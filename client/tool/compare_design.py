"""Create review sheets from source exports and iOS integration screenshots.

Requires Pillow. This is inspection tooling; no screen bitmap is used by the app.
"""
from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[2]
source = root / 'UI_figma/output/TradePilot-Figma-UI'
out = root / 'client/docs/design-review'
for start in range(0, 35, 7):
    sheet = Image.new('RGB', (7 * 390, 2 * 844 + 40), '#e9e9e7')
    draw = ImageDraw.Draw(sheet)
    for col, i in enumerate(range(start, min(start + 7, 35))):
        original = Image.open(source / f'screen-{i+1}.png').resize((390, 844))
        rendered = Image.open(out / f'reference-{i+1}.png').resize((390, 844))
        sheet.paste(original, (col * 390, 20))
        sheet.paste(rendered, (col * 390, 884))
        draw.text((col * 390 + 12, 0), f'{i+1} / ORIGINAL', fill='black')
        draw.text((col * 390 + 12, 865), f'{i+1} / FLUTTER', fill='black')
    sheet.save(out / f'contact-{start//7+1}.png')
canvas = Image.new('RGB', (780, 844))
canvas.paste(Image.open(source / 'screen-1.png').resize((390, 844)), (0, 0))
canvas.paste(Image.open(out / 'reference-1.png').resize((390, 844)), (390, 0))
canvas.save(out / 'compare-watchlist.png')
