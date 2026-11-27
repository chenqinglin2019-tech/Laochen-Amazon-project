"""初筛之前由程序补材料（不用 AI）：并行去 Google Patents 的公开页取每件发明的状态、摘要、第一项独立权利要求，
把外观的代表图下载下来。外观的图有三个来源：Google 图库（授权一年多以上的）、美国专利局每周公报的网页（近 52 周授权的）、
美国专利局"按页取图"的接口（什么时候的都有、图最清楚，但它没有公开文档、换过地址，不能只靠它）。取到的图在本机留一份。"""
from __future__ import annotations

import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from . import config, images, numbers
from .sources import eog, euipo, gpatents, http, ppubs

WORKERS = 8
PATENT_PAGES = 60     # 最多给多少件发明取公开页（也是文字初筛看的件数）；不小于两路发明检索取回件数之和，免得查到了却没看
UTILITY_PAGES = 20    # 其中最多给实用新型留多少件
DESIGN_THUMBS = 60    # 最多给多少件外观取代表图（也是一轮看图初筛的上限）
FIGURES_KEEP = 8
CACHE_NAME = re.compile(r"US[A-Z0-9]+-(?:p\d+|og|g\d+|gt?-[A-Za-z0-9]+)\.(?:png|jpg|gif)(?:\.\d+\.tmp)?")  # 缓存里自己存的文件长这样


def design_order(candidates: list) -> list:
    """看图的先后：标题直接命中的在前，其次是按相关度查到的，最后是同分类的；同一档里新授权的在前。"""
    def rank(cand):
        via = cand.get("via") or []
        tier = 0 if "title" in via else 1 if "relevance" in via else 2
        granted = numbers.parse_date(cand.get("grant_date", ""))
        return (tier, -(granted.toordinal() if granted else 0))
    return sorted((c for c in candidates if c["right_type"] == "design"), key=rank)


def _safe(number: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", number or "") or "x"


def read_page(cand: dict, opener=None) -> None:
    """从 Google Patents 的公开页补：状态、到期日、摘要、第一项独立权利要求、附图地址。"""
    page, note = None, ""
    for attempt in (1, 2):  # 请求多了 Google 偶尔会断开：断开的再试一次
        count("Google Patents 公开页")
        try:
            page = gpatents.fetch(cand["number"], opener)
            break
        except http.SourceError as exc:
            note = exc.message
            if exc.kind != "network":
                break
    if page is None:
        cand["page_note"] = note  # 没读到：初筛时会告诉 AI 这一件只有标题
        return
    cand["page_note"] = ""
    cand["legal_status_raw"] = page["legal_status"]
    cand["legal_status"] = gpatents.status_name(page["legal_status"]) or cand.get("legal_status", "")
    cand["expiry"] = page["expiry"] or cand.get("expiry", "")
    cand["abstract"] = page["abstract"]
    cand["owner"] = cand.get("owner") or page["owner"]
    claims = page["independent_claims"]
    cand["claim1"] = claims[0]["text"][:700] if claims else ""
    cand["figures"] = (page["images"] or cand.get("figures") or [])[:FIGURES_KEEP]
    cand["page_figures"] = len(page["images"])  # 公开页自己列了几张附图（0 表示页面上没解析出图，上面沿用的是检索给的地址）


def figure_page(cand: dict, index: int) -> tuple:
    """第 index 张附图在第几页、附图最后一页是第几页（不知道的是 0）。"""
    pages = int(cand.get("pages") or 0)
    start, end = int(cand.get("figures_from") or 0), int(cand.get("figures_to") or 0)
    if not (1 <= start and (not pages or start <= pages)):
        start, end = 2, 0  # 专利局没给：第 1 页是扉页，从第 2 页起
        if pages == 1:
            start = 1      # 只有一页的：就取这一页
    last = end if end >= start else pages
    return start + index - 1, (min(last, pages) if pages and last else last)


def figure_file(cand: dict, folder: Path, index: int) -> Path:
    """文件名里带页码：换了取图的页，不会拿到以前存下的另一页。"""
    return folder / ("%s-p%d.png" % (_safe(cand["number"]), figure_page(cand, index)[0]))


def from_cache(dest: Path) -> bool:
    """本机缓存里有这张图就拷过来。"""
    source = config.cache_dir() / dest.name
    try:
        if images.readable(source):
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(source), str(dest))
            return images.readable(dest)
    except OSError:
        pass
    return False


def to_cache(dest: Path) -> None:
    """把刚取到的图在本机留一份；留不成不影响这一单。"""
    try:
        folder = config.cache_dir()
        folder.mkdir(parents=True, exist_ok=True)
        partial = folder / ("%s.%d.tmp" % (dest.name, os.getpid()))  # 先写临时文件再改名：别的进程不会读到写了一半的图
        shutil.copyfile(str(dest), str(partial))
        os.replace(str(partial), str(folder / dest.name))
    except OSError:
        pass


def prune_cache(now: float = None) -> None:
    """清掉缓存里太久没用的图。"""
    limit = (now or time.time()) - config.CACHE_DAYS * 86400
    try:
        for path in config.cache_dir().glob("US*"):  # 只删自己存的图（文件名以专利号开头），目录指错了也不误删别的
            if path.is_file() and CACHE_NAME.fullmatch(path.name) and path.stat().st_mtime < limit:
                path.unlink()
    except OSError:
        pass


def google_ready(cand: dict) -> bool:
    """这件的附图 Google 的图库里能不能直接下。实测：地址里带一串两位一段的目录（/77/6c/f3/…）的能下；
    近一年多授权的外观地址是 /USD1150873S1/… 这种，下不了。"""
    urls = cand.get("figures") or []
    return bool(urls) and re.search(r"/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{2}/", str(urls[0])) is not None


def google_figure(cand: dict, folder: Path, index: int, opener=None):
    """从 Google 的图库下第 index 张附图（不占美国专利局的取图额度）。返回本地路径，没有返回 None。"""
    urls = cand.get("figures") or []
    if not google_ready(cand) or index > len(urls):
        return None
    url = str(urls[index - 1])
    # 文件名用网址里的那一段（哪张图就是哪张图）：检索给的地址和公开页给的地址排法不一样，按"第几张"存会错位
    name = re.sub(r"[^A-Za-z0-9]", "", url.split("?")[0].rsplit("/", 1)[-1].rsplit(".", 1)[0])[-40:] or str(index)
    # 缩略图和原图的文件名一样、只是目录不同：分开存（-gt-），免得深查时拿到小图；数张数时两者算同一张（见 figure_set）
    kind = "gt" if "/thumbnails/" in url else "g"
    dest = folder / ("%s-%s-%s%s" % (_safe(cand["number"]), kind, name, ".png" if ".png" in url.lower() else ".jpg"))
    if images.readable(dest) or from_cache(dest):
        return dest
    count("Google 图库附图")
    if http.download(url, dest, opener=opener) and images.readable(dest):
        to_cache(dest)
        return dest
    return None


def gazette_figure(cand: dict, folder: Path, today: date = None, opener=None):
    """近 52 周授权的外观：从专利局每周公报的网页取代表图（静态文件，不占"按页取图"那个接口的额度）。只有一张、比较小，够初筛用。"""
    url = eog.image_url(cand.get("number", ""), cand.get("grant_date", ""), today)
    if not url:
        return None
    dest = folder / ("%s-og.gif" % _safe(cand["number"]))
    if images.readable(dest) or from_cache(dest):
        return dest
    count("美国专利局公报图")
    if http.download(url, dest, opener=opener) and images.readable(dest):
        to_cache(dest)
        return dest
    return None


def official_figure(cand: dict, session, folder: Path, index: int = 1) -> bool:
    """向美国专利局取第 index 张附图页。附图从第几页开始以专利局给的为准（引用文献多的外观，第 2 页还是文字）；
    专利局没给时按"第 1 页是扉页、第 2 页起是附图"算。"""
    page, last = figure_page(cand, index)
    if not page or (last and page > last) or not cand.get("image_location"):  # 页数不知道（0）时照样去取
        return False
    dest = figure_file(cand, folder, index)
    if images.readable(dest) or from_cache(dest):
        ok = True
    else:
        if not session.failed and not ppubs.image_blocked():  # 会话开不成、或者已经认定它不给图的，下面不会真的发请求，不记
            count("美国专利局附图")
        certain = index == 1 or bool(last)  # 第一张附图页、或者在专利局写明的页数范围内：这一页确定存在
        ok = session.page_image(cand["image_location"], page, dest, certain) and images.readable(dest)
        if ok:
            to_cache(dest)
    if ok:
        if index == 1:
            cand["thumb"] = "rights/" + dest.name
            cand["thumb_from"] = "美国专利局"
        return True
    return False


def euipo_figure(cand: dict, folder: Path, order: int, opener=None):
    """欧盟外观的第 order 个视图（欧盟知识产权局官方接口）。返回本地路径，没有返回 None。"""
    dest = folder / ("%s-v%d.jpg" % (_safe(cand["number"]), order))
    if images.readable(dest):
        return dest
    count("欧盟知识产权局附图")
    if euipo.view(cand["euipo"], order, dest, opener) and images.readable(dest):
        return dest
    return None


def use_thumb(cand: dict, path: Path, source: str = "Google Patents") -> None:
    cand["thumb"] = "rights/" + path.name
    cand["thumb_from"] = source


def enrich_one(cand: dict, task_dir: Path, want_image: bool, session, today: date, opener=None) -> None:
    """给一件候选补材料。任何一步失败都只是少一样材料，不抛错。"""
    folder = Path(task_dir) / "rights"
    if not want_image:
        read_page(cand, opener)
        return
    if cand.get("euipo"):  # 欧盟外观：品名和视图张数在详情里，图按视图取
        count("欧盟知识产权局详情")
        try:
            info = euipo.detail(cand["euipo"], opener)
            cand["title"] = info["title"] or cand.get("title", "")
            cand["euipo_views"] = info["views"]
        except http.SourceError:
            pass
        path = euipo_figure(cand, folder, 1, opener)
        if path:
            use_thumb(cand, path, "欧盟知识产权局")
        return
    # 外观的代表图，按这个先后找：
    # Google 图库（授权一年多以上的，图清楚，也不依赖专利局那个没有文档的接口）→ 专利局按页取图（什么时候的都有，图清楚）
    # → 专利局每周公报的网页（近 52 周授权的，只有一张小图：按页取图取不到时顶上）→ 读一次 Google 公开页再试图库。
    path = google_figure(cand, folder, 1, opener)
    if path:
        use_thumb(cand, path)
        return
    if official_figure(cand, session, folder):
        return
    path = gazette_figure(cand, folder, today, opener)
    if path:
        use_thumb(cand, path, "美国专利局公报")
        return
    if not cand.get("figures"):  # 手里没有图的地址（只有专利局检索到的）：读一次公开页，老一点的外观 Google 图库里有
        read_page(cand, opener)
        path = google_figure(cand, folder, 1, opener)
        if path:
            use_thumb(cand, path)


def figure_set(cand: dict, task_dir: Path, limit: int, session, opener=None, official_limit: int = None) -> list:
    """这件外观的前几张附图，返回本地路径。先用 Google 图库里的，不够两张再向美国专利局取；两边各取到几张，用多的那边（不混着用）。"""
    folder = Path(task_dir) / "rights"
    if cand.get("euipo"):
        wanted = min(limit, int(cand.get("euipo_views") or 0) or limit)
        with ThreadPoolExecutor(max_workers=wanted) as pool:
            return [path for path in pool.map(lambda order: euipo_figure(cand, folder, order, opener), range(1, wanted + 1)) if path]
    if google_ready(cand) and len(cand.get("figures") or []) < 2:
        read_page(cand, opener)  # 检索结果只给了一张图的地址：读公开页拿全部附图的地址
    wanted = min(limit, len(cand.get("figures") or [])) if google_ready(cand) else 0
    by_picture = {}  # 同一张图只算一张：两个地址相同的、同一张图的原图和缩略图，都是一张；有原图就用原图
    for index in range(1, wanted + 1):
        path = google_figure(cand, folder, index, opener)
        if path is None:
            continue
        picture = path.stem.split("-gt-")[-1].split("-g-")[-1]
        if picture not in by_picture or ("-gt-" in by_picture[picture].name and "-g-" in path.name):
            by_picture[picture] = path
    found = list(by_picture.values())
    if len(found) >= 2 or not cand.get("image_location"):
        return found
    if ppubs.image_blocked():
        return found  # 已经认定它这会儿不给图：不白跑一趟
    official_limit = official_limit or limit
    with ThreadPoolExecutor(max_workers=official_limit) as pool:
        done = list(pool.map(lambda index: official_figure(cand, session, folder, index), range(1, official_limit + 1)))
    official = [figure_file(cand, folder, index) for index, ok in zip(range(1, official_limit + 1), done) if ok]
    official = [path for path in official if images.readable(path)]
    return official if len(official) >= len(found) else found


_session_lock = threading.Lock()
_count_lock = threading.Lock()
_counts = {}


def count(source: str) -> None:
    """记一次实际发出的请求（几个线程同时记）。"""
    with _count_lock:
        _counts[source] = _counts.get(source, 0) + 1


def session_ready(session):
    """几个线程共用一个会话：谁先到谁去开，其余等它开好。"""
    with _session_lock:
        if not session.token:
            try:
                session.open()
            except http.SourceError:
                pass
    return session


def run(task, say=print, opener=None, today: date = None, usage=None) -> None:
    """只给还没有决定的候选补材料；补过的打上 enriched 标记，初筛就看这一批。"""
    today = today or date.today()
    open_items = [c for c in task["candidates"] if not (c.get("screen") or {}).get("decision")]
    utility = [c for c in open_items if c["right_type"] == "utility_model"][:UTILITY_PAGES]  # 实用新型排在发明后面：先给它留名额，免得一件都轮不到
    patents = [c for c in open_items if c["right_type"] == "patent"][:PATENT_PAGES - len(utility)] + utility
    designs = design_order([c for c in open_items if not c.get("no_figures")])[:DESIGN_THUMBS]  # 来源不给图的外观不用去取
    jobs = [(c, False) for c in patents] + [(c, True) for c in designs]
    if not jobs:
        return
    with _count_lock:
        _counts.clear()
    prune_cache()
    session = ppubs.Session(opener)  # 用到的时候才去开；官方附图取不了时，各件只是少一张图
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(lambda job: enrich_one(job[0], task.dir, job[1], session, today, opener), jobs))
    for cand, _want in jobs:
        cand["enriched"] = True
    missed = [c for c in patents if c.get("page_note")]
    if missed:
        task.add_incomplete("%d 件发明专利的公开页" % len(missed), "没有读到（%s），初筛时只看了标题" % missed[0]["page_note"][:60], "patent")
    flush(usage)
    say("  补材料：发明 %d 件里 %d 件读到了公开页，外观 %d 件里 %d 件取到了代表图" % (
        len(patents), len(patents) - len(missed), len(designs), sum(1 for c in designs if c.get("thumb"))))
    if ppubs.image_blocked():
        say("  美国专利局的取图接口这会儿不给图（是它那边的原因：可能临时不让取，也可能又调整了接口）；没取到图的那几件先记着，过一阵再运行同一条命令会补上")


def flush(usage) -> None:
    """把这一轮记下的请求数交给用量表，然后清零。"""
    with _count_lock:
        done = dict(_counts)
        _counts.clear()
    for source, times in done.items():
        if times and usage is not None:
            usage.add_source_call(source, times)


def more_figures(cand: dict, task_dir: Path, limit: int = 4, opener=None, usage=None) -> list:
    """第二次看图用：把这件外观的前几张附图都取来，返回本地路径。"""
    found = figure_set(cand, task_dir, limit, ppubs.Session(opener), opener)
    flush(usage)
    return found
