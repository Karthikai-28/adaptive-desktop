"""3D model and print-file previews: STL, OBJ, 3MF and G-code.

No thumbnailer for these ships with Ubuntu, so Files showed a generic icon.
Previews are made here, in the Files process, and written to the standard
thumbnail cache (freedesktop Thumbnail Managing spec). GIO then reports them
as the file's thumbnail::path and Nautilus draws them like any other
thumbnail - in the grid, the list and the inspector alike.

A system thumbnailer was not an option: GNOME runs thumbnailers in a
bubblewrap sandbox that only sees /usr, and the renderer needs numpy and
Pillow from the user's site-packages.

Everything here is plain data in, plain data out; no GTK.
"""

import base64
import hashlib
import io
import math
import os
import re
import struct
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw, PngImagePlugin
    HAVE_RENDERER = True
except ImportError:  # the inspector still shows G-code/3MF embedded previews
    np = None
    Image = ImageDraw = PngImagePlugin = None
    HAVE_RENDERER = False

MESH_SUFFIXES = {".stl", ".obj", ".3mf"}
GCODE_SUFFIXES = {".gcode", ".gco"}
ALL_SUFFIXES = MESH_SUFFIXES | GCODE_SUFFIXES

THUMB_SIZE = 256
MAX_TRIANGLES = 60000
MAX_MESH_BYTES = 400 * 1024 * 1024

THUMB_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "thumbnails"


def handles(path):
    return Path(path).suffix.casefold() in ALL_SUFFIXES


# ------------------------------------------------------------------
# Meshes
# ------------------------------------------------------------------


def load_mesh(path):
    """Triangles as an (N, 3, 3) float32 array."""
    path = str(path)
    if os.path.getsize(path) > MAX_MESH_BYTES:
        raise ValueError("model is too large to preview")

    suffix = Path(path).suffix.casefold()
    if suffix == ".stl":
        return _load_stl(path)
    if suffix == ".obj":
        return _load_obj(path)
    if suffix == ".3mf":
        return _load_3mf(path)
    raise ValueError(f"not a mesh: {suffix}")


def _load_stl(path):
    size = os.path.getsize(path)
    with open(path, "rb") as handle:
        header = handle.read(84)
        if len(header) == 84:
            count = struct.unpack("<I", header[80:84])[0]
            if 84 + count * 50 == size:
                record = np.dtype(
                    [("normal", "<f4", 3), ("vertices", "<f4", (3, 3)), ("attr", "<u2")]
                )
                data = np.fromfile(handle, dtype=record, count=count)
                return data["vertices"].astype(np.float32)

    # ASCII STL: every "vertex x y z" line, three per facet.
    with open(path, "r", errors="replace") as handle:
        text = handle.read()
    numbers = re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", text)
    if not numbers:
        raise ValueError("no facets found")
    vertices = np.array(numbers, dtype=np.float32)
    usable = (len(vertices) // 3) * 3
    return vertices[:usable].reshape(-1, 3, 3)


def _load_obj(path):
    vertices = []
    faces = []
    with open(path, "r", errors="replace") as handle:
        for line in handle:
            if line.startswith("v "):
                parts = line.split()
                vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif line.startswith("f "):
                indices = []
                for token in line.split()[1:]:
                    index = int(token.split("/")[0])
                    indices.append(index - 1 if index > 0 else len(vertices) + index)
                # Fan-triangulate polygons.
                for i in range(1, len(indices) - 1):
                    faces.append((indices[0], indices[i], indices[i + 1]))
    if not faces:
        raise ValueError("no faces found")
    points = np.array(vertices, dtype=np.float32)
    return points[np.array(faces, dtype=np.int64)]


def _load_3mf(path):
    meshes = []
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".model")]
        for name in names:
            root = ET.fromstring(archive.read(name))
            for mesh in root.iter():
                if not mesh.tag.endswith("}mesh") and mesh.tag != "mesh":
                    continue
                vertices = []
                triangles = []
                for node in mesh.iter():
                    tag = node.tag.rsplit("}", 1)[-1]
                    if tag == "vertex":
                        vertices.append(
                            (float(node.get("x")), float(node.get("y")), float(node.get("z")))
                        )
                    elif tag == "triangle":
                        triangles.append((int(node.get("v1")), int(node.get("v2")), int(node.get("v3"))))
                if vertices and triangles:
                    points = np.array(vertices, dtype=np.float32)
                    meshes.append(points[np.array(triangles, dtype=np.int64)])
    if not meshes:
        raise ValueError("no meshes in 3MF")
    return np.concatenate(meshes)


def mesh_stats(triangles):
    """Bounding box (units are the file's, millimetres for printing) and
    the enclosed volume by the signed-tetrahedron sum."""
    flat = triangles.reshape(-1, 3)
    low = flat.min(axis=0)
    high = flat.max(axis=0)
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    volume = float(abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0)
    return {
        "triangles": int(len(triangles)),
        "size": tuple(float(v) for v in (high - low)),
        "volume": volume,
    }


def render(triangles, size=THUMB_SIZE):
    """Flat-shaded, three-quarter view, transparent background.

    Painter's algorithm at 2x then a Lanczos downscale for anti-aliasing:
    drawing each triangle anti-aliased would leave hairline seams between
    neighbours.
    """
    if not HAVE_RENDERER:
        raise RuntimeError("numpy/Pillow unavailable")

    tris = triangles
    if len(tris) > MAX_TRIANGLES:
        pick = np.random.default_rng(7).choice(len(tris), MAX_TRIANGLES, replace=False)
        tris = tris[np.sort(pick)]

    flat = tris.reshape(-1, 3)
    center = (flat.min(axis=0) + flat.max(axis=0)) / 2.0
    points = flat - center

    # Z is up in printing formats. Turn 35 degrees about Z, then tip the
    # model 60 degrees back so the camera looks slightly down on it.
    yaw = math.radians(-35.0)
    pitch = math.radians(-60.0)
    rz = np.array([[math.cos(yaw), -math.sin(yaw), 0], [math.sin(yaw), math.cos(yaw), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]])
    view = points @ (rx @ rz).T
    view = view.reshape(-1, 3, 3)

    xy = view[:, :, :2]
    extent = float(np.abs(xy).max()) or 1.0
    scale = (size * 2 * 0.44) / extent
    canvas = size * 2
    screen = xy * scale
    screen[:, :, 0] += canvas / 2.0
    screen[:, :, 1] = canvas / 2.0 - screen[:, :, 1]

    normals = np.cross(view[:, 1] - view[:, 0], view[:, 2] - view[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    lengths[lengths == 0] = 1.0
    normals /= lengths[:, None]
    light = np.array([-0.35, 0.45, 0.82])
    light /= np.linalg.norm(light)
    lambert = np.abs(normals @ light)
    shade = 0.30 + 0.70 * lambert

    # Light graphite material; reads on both the dark grid and white.
    base = np.array([214.0, 214.0, 220.0])
    colors = np.clip(base[None, :] * shade[:, None], 0, 255).astype(np.uint8)

    depth = view[:, :, 2].mean(axis=1)
    order = np.argsort(depth)

    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    polygons = screen[order].tolist()
    fills = colors[order].tolist()
    for polygon, fill in zip(polygons, fills):
        draw.polygon([tuple(p) for p in polygon], fill=(fill[0], fill[1], fill[2], 255))

    image = image.resize((size, size), Image.LANCZOS)
    box = image.getbbox()
    if box:
        image = image.crop(box)
        framed = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        framed.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
        image = framed
    return image


# ------------------------------------------------------------------
# Slicer output
# ------------------------------------------------------------------

_GCODE_FIELDS = {
    # PrusaSlicer / SuperSlicer / OrcaSlicer
    "estimated printing time (normal mode)": "time",
    "estimated printing time": "time",
    "filament used [g]": "grams",
    "total filament used [g]": "grams",
    "filament used [mm]": "millimetres",
    "filament_type": "material",
    "layer_height": "layer_height",
    "nozzle_diameter": "nozzle",
    "printer_model": "printer",
    "filament_settings_id": "filament",
    "print_settings_id": "profile",
    # Cura
    "TIME": "seconds",
    "Filament used": "metres",
    "LAYER_COUNT": "layers",
    "FLAVOR": "flavor",
}


def gcode_info(path):
    """Embedded preview (largest PNG) and print statistics.

    Slicers write the preview at the top and the statistics near the end,
    so only the first and last 256 KB are read, however large the file.
    """
    size = os.path.getsize(path)
    with open(path, "rb") as handle:
        head = handle.read(256 * 1024)
        tail = b""
        if size > len(head):
            handle.seek(max(len(head), size - 256 * 1024))
            tail = handle.read()
    text = (head + b"\n" + tail).decode("utf-8", errors="replace")

    previews = []
    for match in re.finditer(
        r"^; thumbnail begin (\d+)x(\d+) \d+\s*$(.*?)^; thumbnail end",
        text,
        re.M | re.S,
    ):
        width, height = int(match.group(1)), int(match.group(2))
        data = "".join(line[2:].strip() for line in match.group(3).splitlines() if line.startswith(";"))
        try:
            previews.append((width * height, base64.b64decode(data)))
        except Exception:
            continue

    info = {}
    for line in text.splitlines():
        if not line.startswith(";"):
            continue
        body = line.lstrip("; ")
        key, sep, value = body.partition("=") if "=" in body else body.partition(":")
        if not sep:
            continue
        key = key.strip()
        field = _GCODE_FIELDS.get(key)
        if field and field not in info:
            info[field] = value.strip()

    slicer = None
    first = text.split("\n", 1)[0]
    found = re.search(r"generated by (\S+ [\d.]+)", first, re.I)
    if found:
        slicer = found.group(1)
    elif "Cura" in head[:2000].decode("utf-8", "replace"):
        slicer = "Cura"

    previews.sort(reverse=True)
    return {
        "preview": previews[0][1] if previews else None,
        "fields": info,
        "slicer": slicer,
    }


def threemf_preview(path):
    try:
        with zipfile.ZipFile(path) as archive:
            for name in ("Metadata/thumbnail.png", "Metadata/plate_1.png"):
                if name in archive.namelist():
                    return archive.read(name)
    except (OSError, zipfile.BadZipFile):
        pass
    return None


def preview_image(path):
    """A PIL image for the file: the slicer's own picture when there is
    one, else a render of the mesh."""
    suffix = Path(path).suffix.casefold()
    embedded = None
    if suffix in GCODE_SUFFIXES:
        embedded = gcode_info(path)["preview"]
    elif suffix == ".3mf":
        embedded = threemf_preview(path)

    if embedded is not None and Image is not None:
        image = Image.open(io.BytesIO(embedded))
        image.load()
        return image.convert("RGBA")

    if suffix in MESH_SUFFIXES:
        return render(load_mesh(path))
    return None


# ------------------------------------------------------------------
# Thumbnail cache
# ------------------------------------------------------------------


def cached_thumbnail(uri, mtime):
    """Path of a valid large thumbnail for uri, or None."""
    digest = hashlib.md5(uri.encode("utf-8")).hexdigest()
    for folder in ("x-large", "large", "normal"):
        candidate = THUMB_DIR / folder / f"{digest}.png"
        if not candidate.exists():
            continue
        try:
            with Image.open(candidate) as image:
                if int(image.info.get("Thumb::MTime", "-1")) == int(mtime):
                    return candidate
        except Exception:
            continue
    return None


def write_thumbnail(uri, path, image):
    """Store image as the file's large thumbnail and nudge Files to reload.

    uri must be GIO's own spelling of the file's URI: the cache is keyed on
    its MD5, and Python's quoting escapes characters GIO leaves alone.
    """
    st = os.stat(path)
    digest = hashlib.md5(uri.encode("utf-8")).hexdigest()
    folder = THUMB_DIR / "large"
    folder.mkdir(parents=True, exist_ok=True)

    image = image.copy()
    image.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)

    meta = PngImagePlugin.PngInfo()
    meta.add_text("Thumb::URI", uri)
    meta.add_text("Thumb::MTime", str(int(st.st_mtime)))
    meta.add_text("Thumb::Size", str(st.st_size))
    meta.add_text("Software", "Adaptive Files")

    handle, temp = tempfile.mkstemp(dir=folder, suffix=".png")
    os.close(handle)
    try:
        image.save(temp, "PNG", pnginfo=meta)
        os.chmod(temp, 0o600)
        os.replace(temp, folder / f"{digest}.png")
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

    failed = THUMB_DIR / "fail" / "gnome-thumbnail-factory" / f"{digest}.png"
    if failed.exists():
        failed.unlink()

    # Nautilus only re-reads a file's info (and so its thumbnail::path) when
    # its monitor reports a change. Re-setting the times it already has
    # changes nothing visible but raises inotify IN_ATTRIB, which is exactly
    # that report.
    try:
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    except OSError:
        pass

    return folder / f"{digest}.png"
