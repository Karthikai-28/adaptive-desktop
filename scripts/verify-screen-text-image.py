#!/usr/bin/python3
"""Regression: small text on dark and light panels in the same screenshot."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('screen_text_image', root / 'shell/adaptive-shell@local/tools/screen_text_image.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
image = Image.new('RGB', (800, 280), '#19202b')
draw = ImageDraw.Draw(image)
font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 15)
draw.text((30, 35), 'Save your Access Token', font=font, fill='#d5dae2')
draw.text((30, 85), 'Name Permissions', font=font, fill='#d5dae2')
draw.rectangle((410, 0, 799, 279), fill='white')
draw.text((440, 35), 'Visible image text', font=font, fill='#202020')
draw.text((440, 85), 'Copy these English words', font=font, fill='#202020')
prepared = module.prepare(image)
assert prepared.size == (1600, 560)
assert prepared.getpixel((20, 20)) > 200
assert prepared.getpixel((1000, 20)) > 200
with tempfile.TemporaryDirectory(prefix='adaptive-ocr-test-') as folder:
    path = Path(folder) / 'prepared.png'
    prepared.save(path)
    try:
        result = subprocess.run(['tesseract', str(path), 'stdout', '-l', 'eng', '--psm', '6'],
                                capture_output=True, text=True, check=True, timeout=20)
    except FileNotFoundError:
        print('SKIP real OCR: tesseract not installed; image normalization checks passed')
    else:
        for expected in ['Save your Access Token', 'Name', 'Permissions', 'Visible image text', 'Copy these English words']:
            assert expected in result.stdout, f'OCR missed test phrase: {expected}'
        print('OK: real OCR reads small text in mixed dark/light panels after normalization')
