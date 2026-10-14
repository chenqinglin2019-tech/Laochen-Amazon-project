"""Lossless local merging of compatible native SellerSprite XLSX exports.

Copy OOXML cells and image bytes directly. Unsupported structures fail closed,
leaving the prior output and every source intact; never fall back to flat JSON.
"""
from __future__ import annotations

import copy
import posixpath
import re
import tempfile
import zipfile
from pathlib import Path

from lxml import etree as E

from run_outcome import retry_later, replace_with_retry

M = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P = 'http://schemas.openxmlformats.org/package/2006/relationships'
D = 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'
NS = {'m': M, 'r': R, 'p': P, 'd': D}
PARSER = E.XMLParser(resolve_entities=False, no_network=True)


def parse(data):
    return E.fromstring(data, parser=PARSER)


def signature(e):
    if e is None:
        return None
    return (e.tag, tuple(sorted(e.attrib.items())), e.text or '', tuple(signature(x) for x in e))


def encode(e):
    return E.tostring(e, xml_declaration=True, encoding='UTF-8', standalone=True)


def resolve(owner, name):
    return posixpath.normpath(posixpath.join(posixpath.dirname(owner), name)).lstrip('/')


def relpath(owner):
    return posixpath.join(posixpath.dirname(owner), '_rels', posixpath.basename(owner) + '.rels')


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def sheets(parts):
    rels = {r.get('Id'): resolve('xl/workbook.xml', r.get('Target'))
            for r in parse(parts['xl/_rels/workbook.xml.rels'])}
    return {s.get('name'): rels[s.get(f'{{{R}}}id')]
            for s in parse(parts['xl/workbook.xml']).find(f'{{{M}}}sheets')}


def strings(parts):
    return parse(parts.get('xl/sharedStrings.xml', f'<sst xmlns="{M}"/>'.encode()))


def cell_text(c, sst):
    if c.get('t') == 's':
        return ''.join(sst[int(c.findtext(f'{{{M}}}v'))].itertext())
    if c.get('t') == 'inlineStr':
        return ''.join(c.find(f'{{{M}}}is').itertext())
    return c.findtext(f'{{{M}}}v')


def move_ref(ref, rowmap):
    def replace(match):
        old = int(match[2])
        require(old in rowmap, f'引用了未保留的行 {ref}')
        return match[1] + str(rowmap[old])
    return re.sub(r'(\$?[A-Z]+\$?)(\d+)', replace, ref)


def remap_row(row, rowmap, smap, stylemap):
    row = copy.deepcopy(row)
    if rowmap is not None:
        row.set('r', str(rowmap[int(row.get('r'))]))
    if 's' in row.attrib:
        row.set('s', str(stylemap[int(row.get('s'))]))
    for c in row.findall(f'{{{M}}}c'):
        if rowmap is not None:
            c.set('r', move_ref(c.get('r'), rowmap))
        if 's' in c.attrib:
            c.set('s', str(stylemap[int(c.get('s'))]))
        if c.get('t') == 's':
            value = c.find(f'{{{M}}}v')
            value.text = str(smap[int(value.text)])
    return row


def merge_styles(styles, incoming):
    """IDs are workbook-local: merge resources by content before mapping XFs."""
    maps = {}
    for component in ('fonts', 'fills', 'borders', 'numFmts', 'cellStyleXfs', 'cellXfs'):
        source = incoming.find(f'{{{M}}}{component}')
        dest = styles.find(f'{{{M}}}{component}')
        if source is None:
            maps[component] = {}
            continue
        if dest is None:
            dest = E.Element(source.tag, **source.attrib)
            styles.insert(list(incoming).index(source), dest)
        if component == 'numFmts':
            by_code = {x.get('formatCode'): int(x.get('numFmtId')) for x in dest}
            mapping = {}
            for item in source:
                code, old = item.get('formatCode'), int(item.get('numFmtId'))
                if code not in by_code:
                    new = max([163]+[int(x.get('numFmtId')) for x in dest])+1
                    moved = copy.deepcopy(item); moved.set('numFmtId', str(new)); dest.append(moved)
                    by_code[code] = new
                mapping[old] = by_code[code]
        else:
            index = {signature(v): i for i, v in enumerate(dest)}
            mapping = {}
            for i, item in enumerate(source):
                item = copy.deepcopy(item)
                if component in ('cellStyleXfs', 'cellXfs'):
                    for attr, resource in (('fontId', 'fonts'), ('fillId', 'fills'), ('borderId', 'borders'),
                                           ('numFmtId', 'numFmts'), ('xfId', 'cellStyleXfs')):
                        if attr in item.attrib and resource in maps:
                            old = int(item.get(attr)); item.set(attr, str(maps[resource].get(old, old)))
                key = signature(item)
                if key not in index:
                    index[key] = len(dest); dest.append(item)
                mapping[i] = index[key]
        dest.set('count', str(len(dest)))
        maps[component] = mapping
    for e in incoming:
        if E.QName(e).localname not in maps:
            require(signature(e) == signature(styles.find(e.tag)), f'不兼容的样式资源 {E.QName(e).localname}')
    return maps['cellXfs']


def static_drawing_signature(parts, owner):
    """Compare unchanged auxiliary drawings, ignoring only object identity IDs."""
    relationships = parts.get(relpath(owner))
    if not relationships:
        return ()
    result = []
    for rel in parse(relationships):
        if rel.get('TargetMode') == 'External':
            result.append((rel.get('Type'), rel.get('Target')))
            continue
        part = resolve(owner, rel.get('Target'))
        raw = parts[part]
        if part.endswith('.xml'):
            tree = parse(raw)
            for e in tree.iter():
                if E.QName(e).localname in ('cNvPr', 'creationId'):
                    for key in ('id', 'name'):
                        e.attrib.pop(key, None)
            result.append((rel.get('Type'), signature(tree), static_drawing_signature(parts, part)))
        else:
            result.append((rel.get('Type'), raw))
    return tuple(result)


def validate_defined_names(parts):
    for name in parse(parts['xl/workbook.xml']).findall('m:definedNames/m:definedName', NS):
        require(name.get('name') == '_xlnm._FilterDatabase' and name.get('localSheetId') is not None,
                '工作簿包含需要专用引用迁移的命名区域')


def merge_native_exports(output: Path, exports: list[dict]) -> dict:
    """Rows are exact Excel row numbers, already truncated/deduplicated/filtered."""
    try:
        return _merge(Path(output), exports)
    except (ValueError, KeyError, IndexError, TypeError, OSError, zipfile.BadZipFile, E.XMLSyntaxError) as exc:
        raise retry_later(f'原生格式合并失败：{exc}。原始文件和已有成品保留，不生成丢字段或丢格式的替代表。',
                          next_action='检查原始下载表的列、布局或新增对象；修复合并兼容性后本地重新合并，无需重采。') from exc


def _merge(output, exports):
    require(bool(exports), '没有已提交的原生文件')
    with zipfile.ZipFile(exports[0]['path']) as z:
        parts = {n: z.read(n) for n in z.namelist() if not n.endswith('/')}
    names = sheets(parts)
    validate_defined_names(parts)
    main = exports[0].get('sheet')
    if not main:
        ss = strings(parts)
        candidates = [name for name, part in names.items()
                      if any(cell_text(c, ss) == 'ASIN' for c in parse(parts[part]).findall('m:sheetData/m:row/m:c', NS)[:100])]
        require(len(candidates) == 1, '无法唯一识别商品工作表')
        main = candidates[0]
    require(main in names, '缺少商品工作表')
    merged_names = [main] + [n for n in names if n.casefold() in ('brands', 'sellers')]
    dest = {n: parse(parts[names[n]]) for n in merged_names}
    offsets = {n: 0 for n in merged_names}
    headers = {n: copy.deepcopy(ws.find('m:sheetData/m:row', NS)) for n, ws in dest.items()}
    for n, ws in dest.items():
        require(headers[n] is not None and headers[n].get('r') == '1', '原生表头必须位于第1行')
        allowed = {'dimension', 'sheetViews', 'sheetFormatPr', 'cols', 'sheetData', 'hyperlinks',
                   'pageMargins', 'pageSetup', 'drawing', 'autoFilter', 'printOptions', 'sheetPr'}
        require(all(E.QName(e).localname in allowed for e in ws), f'{n} 含尚未支持无损移动的对象')
        data = ws.find(f'{{{M}}}sheetData')
        for row in list(data)[1:]:
            data.remove(row)
        for old in ws.findall(f'{{{M}}}hyperlinks'):
            ws.remove(old)
    sst = strings(parts)
    si_index = {signature(v): i for i, v in enumerate(sst)}
    styles = parse(parts['xl/styles.xml'])
    xfs = styles.find(f'{{{M}}}cellXfs')
    links = {n: E.Element(f'{{{M}}}hyperlinks') for n in merged_names}
    rels = {n: E.Element(f'{{{P}}}Relationships', nsmap={None: P}) for n in merged_names}
    drawings, drawrels, drawing_parts = {}, {}, {}
    for n, ws in dest.items():
        node = ws.find(f'{{{M}}}drawing')
        if node is not None:
            oldrels = {r.get('Id'): r for r in parse(parts[relpath(names[n])])}
            part = resolve(names[n], oldrels[node.get(f'{{{R}}}id')].get('Target'))
            drawing_parts[n] = part
            drawings[n] = parse(parts[part])
            for anchor in list(drawings[n]):
                drawings[n].remove(anchor)
            drawrels[n] = E.Element(f'{{{P}}}Relationships', nsmap={None: P})
            node.set(f'{{{R}}}id', 'rId1')
            E.SubElement(rels[n], f'{{{P}}}Relationship', Id='rId1', Type=R+'/drawing',
                         Target=posixpath.relpath(part, posixpath.dirname(names[n])))
    content = parse(parts['[Content_Types].xml'])
    defaults = {e.get('Extension') for e in content if E.QName(e).localname == 'Default'}
    image_count, cells = 0, 0
    for source_index, export in enumerate(exports):
        with zipfile.ZipFile(export['path']) as z:
            src = {n: z.read(n) for n in z.namelist() if not n.endswith('/')}
        source_names = sheets(src)
        require(source_names == names and list(source_names) == list(names),
                '工作表名称、顺序或结构不同，不能静默丢弃工作表')
        require(not export.get('sheet') or export['sheet'] == main, '商品表名称不一致')
        require(src.get('xl/theme/theme1.xml') == parts.get('xl/theme/theme1.xml'), '颜色/字体主题不同')
        validate_defined_names(src)
        smap = {}
        for i, v in enumerate(strings(src)):
            key = signature(v)
            if key not in si_index:
                si_index[key] = len(sst)
                sst.append(copy.deepcopy(v))
            smap[i] = si_index[key]
        stylemap = merge_styles(styles, parse(src['xl/styles.xml']))
        require(stylemap.get(0) == 0, '工作簿默认样式不同')
        for n in names:
            ws = parse(src[names[n]])
            if n not in dest:
                # Notes/instructions stay once, but must not discard different content.
                for row in ws.findall('m:sheetData/m:row', NS):
                    row.getparent().replace(row, remap_row(row, None, smap, stylemap))
                for col in ws.findall('m:cols/m:col', NS):
                    if col.get('style') is not None:
                        col.set('style', str(stylemap[int(col.get('style'))]))
                require(signature(ws) == signature(parse(parts[names[n]])), f'{n} 附表内容不同')
                require(static_drawing_signature(src, names[n]) == static_drawing_signature(parts, names[n]),
                        f'{n} 附表图片或对象不同')
                continue
            require(all(E.QName(e).localname in allowed for e in ws), f'{n} 含尚未支持无损移动的对象')
            for col in ws.findall('m:cols/m:col', NS):
                if col.get('style') is not None:
                    col.set('style', str(stylemap[int(col.get('style'))]))
            for feature in ('cols', 'sheetFormatPr', 'sheetViews', 'pageMargins', 'pageSetup', 'printOptions', 'sheetPr'):
                require(signature(ws.find(f'{{{M}}}{feature}')) == signature(dest[n].find(f'{{{M}}}{feature}')),
                        f'{n} 的 {feature} 布局不同')
            data = ws.find(f'{{{M}}}sheetData')
            require(signature(remap_row(data[0], None, smap, stylemap)) == signature(headers[n]),
                    f'{n} 列名、顺序或表头格式不一致')
            selected = export['rows'] if n == main else [int(row.get('r')) for row in list(data)[1:]]
            require(len(selected) == len(set(selected)) and all(i > 1 for i in selected), '商品行号重复或包含表头')
            rowmap = {1: 1, **{old: offsets[n]+i+2 for i, old in enumerate(selected)}}
            source_rows = {int(row.get('r')): row for row in data}
            for old in selected:
                require(old in source_rows, f'原始行 {old} 不存在')
                row = source_rows[old]
                require(not row.findall('.//m:f', NS), '含公式的商品/统计行需要专用引用迁移，已停止以保留公式')
                moved = remap_row(row, rowmap, smap, stylemap)
                dest[n].find(f'{{{M}}}sheetData').append(moved)
                cells += len(moved)
            source_rels = {r.get('Id'): r for r in parse(src[relpath(names[n])])} if relpath(names[n]) in src else {}
            require(all(r.get('Type') in (R+'/drawing', R+'/hyperlink') for r in source_rels.values()),
                    f'{n} 含尚未支持迁移的外部对象关系')
            for link in ws.findall('m:hyperlinks/m:hyperlink', NS):
                rownum = int(re.search(r'\d+', link.get('ref'))[0])
                if rownum not in rowmap or (rownum == 1 and source_index):
                    continue
                link = copy.deepcopy(link)
                link.set('ref', move_ref(link.get('ref'), rowmap))
                rid = link.get(f'{{{R}}}id')
                if rid:
                    rel = copy.deepcopy(source_rels[rid])
                    require(rel.get('TargetMode') == 'External', '不支持的内部超链接关系')
                    newrid = f'rId{len(rels[n])+1}'
                    rel.set('Id', newrid)
                    link.set(f'{{{R}}}id', newrid)
                    rels[n].append(rel)
                links[n].append(link)
            node = ws.find(f'{{{M}}}drawing')
            require((node is not None) == (n in drawings), f'{n} 绘图布局不一致')
            if node is not None:
                part = resolve(names[n], source_rels[node.get(f'{{{R}}}id')].get('Target'))
                img_rels = {r.get('Id'): r for r in parse(src[relpath(part)])}
                imported = {}
                for anchor in parse(src[part]):
                    require(E.QName(anchor).localname in ('twoCellAnchor', 'oneCellAnchor'), '不支持绝对位置绘图')
                    start = int(anchor.findtext('d:from/d:row', namespaces=NS)) + 1
                    if start not in rowmap or (start == 1 and source_index):
                        continue
                    anchor = copy.deepcopy(anchor)
                    for marker in anchor.findall('d:from/d:row', NS) + anchor.findall('d:to/d:row', NS):
                        old = int(marker.text)+1
                        # A two-cell image may end exactly at the next row boundary.
                        require(old in rowmap or old == start+1, '图片跨越了被删除的商品行')
                        marker.text = str((rowmap.get(old, rowmap[start]+1))-1)
                    for e in anchor.iter():
                        require(f'{{{R}}}id' not in e.attrib, '图片包含额外对象关系，需专用迁移')
                        for attr in (f'{{{R}}}embed', f'{{{R}}}link'):
                            if attr not in e.attrib:
                                continue
                            rid = e.get(attr)
                            if rid not in imported:
                                rel = img_rels[rid]
                                require(rel.get('Type') == R+'/image' and rel.get('TargetMode') != 'External', '绘图包含非内嵌图片对象')
                                original = resolve(part, rel.get('Target'))
                                media = f'xl/media/merged_{source_index:04d}_{list(names).index(n):02d}_{len(imported):05d}_{posixpath.basename(original)}'
                                parts[media] = src[original]
                                newrid = f'rId{len(drawrels[n])+1}'
                                imported[rid] = newrid
                                E.SubElement(drawrels[n], f'{{{P}}}Relationship', Id=newrid, Type=R+'/image',
                                             Target=posixpath.relpath(media, posixpath.dirname(drawing_parts[n])))
                            e.set(attr, imported[rid])
                        if E.QName(e).localname == 'cNvPr':
                            e.set('id', str(len(drawings[n])+1))
                            e.set('name', f'Picture {len(drawings[n])+1}')
                    drawings[n].append(anchor)
                    image_count += 1
            offsets[n] += len(selected)
        for e in parse(src['[Content_Types].xml']):
            if E.QName(e).localname == 'Default' and e.get('Extension') not in defaults:
                content.append(copy.deepcopy(e))
                defaults.add(e.get('Extension'))
    for n, ws in dest.items():
        dimension = ws.find(f'{{{M}}}dimension')
        original = parse(parts[names[n]])
        lastcol = re.search(r'([A-Z]+)\d+$', original.find(f'{{{M}}}dimension').get('ref'))[1]
        dimension.set('ref', f'A1:{lastcol}{offsets[n]+1}')
        auto = ws.find(f'{{{M}}}autoFilter')
        if auto is not None:
            auto.set('ref', dimension.get('ref'))
        if len(links[n]):
            index = next((i for i, e in enumerate(ws) if E.QName(e).localname in ('pageMargins', 'pageSetup', 'drawing')), len(ws))
            ws.insert(index, links[n])
        parts[names[n]] = encode(ws)
        if len(rels[n]):
            parts[relpath(names[n])] = encode(rels[n])
        else:
            parts.pop(relpath(names[n]), None)
        if n in drawings:
            parts[drawing_parts[n]] = encode(drawings[n])
            parts[relpath(drawing_parts[n])] = encode(drawrels[n])
    xfs.set('count', str(len(xfs)))
    parts['xl/styles.xml'] = encode(styles)
    if len(sst):
        sst.set('uniqueCount', str(len(sst)))
        sst.set('count', str(sum(len(parse(parts[p]).xpath('.//m:c[@t="s"]', namespaces=NS)) for p in names.values())))
        parts['xl/sharedStrings.xml'] = encode(sst)
    parts['[Content_Types].xml'] = encode(content)
    workbook_xml = parse(parts['xl/workbook.xml'])
    for name in workbook_xml.findall('m:definedNames/m:definedName', NS):
        sheet = list(names)[int(name.get('localSheetId'))]
        if sheet in dest:
            ref = dest[sheet].find(f'{{{M}}}autoFilter')
            require(ref is not None, '筛选命名区域缺少对应筛选器')
            absolute = re.sub(r'([A-Z]+)(\d+)', r'$\1$\2', ref.get('ref'))
            name.text = "'" + sheet.replace("'", "''") + "'!" + absolute
    parts['xl/workbook.xml'] = encode(workbook_xml)
    for name, raw in parts.items():
        if name.endswith('.rels'):
            owner = '' if name == '_rels/.rels' else name.replace('/_rels/', '/').removesuffix('.rels')
            for rel in parse(raw):
                if rel.get('TargetMode') != 'External':
                    require(resolve(owner, rel.get('Target')) in parts, f'关系目标缺失 {name}')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix='.xlsx', delete=False) as f:
        temporary = Path(f.name)
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as z:
            for name, raw in parts.items():
                z.writestr(name, raw)
        with zipfile.ZipFile(temporary) as z:
            require(z.testzip() is None, '输出压缩包校验失败')
        replace_with_retry(str(temporary), output)
    finally:
        temporary.unlink(missing_ok=True)
    return {'format_preserved': True, 'workbook': str(output), 'product_sheet': main,
            'product_rows': offsets[main], 'original_columns': last_column_count(dest[main]),
            'images': image_count, 'copied_cells': cells, 'source_files': len(exports)}


def last_column_count(ws):
    letters = re.search(r'([A-Z]+)\d+$', ws.find(f'{{{M}}}dimension').get('ref'))[1]
    result = 0
    for ch in letters:
        result = result*26 + ord(ch)-64
    return result
