"""把多张图拼成一张带编号的拼图，给 AI 一次看很多件外观（省 token）。需要 Pillow。"""
from __future__ import annotations

from pathlib import Path

CELL = 300
LABEL_HEIGHT = 30
COLUMNS = 4
ROWS = 3
PER_SHEET = COLUMNS * ROWS


def available() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def _font(size: int):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # 老版本的 Pillow 不能指定字号
        return ImageFont.load_default()


def trim(picture):
    """裁掉四周的白边。专利局给的是整页扫描，图只占中间一块；不裁的话缩进小格子里就看不清了。"""
    from PIL import ImageChops
    try:
        box = ImageChops.invert(picture.convert("L").point(lambda value: 255 if value > 235 else 0)).getbbox()
    except Exception:
        return picture
    if not box:
        return picture
    left, top, right, bottom = box
    pad = 12
    box = (max(0, left - pad), max(0, top - pad), min(picture.width, right + pad), min(picture.height, bottom + pad))
    return picture.crop(box) if (box[2] - box[0]) > 20 and (box[3] - box[1]) > 20 else picture


def grid(items: list, dest: Path, columns: int = COLUMNS, missing: list = None, cell: int = CELL) -> Path:
    """items 是 [(编号, 图片路径)]。每格上方一条写编号，下面是等比缩小的图。
    打不开的图那一格写 NO IMAGE，并把编号记进 missing（调用方据此把这一件记成"看不清"）。"""
    from PIL import Image, ImageDraw
    rows = max(1, (len(items) + columns - 1) // columns)
    sheet = Image.new("RGB", (columns * cell, rows * (cell + LABEL_HEIGHT)), "white")
    draw = ImageDraw.Draw(sheet)
    font = _font(22)
    for index, (label, path) in enumerate(items):
        left, top = (index % columns) * cell, (index // columns) * (cell + LABEL_HEIGHT)
        draw.rectangle([left, top, left + cell - 1, top + LABEL_HEIGHT - 1], fill=(24, 52, 46))
        draw.text((left + 8, top + 3), str(label), fill="white", font=font)
        draw.rectangle([left, top + LABEL_HEIGHT, left + cell - 1, top + LABEL_HEIGHT + cell - 1], outline=(200, 208, 200))
        try:
            with Image.open(path) as picture:
                picture = trim(picture.convert("RGB"))
                picture.thumbnail((cell - 12, cell - 12))
                sheet.paste(picture, (left + (cell - picture.width) // 2, top + LABEL_HEIGHT + (cell - picture.height) // 2))
        except Exception:
            draw.text((left + cell // 4, top + LABEL_HEIGHT + cell // 2 - 12), "NO IMAGE", fill=(120, 120, 120), font=font)
            if missing is not None:
                missing.append(label)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, "JPEG", quality=88)
    return dest


def sheets(items: list, dest_dir: Path, prefix: str, missing: list = None) -> list:
    """每 12 件拼一张，返回各张拼图的路径。"""
    out = []
    for start in range(0, len(items), PER_SHEET):
        out.append(grid(items[start:start + PER_SHEET], Path(dest_dir) / ("%s-%02d.jpg" % (prefix, start // PER_SHEET + 1)), missing=missing))
    return out
