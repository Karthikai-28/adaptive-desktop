"""Document pages and photo metadata for the inspector.

PDF pages are rendered by pdftoppm (poppler-utils) into a private cache, so
paging through a document never re-renders a page already seen. Photo
metadata comes from GExiv2, which reads EXIF, IPTC and XMP alike.
"""

import datetime
import hashlib
import os
import re
import subprocess
from pathlib import Path

import gi

from gi.repository import GLib  # noqa: E402

try:
    gi.require_version("GExiv2", "0.10")
    from gi.repository import GExiv2  # noqa: E402
    HAVE_EXIV2 = True
except (ValueError, ImportError):
    GExiv2 = None
    HAVE_EXIV2 = False

PAGE_CACHE = Path(GLib.get_user_cache_dir()) / "adaptive-files" / "pages"


def pdf_page_count(path):
    proc = subprocess.run(
        ["pdfinfo", path], capture_output=True, text=True, timeout=5, check=False
    )
    found = re.search(r"^Pages:\s+(\d+)", proc.stdout, re.M)
    return int(found.group(1)) if found else 0


def pdf_page(path, page, width):
    """PNG of one page, width pixels wide."""
    st = os.stat(path)
    key = hashlib.sha1(f"{path}:{st.st_mtime_ns}:{page}:{width}".encode()).hexdigest()[:24]
    PAGE_CACHE.mkdir(parents=True, exist_ok=True)
    target = PAGE_CACHE / f"{key}.png"
    if target.exists():
        return str(target)

    stem = PAGE_CACHE / key
    subprocess.run(
        ["pdftoppm", "-f", str(page), "-l", str(page), "-scale-to-x", str(width),
         "-scale-to-y", "-1", "-png", "-singlefile", path, str(stem)],
        capture_output=True,
        timeout=20,
        check=False,
    )
    if not target.exists():
        raise RuntimeError("page could not be rendered")
    return str(target)


def photo_details(path):
    """Camera facts worth a glance, in display order; empty when the file
    carries none."""
    if not HAVE_EXIV2:
        return {}
    metadata = GExiv2.Metadata()
    try:
        metadata.open_path(path)
    except GLib.Error:
        return {}

    def tag(name):
        try:
            if metadata.has_tag(name):
                return (metadata.get_tag_interpreted_string(name) or "").strip()
        except GLib.Error:
            pass
        return ""

    details = {}
    make = tag("Exif.Image.Make")
    model = tag("Exif.Image.Model")
    if model:
        details["Camera"] = model if not make or model.startswith(make) else f"{make} {model}"
    lens = tag("Exif.Photo.LensModel")
    if lens:
        details["Lens"] = lens

    # GExiv2's getters return -1 (or 0) for "not recorded".
    settings = []
    for getter, fmt in (
        (metadata.get_focal_length, "{:g} mm"),
        (metadata.get_fnumber, "ƒ/{:g}"),
        (metadata.get_iso_speed, "ISO {}"),
    ):
        try:
            value = getter()
        except Exception:
            continue
        if value and value > 0:
            settings.append(fmt.format(round(value, 1) if isinstance(value, float) else value))
    try:
        top, bottom = metadata.get_exposure_time()
        if top > 0 and bottom > 0:
            shutter = f"1/{round(bottom / top)} s" if top < bottom else f"{top / bottom:g} s"
            settings.insert(min(2, len(settings)), shutter)
    except Exception:
        pass
    if settings:
        details["Exposure"] = "  ·  ".join(settings)

    taken = tag("Exif.Photo.DateTimeOriginal")
    if taken:
        try:
            moment = datetime.datetime.strptime(taken[:19], "%Y:%m:%d %H:%M:%S")
            details["Taken"] = moment.strftime("%b %d, %Y · %I:%M %p")
        except ValueError:
            details["Taken"] = taken

    try:
        ok, longitude, latitude, _altitude = metadata.get_gps_info()
    except Exception:
        ok = False
    if ok and (latitude or longitude):
        details["_gps"] = (latitude, longitude)
    return details
