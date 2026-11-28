"""图片的小工具：给 AI 看之前先缩小（省 token），检查用户给的图片能不能打开。"""
from __future__ import annotations

import shutil
from pathlib import Path

SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")
MAGIC = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"RIFF", b"GIF8")


def prepare(paths, dest_dir: Path, max_px: int) -> list:
    """把图片缩到最长边不超过 max_px，存成 JPEG 放进 dest_dir，返回新路径。没装 Pillow 就原样拷过去。"""
    out = []
    for index, source in enumerate(paths or []):
        source = Path(source)
        if not source.is_file():
            continue
        try:
            from PIL import Image
            with Image.open(source) as image:
                image = image.convert("RGB")
                image.thumbnail((max_px, max_px))
                target = Path(dest_dir) / ("img-%02d.jpg" % (index + 1))
                image.save(target, "JPEG", quality=85)
        except ImportError:
            target = Path(dest_dir) / ("img-%02d%s" % (index + 1, source.suffix.lower() or ".jpg"))
            shutil.copyfile(source, target)
        except Exception:
            continue  # 这张图坏了，跳过；其余照常
        out.append(target)
    return out


def for_upload(path: Path, dest_dir: Path, limit: int = 500_000):
    """以图搜图上传前把图压到 limit 字节以内（SerpApi 只收 500KB 以内的 jpg、png、webp）。
    本来就够小、格式也对的原样用；否则用 Pillow 缩成 JPEG。做不到（没装 Pillow、图坏了）返回 None。"""
    path = Path(path)
    if not path.is_file():
        return None
    if path.stat().st_size <= limit and path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
        return path
    try:
        from PIL import Image
        with Image.open(path) as image:
            image = image.convert("RGB")
            target = Path(dest_dir) / "lens-upload.jpg"
            for side, quality in ((1600, 85), (1200, 80), (900, 75), (700, 70)):
                copy = image.copy()
                copy.thumbnail((side, side))
                copy.save(target, "JPEG", quality=quality)
                if target.stat().st_size <= limit:
                    return target
    except ImportError:
        return None
    except Exception:
        return None
    return None


def readable(path: Path) -> bool:
    """用户给的图片能不能当图片打开。装了 Pillow 就真的打开验一下，没装只看文件头。"""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        from PIL import Image
    except ImportError:
        with path.open("rb") as handle:
            return handle.read(8).startswith(MAGIC)
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except Exception:
        return False
