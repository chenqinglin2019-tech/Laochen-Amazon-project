#!/usr/bin/env python3
"""Keep the verification effort on the rights that can matter (new tasks with ``core_focus_revision``).

r5d real run: 30 of 175 candidates were selected (pipe supports, headbands, a drain cleaner ... next to the core
patent), ten of them expired long ago or published only abroad; the ten SerpApi requests went to them in arrival
order and the publication pages the browser then read could never be accepted. This module holds the shared,
deterministic parts of the fix:

* objective facts a program may use to set a card aside (``triage_defaults``): a US utility filing more than 25
  years old (20-year term plus any term adjustment) or a US design granted more than 15 years ago is expired; a
  WO/EP/foreign publication confers no right in the US (its US family member, if any, is a US document of its own);
* the text triage host's priority for each selected candidate (``core`` = the same kind of article for the same use,
  ``related`` = the rest), kept beside the ledger in ``text-triage/priority.json``;
* the public Google Patents page of a document: its address, its claims and drawings. ``core_dossier`` retains it
  for a selected candidate without an exact API record (budget used up) and for the granted publication of an
  application the API record reports as granted, so the element comparison reads the claims that are in force.

Nothing here grades a risk or excludes a candidate by itself; recorders validate every decision.
"""
from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path

REVISION = 'core-focus-v1'
PRIORITY_FILE = ('text-triage', 'priority.json')
PRIORITIES = ('core', 'related')
UTILITY_TERM_YEARS, ADJUSTMENT_MARGIN_YEARS, DESIGN_TERM_YEARS = 20, 5, 15
_YEAR_IN_NUMBER = re.compile(r'^US((?:19|20)\d{2})\d{6,}[A-Z]?$')
_GRANTED_KIND = re.compile(r'^US(?:RE)?\d{5,8}(?:B1|B2|E|S|S1)?$')


def enabled(task) -> bool:
    return isinstance(task, dict) and task.get('core_focus_revision') == REVISION


def _year(value):
    match = _YEAR_IN_NUMBER.match(re.sub(r'[^A-Za-z0-9]', '', str(value or '')).upper())
    return int(match.group(1)) if match else None


def earliest_filing_year(candidate: dict):
    """Year of the candidate's own US application (epodoc spelling USyyyynnnnnn...), or None.

    Only the US application itself is read: a foreign or provisional priority may precede the US filing that starts
    the term, and a continuation's term ends earlier than its own filing year suggests, so this never makes a
    document look older than it is."""
    years = [_year(value) for value in (candidate.get('application_numbers') or []) if isinstance(value, str)]
    years += [_year(candidate.get('application_number'))]
    for key in ('filing_date',):
        text = str(candidate.get(key) or '')
        if re.match(r'^(?:19|20)\d{2}-', text):
            years.append(int(text[:4]))
    years = [year for year in years if year]
    return min(years) if years else None


def expired_by_age(candidate: dict, *, today=None):
    """A short reason when the candidate's own dates prove the US term is over, else None."""
    year = (today or date.today()).year
    number = re.sub(r'[^A-Za-z0-9]', '', str(candidate.get('publication_number') or '')).upper()
    if candidate.get('right_type') == 'design':
        granted = str(candidate.get('publication_date') or candidate.get('grant_date') or '')
        if number.startswith('USD') and re.match(r'^(?:19|20)\d{2}-', granted) \
                and int(granted[:4]) + DESIGN_TERM_YEARS < year:
            return '外观设计 %s 于 %s 授权，美国外观设计保护期最长自授权起 %d 年，已届满' % (number, granted[:10], DESIGN_TERM_YEARS)
        return None
    if candidate.get('right_type') not in {'patent', 'utility_model'} or not number.startswith('US'):
        return None
    filed = earliest_filing_year(candidate)
    if filed and filed + UTILITY_TERM_YEARS + ADJUSTMENT_MARGIN_YEARS < year:
        return ('%s 的美国申请年份为 %d 年；美国发明专利保护期自申请日起 %d 年，即使计入期限调整（留 %d 年余量）'
                '也已届满' % (number, filed, UTILITY_TERM_YEARS, ADJUSTMENT_MARGIN_YEARS))
    return None


def foreign_publication(candidate: dict, task: dict, others):
    """(rule, reason) for a non-US patent publication in a US-only task, else None.

    'family_duplicate' when another candidate of the same EPO family is a US document, 'foreign_publication'
    otherwise. A WO (PCT) or foreign publication grants no right in the US by itself."""
    targets = set(task.get('target_jurisdictions') or [])
    number = re.sub(r'[^A-Za-z0-9]', '', str(candidate.get('publication_number') or '')).upper()
    if targets != {'US'} or candidate.get('right_type') not in {'patent', 'utility_model', 'design'} \
            or not number or number.startswith('US'):
        return None
    family = candidate.get('family_id')
    sibling = next((row.get('publication_number') for row in others if family and row.get('family_id') == family
                    and str(row.get('publication_number') or '').upper().startswith('US')
                    and row.get('candidate_id') != candidate.get('candidate_id')), None)
    if sibling:
        return 'family_duplicate', '%s 是 %s 的同族非美国文献，美国效力由该美国同族文献承担核验' % (number, sibling)
    return 'foreign_publication', ('%s 是国际申请或外国公开文献，本身在美国没有专利效力；若其进入美国，美国同族会以美国号码'
                                   '另行出现在美国检索中' % number)


# ----- text triage priorities -------------------------------------------------------------------------------------
def _priority_path(root):
    return Path(root).joinpath(*PRIORITY_FILE)


def priorities(root) -> dict:
    path = _priority_path(root)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return {key: value for key, value in data.items() if value in PRIORITIES} if isinstance(data, dict) else {}


def save_priorities(root, values: dict):
    from common import atomic_write_json
    current = priorities(root)
    current.update({key: value for key, value in values.items() if value in PRIORITIES})
    path = _priority_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, current)


# ----- public Google Patents pages --------------------------------------------------------------------------------
def page_url(number: str) -> str:
    from common import canonical_patent_number
    return 'https://patents.google.com/patent/%s/en' % canonical_patent_number(number)


def granted_publication(payload: dict):
    """The granted US publication of the same application an API detail record reports, if it is another document."""
    from common import canonical_patent_number
    own = canonical_patent_number(payload.get('publication_number'))
    found = []
    for group in (payload.get('worldwide_applications') or {}).values() if isinstance(payload.get('worldwide_applications'), dict) else []:
        for row in group if isinstance(group, list) else []:
            if isinstance(row, dict) and row.get('this_app') is True:
                found.append(str(row.get('document_id') or ''))
    for row in payload.get('events') or []:
        if isinstance(row, dict) and row.get('type') == 'publication':
            found.append(str(row.get('document_id') or ''))
    for value in found:
        match = re.match(r'^patent/([A-Z0-9]+)/[a-z]{2}$', value)
        number = canonical_patent_number(match.group(1)) if match else ''
        if number and number != own and _GRANTED_KIND.match(number) and not number.endswith('A1'):
            return number
    return None


def page_granted_publication(text: str):
    """The granted US publication of the same application a public Google Patents page lists, if it is another document.

    r7 (search-guard-v1, run B0GFNWR8FW): US20090293905A1 got no API record (quota) and was compared on its published
    claims although its own page lists "Publication of US8156949B2". Same rule as ``granted_publication``: the page's
    publication events and its own application (thisApp), a granted kind other than the page's own number."""
    from common import canonical_patent_number
    own = canonical_patent_number(page_facts(text).get('publication_number'))
    found = []
    for match in re.finditer(r'<dd itemprop="events"[^>]*>(.*?)</dd>', text, flags=re.S):
        block = match.group(1)
        if re.search(r'<span itemprop="type">\s*publication\s*</span>', block):
            document = re.search(r'<span itemprop="documentId">([^<]+)</span>', block)
            if document:
                found.append(document.group(1).strip())
    for match in re.finditer(r'<li itemprop="application"[^>]*>(.*?)</li>', text, flags=re.S):
        block = match.group(1)
        if 'itemprop="thisApp"' in block:
            document = re.search(r'<span itemprop="documentId">([^<]+)</span>', block)
            if document:
                found.append(document.group(1).strip())
    for value in found:
        number_match = re.match(r'^patent/([A-Z0-9]+)/[a-z]{2}$', value)
        number = canonical_patent_number(number_match.group(1)) if number_match else ''
        if number and number != own and _GRANTED_KIND.match(number) and not number.endswith('A1'):
            return number
    return None


def _strip(fragment: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', fragment)
    return ' '.join(html.unescape(text).split())


def page_claims(text: str) -> list:
    """['1. ...', '2. ...'] from a Google Patents page's claims section ([] when absent)."""
    start = text.find('<section itemprop="claims"')
    if start < 0:
        return []
    section = text[start:text.find('</section>', start)]
    # r5d12 (B0GLNPC6K8): older pages number claims without zero padding (num="8") and list cancelled ones as a range
    # (num="1-7" "1-7. (Canceled)"); a 3-5 digit pattern read no claim at all and the candidate was never registered
    parts = re.split(r'<div[^>]*\bnum="(\d{1,5}(?:-\d{1,5})?)"[^>]*class="claim[^"]*"[^>]*>', section)
    claims = []
    for index in range(1, len(parts) - 1, 2):
        body = _strip(parts[index + 1])
        label = parts[index]
        body = re.sub(r'^%s\s*\.\s*' % r'\s*-\s*'.join(str(int(n)) for n in label.split('-')), '', body)
        if '-' in label or re.match(r'^\(?\s*(?:canceled|cancelled|deleted|withdrawn)\s*\)?\s*\.?$', body, re.I):
            continue
        if body:
            claims.append('%d. %s' % (int(label), body))
    return claims


def page_facts(text: str) -> dict:
    """Identity and page-level fields of a Google Patents page (not an official status record)."""
    def meta(name):
        match = re.search(r'<meta\s+name="%s"\s+content="([^"]*)"' % re.escape(name), text)
        return html.unescape(match.group(1)).strip() if match else ''
    number = re.search(r'<dd itemprop="publicationNumber">([^<]+)</dd>', text)
    title = re.search(r'<span itemprop="title">([^<]+)</span>', text) or re.search(r'<title>([^<]+)</title>', text)
    status = re.search(r'<span itemprop="status">([^<]+)</span>', text)
    legal = re.search(r'itemprop="legalStatusIfi"[^>]*>\s*<span itemprop="status">([^<]+)</span>', text)
    expiry = re.search(r'<span itemprop="expiration"[^>]*>[^<]*</span>|itemprop="expiration"[^>]*>([^<]+)<', text)
    images = list(dict.fromkeys(re.findall(r'<meta itemprop="full" content="(https://patentimages[^"]+)"', text)))
    return {'publication_number': (number.group(1).strip() if number else meta('citation_patent_number').replace(':', '')),
            'title': html.unescape(title.group(1)).strip() if title else '',
            'application_status': status.group(1).strip() if status else '',
            'legal_status': legal.group(1).strip() if legal else '',
            'expiration': (expiry.group(1) or '').strip() if expiry and expiry.lastindex else '',
            'pdf': meta('citation_pdf_url'), 'images': images}


def document_claims(text: str) -> list:
    """['1. ...'] from a published document's full text ("Claims" heading followed by numbered claims)."""
    start = max(text.rfind('\nClaims\n'), text.rfind('\nWhat is claimed is'), text.rfind('\nI claim'))
    if start < 0:
        return []
    body = text[start:].split('\n', 2)[-1]
    pieces = re.split(r'(?:^|\n)\s*(\d{1,3})\s*\.\s+', '\n' + body)
    claims = []
    for index in range(1, len(pieces) - 1, 2):
        value = ' '.join(pieces[index + 1].split())
        if value:
            claims.append('%s. %s' % (pieces[index], value))
    return claims
