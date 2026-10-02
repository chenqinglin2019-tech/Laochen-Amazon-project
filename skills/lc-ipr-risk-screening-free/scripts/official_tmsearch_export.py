"""Read retained USPTO TMsearch XLSX exports as bounded, traceable result rows.

The workbook is evidence, not an instruction source. This module makes no
network requests and never treats an exported search result as a legal finding.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
import re
import zipfile
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from common import resolve_retained_path

X = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
D = '{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
P = '{http://schemas.openxmlformats.org/package/2006/relationships}'
HEADERS = ('SerialNumber', 'Wordmark', 'Image', 'Status', 'GoodsAndServicesTruncated',
    'Basis', 'FiledDate', 'InternationalClass', 'OwnerFullText', 'PriorityDate',
    'RegistrationDate', 'RegistrationNumber', 'RegistrationType', 'SupplementalRegistrationDate')
MAX_UNCOMPRESSED = 64 * 1024 * 1024


def registered_sources(evidence):
    for entry in evidence.get('collections', {}).get('sources', []):
        if not isinstance(entry, dict) or entry.get('provider') != 'public_source' or entry.get('kind') != 'official_record':
            continue
        payload = entry.get('payload') or {}
        path = str(entry.get('path') or payload.get('path') or '')
        url = str(entry.get('source_url') or payload.get('source_url') or '')
        parsed = urlsplit(url)
        if (Path(path).suffix.lower() == '.xlsx' and parsed.scheme == 'https'
                and parsed.hostname == 'tmsearch.uspto.gov'
                and str(entry.get('jurisdiction') or payload.get('jurisdiction') or '').upper() == 'US'
                and entry.get('right_type') in {'trademark', 'trademark_word', 'trademark_figurative'}):
            yield entry


def _cells(row, strings):
    result = {}
    for cell in row.findall(X + 'c'):
        address = cell.get('r') or ''
        match = re.fullmatch(r'([A-Z]+)[0-9]+', address)
        if not match:
            continue
        value = cell.findtext(X + 'v')
        if cell.get('t') == 's' and value is not None:
            try:
                value = strings[int(value)]
            except (ValueError, IndexError):
                raise ValueError('TMSEARCH_EXPORT_STRING_INDEX_INVALID') from None
        elif cell.get('t') == 'inlineStr':
            value = ''.join(node.text or '' for node in cell.findall('.//' + X + 't'))
        result[match.group(1)] = value or ''
    return result


def _column(number):
    value = ''
    while number:
        number, remainder = divmod(number - 1, 26)
        value = chr(65 + remainder) + value
    return value


def _images(archive, names):
    if 'xl/drawings/drawing1.xml' not in names:
        return {}
    if 'xl/drawings/_rels/drawing1.xml.rels' not in names:
        raise ValueError('TMSEARCH_EXPORT_IMAGE_RELATION_MISSING')
    relationships = ET.fromstring(archive.read('xl/drawings/_rels/drawing1.xml.rels'))
    members = {}
    for rel in relationships.findall(P + 'Relationship'):
        if rel.get('TargetMode') == 'External' or not str(rel.get('Type') or '').endswith('/image'):
            continue
        target = str(rel.get('Target') or '')
        member = 'xl/' + target.removeprefix('../')
        if not re.fullmatch(r'xl/media/[A-Za-z0-9._-]+\.(?:png|jpe?g)', member) or member not in names:
            raise ValueError('TMSEARCH_EXPORT_IMAGE_PATH_INVALID')
        members[rel.get('Id')] = member
    drawing = ET.fromstring(archive.read('xl/drawings/drawing1.xml'))
    by_row = {}
    for anchor in drawing:
        row = anchor.findtext(D + 'from/' + D + 'row')
        if row is None:
            continue
        for blip in anchor.findall('.//' + A + 'blip'):
            member = members.get(blip.get(R + 'embed'))
            if member:
                by_row.setdefault(int(row) + 1, []).append(member)
    return by_row


def parse_export(task_dir, entry, *, include_images=False, source_bytes=None):
    payload = entry.get('payload') or {}
    path = entry.get('path') or payload.get('path')
    digest = entry.get('sha256') or payload.get('sha256')
    expected_bytes = entry.get('bytes') or payload.get('bytes')
    if not path or not re.fullmatch(r'[0-9a-f]{64}', str(digest or '')) or not isinstance(expected_bytes, int):
        raise ValueError('TMSEARCH_EXPORT_SOURCE_BINDING_MISSING')
    if source_bytes is None:
        file = resolve_retained_path(Path(task_dir), path, expected_sha256=digest, expected_bytes=expected_bytes)
        # A capacity gap is allowed only for an actually bound source. Resolve
        # streams the integrity check; do not load an oversized workbook.
        if expected_bytes > 16 * 1024 * 1024:
            raise ValueError('TMSEARCH_EXPORT_TOO_LARGE')
        source_bytes = file.read_bytes()
    # Parse the same verified bytes; reopening a path can substitute a workbook.
    if hashlib.sha256(source_bytes).hexdigest() != digest:
        raise ValueError('RETAINED_PATH_HASH_MISMATCH')
    if len(source_bytes) != expected_bytes:
        raise ValueError('RETAINED_PATH_BYTES_MISMATCH')
    if len(source_bytes) > 16 * 1024 * 1024:
        raise ValueError('TMSEARCH_EXPORT_TOO_LARGE')
    try:
        with zipfile.ZipFile(BytesIO(source_bytes)) as archive:
            info = archive.infolist()
            if len(info) > 1000 or sum(item.file_size for item in info) > MAX_UNCOMPRESSED:
                raise ValueError('TMSEARCH_EXPORT_ZIP_LIMIT')
            names = set(archive.namelist())
            if not {'xl/sharedStrings.xml', 'xl/worksheets/sheet1.xml'} <= names:
                raise ValueError('TMSEARCH_EXPORT_LAYOUT_INVALID')
            strings_xml = ET.fromstring(archive.read('xl/sharedStrings.xml'))
            strings = [''.join(part.text or '' for part in item.findall('.//' + X + 't'))
                       for item in strings_xml.findall(X + 'si')]
            worksheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            rows = {int(row.get('r')): _cells(row, strings) for row in worksheet.findall('.//' + X + 'sheetData/' + X + 'row')}
            if len(rows) > 1004 or any(rows.get(4, {}).get(_column(i)) != header for i, header in enumerate(HEADERS, 1)):
                raise ValueError('TMSEARCH_EXPORT_HEADER_INVALID')
            search_term = rows.get(2, {}).get('C', '').strip()
            first = rows.get(1, {}).get('A', '')
            count_match = re.fullmatch(r'Search results from 1 to ([0-9]+)', first)
            if not count_match or not search_term:
                raise ValueError('TMSEARCH_EXPORT_QUERY_METADATA_INVALID')
            by_row = _images(archive, names)
            data_rows = [number for number in sorted(rows) if number >= 5 and any(rows[number].values())]
            if len(data_rows) != int(count_match.group(1)) or len(data_rows) > 1000:
                raise ValueError('TMSEARCH_EXPORT_ROW_COUNT_MISMATCH')
            result, image_bytes = [], {}
            for position, number in enumerate(data_rows, 1):
                fields = {header: rows[number].get(_column(i), '').strip() for i, header in enumerate(HEADERS, 1)}
                serial = fields['SerialNumber']
                if not re.fullmatch(r'[0-9]{8}', serial):
                    raise ValueError('TMSEARCH_EXPORT_SERIAL_INVALID')
                images = []
                for member in by_row.get(number, []):
                    content = archive.read(member)
                    valid = content.startswith(b'\x89PNG\r\n\x1a\n') or content.startswith(b'\xff\xd8\xff')
                    images.append({'member': member, 'sha256': hashlib.sha256(content).hexdigest(),
                        'bytes': len(content), 'valid_image': valid})
                    if include_images and valid:
                        image_bytes[member] = content
                row_digest = hashlib.sha256(('\x1f'.join(fields.values()) + '\x1f' + ','.join(i['sha256'] for i in images)).encode()).hexdigest()
                result.append({'position': position, 'worksheet_row': number, 'fields': fields,
                    'images': images, 'source_record_sha256': row_digest})
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ET.ParseError, KeyError, OSError,
            RuntimeError, NotImplementedError, EOFError) as exc:
        raise ValueError('TMSEARCH_EXPORT_INVALID') from exc
    except ValueError as exc:
        if str(exc).startswith('TMSEARCH_EXPORT_'):
            raise
        raise ValueError('TMSEARCH_EXPORT_INVALID') from exc
    return {'search_term': search_term, 'rows': result, 'source_sha256': digest,
        'source_evidence_id': entry.get('evidence_id'), 'images': image_bytes}


def format_issue(source, error, plan=None):
    """A bound but unreadable workbook is a disclosed gap, never a zero result."""
    code = str(error)
    if not code.startswith('TMSEARCH_EXPORT_') or code == 'TMSEARCH_EXPORT_SOURCE_BINDING_MISSING':
        return None
    right = source.get('right_type')
    rights = {right} if right in {'trademark_word', 'trademark_figurative'} else set()
    if not rights:
        matching = {row.get('right_type') for rows in (plan or {}).get('queries', {}).values()
            if isinstance(rows, list) for row in rows if isinstance(row, dict)
            and row.get('query_id') == source.get('query_id') and row.get('jurisdiction') == 'US'
            and row.get('right_type') in {'trademark_word', 'trademark_figurative'}}
        rights = matching if len(matching) == 1 else {'trademark_word', 'trademark_figurative'}
    payload = source.get('payload') or {}
    return {'evidence_id': source.get('evidence_id'), 'source_sha256': source.get('sha256') or payload.get('sha256'),
        'source_bytes': source.get('bytes') or payload.get('bytes'), 'query_id': source.get('query_id'),
        'jurisdiction': 'US', 'right_type': 'trademark', 'affected_right_types': sorted(rights),
        'error_code': code}


def candidate_entries(task_dir, evidence, *, issues=None, plan=None):
    result = []
    for source in registered_sources(evidence):
        try:
            parsed = parse_export(task_dir, source)
        except ValueError as exc:
            issue = format_issue(source, exc, plan)
            if issues is None or issue is None:
                raise
            issues.append(issue)
            continue
        right = source['right_type']
        if right == 'trademark':
            right = 'trademark_word' if parsed['search_term'].startswith('CM:') else 'trademark_figurative'
        candidates = []
        for row in parsed['rows']:
            fields = row['fields']
            candidates.append({'jurisdiction': 'US', 'right_type': right,
                'right_type_basis': 'registered_source_query_scope',
                'application_number': fields['SerialNumber'],
                'serial_number': fields['SerialNumber'],
                'registration_number': fields['RegistrationNumber'],
                'mark_text': fields['Wordmark'],
                'title': fields['Wordmark'] or '图形商标 ' + fields['SerialNumber'],
                'status': fields['Status'], 'goods_services': fields['GoodsAndServicesTruncated'],
                'international_class': fields['InternationalClass'],
                'owner': fields['OwnerFullText'], 'filing_date': fields['FiledDate'],
                'registration_date': fields['RegistrationDate'],
                'source_position': row['position'],
                'source_record_sha256': row['source_record_sha256'],
                'source_image_members': row['images'],
                'official_export_source_evidence_id': source['evidence_id'],
                'official_export_query': parsed['search_term'],
                'official_status_unverified': True})
        result.append({**source, 'payload': {'candidates': candidates},
            'query': parsed['search_term'], 'source_key': 'tmsearch-export:' + parsed['source_sha256']})
    return result


def publication_issues(task_dir, evidence, candidates, *, mode=None, plan=None):
    """Reject silent disappearance and untriaged rows before either review or publication."""
    issues = []
    unreadable = []
    actual = [item for item in candidates.get('trademarks', []) if isinstance(item, dict)] if isinstance(candidates, dict) else []
    for source in registered_sources(evidence):
        try:
            parsed = parse_export(task_dir, source)
        except ValueError as exc:
            issue = format_issue(source, exc, plan)
            if issue is None:
                issues.append('OFFICIAL_EXPORT_UNREADABLE:' + str(source.get('evidence_id')) + ':' + str(exc))
            else:
                unreadable.append(issue)
            continue
        for row in parsed['rows']:
            matches = [item for item in actual if any(ref.get('evidence_id') == source.get('evidence_id')
                and ref.get('source_position') == row['position']
                and ref.get('source_record_sha256') == row['source_record_sha256']
                for ref in item.get('sources', []) if isinstance(ref, dict))]
            if len(matches) != 1:
                issues.append('OFFICIAL_EXPORT_ROW_UNACCOUNTED:' + str(source.get('evidence_id')) + ':' + str(row['position']))
            elif matches[0].get('triage_status') not in {'selected', 'not_selected', 'needs_info'}:
                issues.append('OFFICIAL_EXPORT_ROW_UNTRIAGED:' + str(source.get('evidence_id')) + ':' + str(row['position']))
    recorded = candidates.get('official_export_issues', []) if isinstance(candidates, dict) else []
    if recorded != unreadable:
        issues.append('OFFICIAL_EXPORT_LIMIT_BINDING_INVALID')
    if mode != 'evidence':
        issues.extend('OFFICIAL_EXPORT_UNREADABLE:' + str(item['evidence_id']) + ':' + item['error_code']
            for item in unreadable)
    return issues
