#!/usr/bin/env python3
"""Make the glass backdrop: the wallpaper, cropped to the screen's shape and blurred once.

    glass_wallpaper.py SOURCE WIDTH HEIGHT DEST

Files and Home are drawn as a graphite tint over this picture. It is made when the wallpaper
changes, not while anything moves, so nothing is blurred live: a small PNG the shell and the Home
page stretch over the screen. Blurred this heavily, a 640 px wide picture is indistinguishable
from a full-size one.

Pillow when it is installed, ImageMagick's convert otherwise. Exit status 0 and DEST written, or
non-zero and DEST untouched.
"""

import os
import shutil
import subprocess
import sys
import tempfile

OUT_WIDTH = 640
# In output pixels: about 40 px on a 1920 px screen, the strength the live blur had.
BLUR = 13
SATURATION = 1.25


def with_pillow(source, width, height, dest):
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    image = Image.open(source)
    image.draft("RGB", (OUT_WIDTH * 2, height * 2))      # decode a JPEG small: no need for all of it
    image = ImageOps.exif_transpose(image).convert("RGB")
    image = ImageOps.fit(image, (OUT_WIDTH, height), Image.BILINEAR, centering=(0.5, 0.5))
    image = image.filter(ImageFilter.GaussianBlur(BLUR))
    image = ImageEnhance.Color(image).enhance(SATURATION)
    image.save(dest, "PNG")


def with_convert(source, width, height, dest):
    size = f"{OUT_WIDTH}x{height}"
    subprocess.run(["convert", f"{source}[0]", "-auto-orient", "-resize", f"{size}^", "-gravity", "center",
                    "-extent", size, "-blur", f"0x{BLUR}", "-modulate", f"100,{int(SATURATION * 100)},100",
                    f"PNG:{dest}"], check=True, capture_output=True, timeout=60)


def main(argv):
    if len(argv) != 5:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    source, dest = argv[1], argv[4]
    try:
        screen_w, screen_h = max(1, int(argv[2])), max(1, int(argv[3]))
    except ValueError:
        return 2
    if not os.path.isfile(source):
        print(f"no such picture: {source}", file=sys.stderr)
        return 1
    height = max(1, round(OUT_WIDTH * screen_h / screen_w))
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    handle, partial = tempfile.mkstemp(suffix=".png", dir=os.path.dirname(dest) or ".")
    os.close(handle)
    try:
        try:
            with_pillow(source, OUT_WIDTH, height, partial)
        except ImportError:
            if not shutil.which("convert"):
                print("needs Pillow or ImageMagick", file=sys.stderr)
                return 1
            with_convert(source, OUT_WIDTH, height, partial)
        os.replace(partial, dest)        # readers see the old picture or the new one, never half
        return 0
    except Exception as error:           # a picture that will not decode must not leave a broken DEST
        print(f"could not make the glass backdrop: {error}", file=sys.stderr)
        return 1
    finally:
        if os.path.exists(partial):
            os.unlink(partial)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
