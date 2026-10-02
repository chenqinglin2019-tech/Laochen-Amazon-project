"""Expose only retained, hash-bound public materials from the frozen input."""
import hashlib
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def retained_bundle(frozen, task_dir):
    root = Path(task_dir).resolve()
    materials, images, seen = [], {}, {}

    def visit(value, ref):
        if isinstance(value, list):
            for child in value:
                visit(child, ref)
            return
        if not isinstance(value, dict):
            return
        path, digest = value.get('path'), value.get('sha256')
        url = value.get('source_url')
        if path and digest and isinstance(url, str) and url.startswith(('https://', 'http://')):
            original = Path(path)
            resolved = original.resolve()
            try:
                relative = resolved.relative_to(root)
            except ValueError:
                raise ValueError('REVIEW_MATERIAL_OUTSIDE_TASK') from None
            if original.is_symlink() or any(part.startswith('.') for part in relative.parts):
                raise ValueError('REVIEW_MATERIAL_PRIVATE_OR_LINK')
            key = (str(resolved), digest)
            if key not in seen:
                data = resolved.read_bytes()
                if hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError('REVIEW_MATERIAL_HASH_CHANGED')
                if len(data) > 16 * 1024 * 1024:
                    raise ValueError('REVIEW_MATERIAL_TOO_LARGE')
                suffix = resolved.suffix.lower()
                row = {'material_id': 'M' + str(len(materials) + 1),
                       'source_refs': [ref], 'sha256': digest, 'bytes': len(data),
                       'name': resolved.name}
                if suffix in ('.jpg', '.jpeg', '.png', '.webp'):
                    valid = (data.startswith(b'\xff\xd8\xff') or data.startswith(b'\x89PNG\r\n\x1a\n') or
                             data[:4] == b'RIFF' and data[8:12] == b'WEBP')
                    if not valid:
                        raise ValueError('REVIEW_MATERIAL_IMAGE_INVALID')
                    row['kind'] = 'attached_image'
                    row['bundle_name'] = row['material_id'] + suffix
                    images[row['bundle_name']] = data
                elif suffix in ('.html', '.htm', '.txt', '.pdf'):
                    if suffix == '.pdf':
                        from pypdf import PdfReader
                        pdf = PdfReader(BytesIO(data))
                        text = '\n'.join(f'[page {i + 1}]\n' + (page.extract_text() or '')
                                         for i, page in enumerate(pdf.pages))
                        row['kind'] = 'pdf_text_only'
                        row['limitations'] = 'PDF images/layout not supplied; empty extracted text is not negative evidence'
                    else:
                        text = data.decode('utf-8-sig')
                        if suffix != '.txt':
                            parser = VisibleText()
                            parser.feed(text)
                            text = '\n'.join(parser.parts)
                        row['kind'] = 'retained_text'
                    row['text'] = text
                    row['text_sha256'] = hashlib.sha256(text.encode()).hexdigest()
                else:
                    raise ValueError('REVIEW_MATERIAL_UNSUPPORTED')
                materials.append(row)
                seen[key] = row
            elif ref not in seen[key]['source_refs']:
                seen[key]['source_refs'].append(ref)
        for child in value.values():
            visit(child, ref)

    used = {ref for item_id, item in frozen['items'].items() if item_id not in frozen.get('reuse', {})
            for ref in item.get('evidence_refs', []) + item.get('outcome_refs', [])}
    for ref, fact in sorted(frozen['source_facts'].items()):
        if ref not in used:
            continue
        row = fact.get('row', {})
        # A user-file path is not permission to send it to an external model.
        if row.get('provider') not in ('public_source', 'amazon_browser') and row.get('source') != 'amazon_browser':
            continue
        visit(row, ref)
    if not images:
        raise ValueError('REVIEW_MATERIAL_NO_FROZEN_PUBLIC_IMAGE')
    if len(images) > 12 or sum(len(data) for data in images.values()) > 32 * 1024 * 1024:
        raise ValueError('REVIEW_MATERIAL_BUNDLE_TOO_LARGE')
    if sum(len(row.get('text', '')) for row in materials) > 120000:
        raise ValueError('REVIEW_MATERIAL_TEXT_TOO_LARGE')
    return {'revision': 'retained-material-bundle-v1', 'materials': materials}, images
