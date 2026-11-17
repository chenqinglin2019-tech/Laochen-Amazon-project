"""r10 (eu-scope-v1): keep a final-review module packet within the review host's prompt limit.

Run of 2026-11-17 (EU + DE, eight selected EP patents): the technical module carried the lossless full texts of eight
European patents - the EPO publication XML with its claims in three languages and the whole description, the Google
Patents page and the PDF of the same documents, plus the descriptions inside the API detail records - about two
million characters against the 1,048,576 limit (``REPORT_REVIEW_HOST_INPUT_TOO_LARGE_AFTER_LOSSLESS_ENCODING``) and
the run ended without a report.

Only a packet the host would refuse (over ``HOST_LIMIT``) is changed; it is brought to ``BUDGET`` in this order,
stopping as soon as it fits:

1. description fields inside inline records (API detail records, EPO documents) are replaced by a short note;
2. retained patent texts keep their front matter and claims, the description is left out (``omitted_sections``);
3. the longest texts are cut to their share of the remaining room (at least ``FLOOR`` characters each);
4. the longest texts are not transmitted at all.

Every change is listed in ``packet['review_packet_budget']`` and on the material row itself (``budget_trimmed``,
``limitations``); the retained originals, their hashes, the frozen input and the evidence registry are unchanged and
every evidence id stays citable. A packet the host accepts today is not touched.
"""
from __future__ import annotations

import json
import re
from xml.etree import ElementTree

from common import sha256_json

REVISION = 'review-budget-v1'
HOST_LIMIT = 1048576
BUDGET = 900000              # below the host limit, leaving room for the retry feedback a repaired turn appends
FLOOR = 6000
INLINE_FIELDS = ('description', 'description_translated', 'descriptions', 'description_text', 'full_text')
INLINE_MIN = 3000
NOTE = ('[r10 终审材料预算：说明书全文未随终审材料发送；原件完整留存于证据目录，可按证据编号引用。'
        'Description omitted from the review packet by the size budget; the retained original is complete and citable.]')
CLAIM_HEADINGS = ('claims', 'patentansprüche', 'patentanspruche', 'revendications', 'what is claimed is',
                  'what is claimed:', 'i claim:', 'we claim:', 'the invention claimed is')


def enabled(task) -> bool:
    import eu_scope
    return eu_scope.enabled(task)


def prompt_chars(packet) -> int:
    from report_review_host import review_prompt
    return max(len(review_prompt(packet, 1)), len(review_prompt(packet, 2)))


def _encoded(value) -> int:
    return len(json.dumps(value, ensure_ascii=True))


# ----- 1. inline description fields -------------------------------------------------------------------------------
def _inline_rows(packet):
    """(container, key, size) of long patent-record description fields outside the transmitted originals."""
    found = []
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'retained_originals':
                    continue
                # only a patent record's own description (never a product description)
                if (key in INLINE_FIELDS and child not in (None, '', []) and child != NOTE
                        and ('publication_number' in value or 'claims' in value)):
                    size = _encoded(child)
                    if size >= INLINE_MIN:
                        found.append((value, key, size))
                        continue
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(packet)
    return found


# ----- 2. retained patent texts: front matter and claims --------------------------------------------------------------
def _xml_claims(text):
    try:
        root = ElementTree.fromstring(text.encode('utf-8'))
    except (ElementTree.ParseError, ValueError):
        return None
    if root.tag.rsplit('}', 1)[-1] != 'ep-patent-document':
        return None
    flat = lambda node: ' '.join(' '.join(node.itertext()).split())
    head = ['EP%s%s (%s)' % (root.attrib.get('doc-number', ''), root.attrib.get('kind', ''), root.attrib.get('lang', ''))]
    for node in root.iter():
        name = node.tag.rsplit('}', 1)[-1]
        if name in {'B541', 'B542'} or name == 'abstract':
            head.append(flat(node))
    groups = [node for node in root.iter() if node.tag.rsplit('}', 1)[-1] == 'claims']
    if not groups:
        return None
    parts = head + ['Description', '[omitted]']
    for group in groups:
        parts.append('Claims (%s)' % group.attrib.get('lang', ''))
        parts.extend(flat(claim) for claim in group if claim.tag.rsplit('}', 1)[-1] == 'claim')
    return '\n'.join(part for part in parts if part)


def condense(text):
    """(text, method) keeping the front matter and the claims of a patent text, or (text, None)."""
    if not isinstance(text, str):
        return text, None
    stripped = text.lstrip()
    if stripped.startswith('<') and 'ep-patent-document' in stripped[:2000]:
        result = _xml_claims(stripped)
        return (result, 'xml_claims') if result and len(result) < len(text) else (text, None)
    from module_review import related_excerpt
    for pdf in (False, True):
        result, cut = related_excerpt(text, pdf=pdf)
        if cut and len(result) < len(text):
            return result, 'description_omitted'
    lines = text.split('\n')
    marks = [index for index, line in enumerate(lines) if line.strip().casefold().rstrip(':') in
             {heading.rstrip(':') for heading in CLAIM_HEADINGS} or re.match(r'^claims \(\d+\)$', line.strip().casefold())]
    if marks and marks[0] > 20:
        first = marks[0]
        head = next((index for index, line in enumerate(lines[:first])
                     if line.strip().casefold() in {'description', 'beschreibung', 'description of embodiments'}), None)
        keep = lines[:head if head is not None else min(20, first)]
        result = '\n'.join(keep + ['[description omitted]'] + lines[first:])
        if len(result) < len(text):
            return result, 'description_omitted'
    return text, None


def _texts(packet):
    rows = ((packet.get('retained_originals') or {}).get('materials') or [])
    return [row for row in rows if isinstance(row, dict) and isinstance(row.get('text'), str)
            and row.get('kind') in {'original_text', 'pdf_text_extraction'}]


def _replace(row, text, method, note):
    original = row.setdefault('budget_trimmed', {'revision': REVISION, 'original_chars': len(row['text'])})
    original['method'] = method
    original['sent_chars'] = len(text)
    row['text'] = text
    row['text_sha256'] = sha256_json(text)
    if method in {'xml_claims', 'description_omitted'}:
        row['omitted_sections'] = sorted(set(row.get('omitted_sections') or []) | {'Description'})
    row['limitations'] = (str(row.get('limitations') or '') + ' ' + note).strip()


def fit(packet, *, budget=BUDGET, trigger=HOST_LIMIT):
    """Bring a module packet over ``trigger`` prompt characters to ``budget``; returns the record or None."""
    if not enabled(packet.get('task') or {}):
        return None
    size = prompt_chars(packet)
    if size <= trigger:
        return None
    record = {'revision': REVISION, 'budget': budget, 'host_limit': HOST_LIMIT, 'prompt_chars_before': size, 'steps': []}
    # 1
    rows = _inline_rows(packet)
    for container, key, chars in rows:
        container[key] = NOTE
    if rows:
        record['steps'].append({'step': 'inline_descriptions', 'fields': len(rows), 'chars': sum(r[2] for r in rows)})
        size = prompt_chars(packet)
    # 2
    if size > budget:
        changed = 0
        for row in sorted(_texts(packet), key=lambda item: -len(item['text'])):
            text, method = condense(row['text'])
            if method:
                _replace(row, text, method, 'Review budget (r10): only the front matter and the claims of this '
                         'publication are transmitted; the description is omitted, the retained original stays complete and citable.')
                changed += 1
        if changed:
            record['steps'].append({'step': 'claims_only', 'materials': changed})
            size = prompt_chars(packet)
    # 3
    for _ in range(3):
        if size <= budget:
            break
        texts = sorted(_texts(packet), key=lambda item: -len(item['text']))
        total = sum(len(row['text']) for row in texts)
        if not texts or total <= FLOOR * len(texts):
            break
        ratio = max(0.0, 1 - (size - budget) * 1.1 / total)
        cut = 0
        for row in texts:
            keep = max(FLOOR, int(len(row['text']) * ratio))
            if keep < len(row['text']):
                omitted = len(row['text']) - keep
                _replace(row, row['text'][:keep] + '\n[... %d characters omitted by the review budget ...]' % omitted,
                         'truncated', 'Review budget (r10): only the first %d characters of this text are transmitted; '
                         'the retained original stays complete and citable.' % keep)
                cut += 1
        record['steps'].append({'step': 'truncated', 'materials': cut})
        size = prompt_chars(packet)
    # 4
    dropped = 0
    while size > budget:
        texts = [row for row in sorted(_texts(packet), key=lambda item: -len(item['text']))
                 if (row.get('budget_trimmed') or {}).get('method') != 'not_transmitted']
        if not texts:
            break
        row = texts[0]
        _replace(row, '[text not transmitted by the review budget]', 'not_transmitted',
                 'Review budget (r10): this text is not transmitted; the retained original stays complete and citable.')
        dropped += 1
        size = prompt_chars(packet)
    if dropped:
        record['steps'].append({'step': 'not_transmitted', 'materials': dropped})
    record['prompt_chars_after'] = size
    record['fits'] = size <= HOST_LIMIT
    packet['review_packet_budget'] = record
    return record
