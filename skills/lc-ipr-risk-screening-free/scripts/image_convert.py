"""GIF / TIFF originals as PNG (r5d4).

r5d4 real run B0FSJBDTF2_US_20261012: the USPTO gazette publishes a design's representative view as a GIF. It was
registered as a retained public original, the review reader only reads PNG / JPEG / WEBP and skipped it, and the
complete appearance review was voided at the end (ADAPTIVE_ORIGINAL_MANIFEST_INCOMPLETE) after five minutes of
sessions. A GIF or TIFF image is now carried as a lossless PNG of its first frame (USPTO drawings are single
frames): at registration time the PNG is what is registered, with the original's hash, size, name and format
recorded beside it; an already registered original is converted the same way when the review reads it. The
conversion is deterministic (same bytes in, same PNG out), so packet hashes stay stable.
"""
from __future__ import annotations

from io import BytesIO

CONVERTIBLE = {'.gif': 'GIF', '.tif': 'TIFF', '.tiff': 'TIFF'}
READABLE = {'.png', '.jpg', '.jpeg', '.webp'}
TRANSFORM = 'pillow-png-first-frame-v1'
MAX_PIXELS = 80_000_000


def to_png(data: bytes) -> bytes:
    """Lossless PNG of the first frame of a GIF / TIFF (raises ValueError when the bytes are not such an image)."""
    from PIL import Image
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in {'GIF', 'TIFF'}:
                raise ValueError('IMAGE_CONVERT_FORMAT_UNSUPPORTED:' + str(image.format))
            if image.size[0] * image.size[1] > MAX_PIXELS:
                raise ValueError('IMAGE_CONVERT_TOO_LARGE')
            image.seek(0)
            frame = image.copy()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('IMAGE_CONVERT_UNREADABLE:' + type(exc).__name__) from exc
    if frame.mode == 'P':
        frame = frame.convert('RGBA' if 'transparency' in frame.info else 'RGB')
    elif frame.mode not in {'1', 'L', 'LA', 'RGB', 'RGBA'}:
        frame = frame.convert('RGB')
    out = BytesIO()
    frame.save(out, format='PNG')
    return out.getvalue()


def format_of(suffix: str):
    return CONVERTIBLE.get(str(suffix or '').lower())


# r5d7: the USPTO grant PDF is one scanned page image per page (bilevel TIFF, 2560 x 3300). Its page images are taken
# out with pypdf and Pillow (both already installed), so no PDF renderer (pdftoppm) is needed on Mac or Windows.
PDF_PAGE_TRANSFORM = 'pypdf-embedded-page-image-grayscale-png-max-1600-v1'
PDF_PAGE_MAX_SIDE = 1600


def pdf_page_pngs(data: bytes, *, max_pages: int = 10, max_side: int = PDF_PAGE_MAX_SIDE, max_images=None) -> list:
    """[(page number, PNG bytes)] of a scanned PDF: per page its largest embedded image, grayscale, longest side at
    most ``max_side``. Pages without an image are skipped; raises ValueError when the PDF cannot be read at all.
    ``max_images`` stops after that many page images (r5d24: the design screen looks at the first two only)."""
    try:
        from PIL import Image
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError('PDF_PAGES_READER_UNAVAILABLE: run setup_skill.py to install the bundled pypdf / Pillow') from exc
    try:
        reader = PdfReader(BytesIO(data))
        pages = list(reader.pages)
    except Exception as exc:
        raise ValueError('PDF_PAGES_UNREADABLE:' + type(exc).__name__) from exc
    output = []
    for number, page in enumerate(pages[:max_pages], 1):
        if max_images is not None and len(output) >= max_images:
            break
        try:
            images = [item.image for item in page.images if item.image is not None]
        except Exception:
            continue
        images = [image for image in images if image.size[0] * image.size[1] <= MAX_PIXELS]
        if not images:
            continue
        image = max(images, key=lambda value: value.size[0] * value.size[1])
        frame = image.convert('L')
        scale = max_side / float(max(frame.size))
        if scale < 1:
            frame = frame.resize((max(1, round(frame.size[0] * scale)), max(1, round(frame.size[1] * scale))),
                                 Image.LANCZOS)
        out = BytesIO()
        frame.save(out, format='PNG', optimize=True)
        output.append((number, out.getvalue()))
    return output
