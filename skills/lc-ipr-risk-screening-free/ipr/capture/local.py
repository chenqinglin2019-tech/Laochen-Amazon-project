"""资料入口（R-014）：没有链接时，用自己提供的图片和文字开跑。

资料文件夹里放：至少一张产品图（jpg / png / webp）；文字可以写在文件夹里的 .txt 或 .md 文件里（第一行当品名，其余当描述），
也可以用命令行的 --title 直接给一句。可选的 product.json 可以写 title、brand、category、bullets、description。
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .. import config, images
from ..outcome import NoProduct

TEXT_SUFFIXES = (".txt", ".md")
TITLE_MAX = 300


def read_text(path: Path) -> str:
    """文字文件可能是 UTF-8（带不带 BOM）、UTF-16 或中文 Windows 的 GBK，逐个试；都不行就返回空字符串。"""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        codecs = ("utf-16",)
    else:
        codecs = ("utf-8-sig", "gb18030")
    decoded = {}
    for codec in codecs:
        try:
            decoded[codec] = raw.decode(codec)
        except UnicodeDecodeError:
            continue
    text = decoded.get("utf-8-sig", decoded.get("utf-16", decoded.get("gb18030", "")))
    if "utf-8-sig" in decoded and "gb18030" in decoded and not raw.startswith(b"\xef\xbb\xbf"):
        # UTF-8 优先（德、法、意、西语的重音字母、®、° 都是正常的 UTF-8）。
        # 只有一种情况改按 GBK：个别很短的纯中文 GBK 文本碰巧也是合法的 UTF-8，读出来整段都是
        # 冷僻的拉丁扩展、希腊字母（U+0180–U+03FF），连一个英文字母和数字都没有。
        foreign = [ch for ch in text if ord(ch) > 0x7f]
        if foreign and all("\u0180" <= ch <= "\u03ff" for ch in foreign) and not re.search(r"[A-Za-z0-9]", text):
            text = decoded["gb18030"]  # 整段没有一个英文字母和数字（"5μm"这种正常写法不会走到这里）
    return text


def inspect(folder: Path, title: str = "") -> dict:
    """看一遍资料文件夹，返回 {"images": [...], "bad_images": [...], "text": {...}, "problems": [给用户看的话]}。不改任何文件。"""
    folder = Path(folder)
    problems = []
    if not folder.is_dir():
        message = "资料文件夹 %s 不存在" % folder
        return {"images": [], "bad_images": [], "text": {}, "problems": [message], "blocking": [message]}
    files = sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))
    pictures = [p for p in files if p.suffix.lower() in images.SUFFIXES]
    good = [p for p in pictures if images.readable(p)]
    bad = [p for p in pictures if p not in good]
    text = {"title": (title or "").strip(), "description": "", "brand": "", "category": "", "bullets": []}
    meta = folder / "product.json"
    if meta.is_file():
        try:
            data = json.loads(read_text(meta) or "不是 JSON")
        except ValueError:
            problems.append("product.json 读不了，请检查格式和编码")
            data = {}
        if isinstance(data, dict):
            text["title"] = text["title"] or str(data.get("title") or "").strip()
            text["description"] = str(data.get("description") or "").strip()
            text["brand"] = str(data.get("brand") or "").strip()
            text["category"] = str(data.get("category") or "").strip()
            text["bullets"] = [str(b).strip() for b in data.get("bullets") or [] if str(b).strip()] if isinstance(data.get("bullets"), list) else []
    for note in (p for p in files if p.suffix.lower() in TEXT_SUFFIXES):
        content = read_text(note)
        if not content.strip():
            try:
                empty = not note.read_bytes().strip()
            except OSError:
                empty = False
            if not empty:
                problems.append("文字文件 %s 读不出来，请另存为 UTF-8 编码" % note.name)
            continue
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not text["title"]:  # 第一行当品名，太长就截断，截掉的部分并进描述
            text["title"], overflow = lines[0][:TITLE_MAX], lines[0][TITLE_MAX:]
            lines = ([overflow] if overflow else []) + lines[1:]
        text["description"] = (text["description"] + " " + " ".join(lines)).strip()[:3000]
    if not text["title"] and text["description"]:  # 只给了描述：取第一句当品名
        # 句点只在"前面至少三个小写字母或数字、后面是空白加大写字母或汉字"时才当句子结束，免得把 2.5、U.S.、No. 5 切开
        first = re.split(r"[。！？!?\n]|(?<=[a-zà-ÿ0-9\u4e00-\u9fff]{3})\.\s+(?=[A-ZÀ-Þ\u4e00-\u9fff])",
                         text["description"].lstrip(" .。！？!?…"), 1)[0].strip()
        text["title"] = (first if len(first) >= 2 else text["description"].strip())[:TITLE_MAX]
    blocking = []
    for picture in bad:
        problems.append("图片 %s 打不开或格式不支持" % picture.name)
    if not good:
        blocking.append("缺产品图：文件夹里至少要有一张能打开的图片（jpg、png、webp）"
                        + ("；现有的 %s 打不开" % "、".join(p.name for p in bad) if bad else ""))
    if not text["title"]:
        blocking.append("缺品名或描述：在文件夹里放一个 .txt 写一句，或者用 --title 给一句")
    return {"images": good, "bad_images": bad, "text": text, "problems": problems + blocking, "blocking": blocking}


def capture(folder: Path, task_dir: Path, title: str = "") -> dict:
    """把资料整理成和链接采集一样的格式，图片拷进任务目录。"""
    found = inspect(folder, title)
    if found["blocking"]:
        raise NoProduct("没拿到商品资料：%s。" % "；".join(found["blocking"]))
    saved = []
    image_dir = Path(task_dir) / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    for index, source in enumerate(found["images"][:config.PRODUCT_IMAGES_MAX]):
        target = image_dir / ("IMG-%03d%s" % (index + 1, source.suffix.lower()))
        shutil.copyfile(source, target)
        saved.append({"file": str(target), "url": ""})
    text = found["text"]
    product = {"title": text["title"], "brand": text["brand"], "category": text["category"], "bullets": text["bullets"],
               "description": text["description"], "asin": "", "url": "", "marking": []}
    notes = [p for p in found["problems"] if p not in found["blocking"]]
    return {"product": product, "images": saved, "space_id": None, "failed_images": [], "notes": notes}
