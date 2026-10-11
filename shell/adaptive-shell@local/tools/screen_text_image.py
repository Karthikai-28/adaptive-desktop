#!/usr/bin/python3
"""Prepare screen pixels for OCR; preserve geometry and both light/dark panels."""
import json
import math
import sys

from PIL import Image, ImageFilter, ImageOps

MAX_PIXELS = 16_000_000


def prepare(image):
    gray = image.convert('L')
    # Estimate background polarity locally: one desktop may contain both a
    # white document and a dark image. A whole-screen inversion breaks one.
    light_background = gray.filter(ImageFilter.GaussianBlur(16)).point(
        lambda value: 255 if value >= 128 else 0)
    normalized = Image.composite(gray, ImageOps.invert(gray), light_background)
    normalized = ImageOps.autocontrast(normalized)
    scale = max(1, min(2, math.sqrt(MAX_PIXELS / (image.width * image.height))))
    size = (round(image.width * scale), round(image.height * scale))
    return normalized.resize(size, getattr(Image, 'Resampling', Image).LANCZOS)


def main():
    with Image.open(sys.argv[1]) as image:
        normalized = prepare(image)
    # The caller supplies a path in its private, session-scoped directory.
    normalized.save(sys.argv[2], format='PNG')
    print(json.dumps({'width': normalized.width, 'height': normalized.height}))


if __name__ == '__main__':
    main()
