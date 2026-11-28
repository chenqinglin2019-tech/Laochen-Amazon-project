"""深查前取材料（R-006）：发明取独立权利要求和附图，外观取多张附图；商标和图案用检索时已有的记录。几件同时取，单件取不到不影响别的。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config, enrich, images
from .sources import gpatents, http, ppubs

CLAIMS_KEEP = 3       # 每件发明最多比几项独立权利要求
CLAIM_CHARS = 2500    # 每项最多给 AI 多少字
DESIGN_FIGURES = 6    # 每件外观取几张附图（Google 图库里有的）
OFFICIAL_FIGURES = 4  # 要向美国专利局按页取时只取前几张（一般是立体图加几个主要视图）
PATENT_FIGURES = 2    # 每件发明留几张附图放进报告
WORKERS = 8


def _rel(task_dir: Path, path: Path) -> str:
    return path.relative_to(task_dir).as_posix()


def patent(finding: dict, cand: dict, task_dir: Path, opener=None) -> None:
    page, note, retry = None, "", False
    for _attempt in (1, 2):
        enrich.count("Google Patents 公开页")
        try:
            # 页面标注推出来的号码不知道是 B1 还是 B2：和补材料时一样，找不到换另一个试
            page = (gpatents.fetch_any if cand.get("marked_by") else gpatents.fetch)(cand["number"], opener)
            if page.get("number") and page["number"] != cand["number"]:  # 实际读到的是另一个类别码（B1/B2）：号码改过来
                cand["number"], cand["url"] = page["number"], gpatents.URL % page["number"]
                for field in ("number", "url"):
                    if field in finding:
                        finding[field] = cand[field]
            break
        except http.SourceError as exc:
            note = exc.message
            # 连不上、被限流、被拦（403，或者回了 200 却不是专利页）：再跑一次可能就好了；没收录（404）的再跑也一样
            retry = exc.kind in ("network", "quota") or exc.status in (403, 429) or exc.status >= 500 or (exc.kind == "format" and exc.status == 200)
            if exc.kind != "network":
                break
    claims = []
    if page:
        retry = False  # 页面读到了：里面没有权利要求的话再跑也一样
        found = page["independent_claims"]
        claims = [{"number": c["number"], "text": c["text"][:CLAIM_CHARS]} for c in found[:CLAIMS_KEEP]]
        if len(found) > CLAIMS_KEEP:
            finding["material_limit"] = "这件专利有 %d 项独立权利要求，只比了前 %d 项" % (len(found), CLAIMS_KEEP)
        finding["legal_status"] = gpatents.status_name(page["legal_status"]) or finding.get("legal_status", "")
        finding["expiry"] = page["expiry"] or finding.get("expiry", "")
        finding["owner"] = finding.get("owner") or page["owner"]
        folder = task_dir / "rights"
        for index, url in enumerate(page["images"][:PATENT_FIGURES], 1):
            dest = folder / ("%s-f%d%s" % (enrich._safe(cand["number"]), index, ".png" if ".png" in url.lower() else ".jpg"))
            if images.readable(dest) or (http.download(url, dest, opener=opener) and images.readable(dest)):
                finding["right_images"].append(_rel(task_dir, dest))
    if not claims and cand.get("claim1"):  # 公开页这次没读到：用初筛时留下的第一项（只有开头一段）
        claims = [{"number": 1, "text": cand["claim1"]}]
        finding["material_limit"] = "这次没有读到完整的权利要求，只用了第一项独立权利要求的开头一段"
    finding["claims"] = claims
    if not claims:
        finding["material_note"] = "没有取到权利要求（%s）" % (note or "公开页里没有权利要求")
        finding["material_retry"] = retry


def single_figure(cand: dict, path: Path) -> bool:
    """只取到一张图时：这件外观是不是本来就只有一张附图。拿不准的一律算"没取全"（比对时会标材料不全、不让评低）。
    算"本来就一张"的只有两种：专利局写明附图只有一页；或者这次读成了公开页、上面确实只列了一张，取到的就是它。"""
    name = Path(path).name
    if cand.get("euipo"):  # 欧盟外观：详情里写着一共几个视图
        return int(cand.get("euipo_views") or 0) == 1
    if cand.get("image_location"):
        try:
            start, last = enrich.figure_page(cand, 1)
            official = enrich.figure_file(cand, Path(path).parent, 1).name
        except (TypeError, ValueError):
            return False
        return bool(last) and last == start and name == official  # 取到的得是专利局那一页，公报的小图、初筛那张兜底的都不算
    return (enrich.google_ready(cand) and cand.get("page_note") == "" and cand.get("page_figures") == 1
            and len(cand.get("figures") or []) == 1 and "-g-" in name)


def _results(jobs: list) -> list:
    """收一组取图任务的结果；单张出错只是少这一张。"""
    found = []
    for job in jobs:
        try:
            path = job.result()
        except Exception:
            path = None
        if path and path not in found:
            found.append(path)
    return found


def gather(task, pairs: list, opener=None, usage=None) -> None:
    """pairs 是 [(候选, 比对记录)]。把材料写进比对记录：claims、right_images；取不到的写 material_note。"""
    task_dir = Path(task.dir)
    enrich.flush(None)  # 上一轮中途停下留在计数里的不算这一轮的
    designs = [(cand, finding) for cand, finding in pairs if finding["right_type"] == "design"]
    patents = [(cand, finding) for cand, finding in pairs if finding["right_type"] in ("patent", "utility_model")]
    session = ppubs.Session(opener)  # 用到的时候才去开
    refused_before = ppubs.IMAGE_STATE["refused"]
    refused = False
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        patent_jobs = [pool.submit(patent, finding, cand, task_dir, opener) for cand, finding in patents]
        figure_jobs = [pool.submit(enrich.figure_set, cand, task_dir, DESIGN_FIGURES, session, opener, OFFICIAL_FIGURES) for cand, _finding in designs]
        for (cand, finding), job in zip(patents, patent_jobs):
            try:
                job.result()
            except Exception as exc:  # 单件出了意料之外的错：这一件记成没取到，别的照常
                finding["claims"] = []
                finding.update(material_note="取权利要求时程序出错（%s）" % type(exc).__name__, material_retry=True)
        for (cand, finding), job in zip(designs, figure_jobs):
            try:
                found = job.result()
            except Exception:  # 单件出错只是这一件没有图
                found = []
            thumb = config.inside(task_dir, cand["thumb"]) if cand.get("thumb") else None
            if not found and thumb is not None and images.readable(thumb):
                found = [thumb]  # 多的没取到：至少用初筛时那一张
            found = [path for path in found if config.inside(task_dir, path) is not None]  # 落在任务目录外面的（比如目录被换成了链接）不要
            finding["right_images"] = [config.inside(task_dir, path).relative_to(task_dir.resolve()).as_posix() for path in found]
            if not found:
                finding.update(material_note="没有取到附图", material_retry=True)
            elif len(found) == 1 and not single_figure(cand, found[0]):
                finding["material_limit"] = "只取到 1 张附图，别的视图没有看到"
        # 所有件都取完了再看：这一轮向专利局取图被拒过，那些只拿到一张图的就是因为它不给图才没取全的，到时要重取重比
        refused = ppubs.image_blocked() or ppubs.IMAGE_STATE["refused"] > refused_before
        for cand, finding in designs:
            if finding.get("material_limit") and cand.get("image_location"):
                finding["limit_retry"] = refused
    enrich.flush(usage)
    if refused and any(f.get("limit_retry") or (c.get("image_location") and f.get("material_note")) for c, f in designs):
        task.add_incomplete("美国专利局的取图接口", "这会儿不给图（是它那边的原因），有的外观附图没取全；过一阵再运行同一条命令会补上", "design")
