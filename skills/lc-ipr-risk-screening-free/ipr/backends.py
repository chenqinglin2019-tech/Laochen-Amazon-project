"""流程和外界之间的两道接口：AI 会话、数据来源。

每道接口有两种实现：
- 演示（Replay）：读 fixtures/ 里录好的数据和固定样例，不联网、不开 AI 会话；
- 真实（Live）：真的开 Codex 子会话、真的调检索接口。按开发计划分阶段接上，没接上的明确报"还没做"。
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from . import config, dossier, enrich, images, searching
from .ai import LiveAI
from .capture import chrome, ego, local
from .outcome import NoProduct, NotReady, StepFailed, WaitingUser
from .sources import euipo


inside = config.inside  # 把相对路径接到某个目录下面；跑到外面去的返回 None


def fixture_dir(name: str):
    """演示数据的名字只能是字母、数字、横线、下划线，而且必须真的在 fixtures/ 里。"""
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", name or ""):
        return None
    path = inside(config.FIXTURE_DIR, name)
    return path if path is not None and path.is_dir() else None


class Ctx:
    """一次运行里各步骤共用的东西。"""

    def __init__(self, task, usage, ai, sources, env=None, say=print):
        self.task = task
        self.usage = usage
        self.ai = ai
        self.sources = sources
        self.env = env or {}
        self.say = say


# ---------------- AI 会话 ----------------
class ReplayAI:
    """演示用：按 key 读固定样例。样例只证明流程通、格式对，不是真实判断。"""

    model = "演示样例"

    def __init__(self, fixture_dir: Path, usage):
        self.dir = Path(fixture_dir) / "ai"
        self.usage = usage

    def ask(self, step: str, key: str, prompt: str = None, images=(), schema: dict = None, tier: str = "light", timeout: int = None,
            image_max_px: int = None) -> dict:
        started = time.monotonic()
        path = inside(self.dir, key + ".json")
        if path is None or not path.is_file():
            self.usage.add_session(step, key, self.model, time.monotonic() - started, None, ok=False)
            raise StepFailed("演示数据里没有 %s 的样例" % key)
        answer = json.loads(path.read_text(encoding="utf-8"))
        self.usage.add_session(step, key, self.model, time.monotonic() - started, None, ok=True)
        return answer


# ---------------- 数据来源 ----------------
class ReplaySources:
    """演示用：读录好的商品资料和检索结果。"""

    def __init__(self, fixture_dir: Path, usage):
        self.dir = Path(fixture_dir)
        self.usage = usage

    def load(self, key: str):
        path = inside(self.dir, key + ".json")
        if path is None or not path.is_file():
            raise StepFailed("演示数据里没有 %s" % key)
        return json.loads(path.read_text(encoding="utf-8"))

    def capture(self, ctx) -> dict:
        """演示：读录好的商品资料，图片拷进任务目录。返回的格式和真实采集一样。"""
        product = dict(self.load("product"))
        images = []
        for image in product.get("images") or []:
            dest = ctx.task.dir / "images" / str(image.get("file", "")).split("/")[-1]
            if self.copy_file(str(image.get("file", "")), dest):
                images.append({"id": image.get("id", ""), "file": "images/" + dest.name, "url": image.get("url", "")})
        product["images"] = images
        product["captured_by"] = "演示数据"
        return product

    live = False

    def enrich(self, ctx) -> None:
        """演示数据里候选的材料是录好的，不用补。"""

    def more_figures(self, ctx, cand: dict) -> list:
        return []

    def search(self, ctx) -> dict:
        """演示：读录好的检索记录和候选清单。"""
        data = self.load("search")
        candidates = self.load("candidates")
        if not isinstance(data, dict):
            raise StepFailed("检索返回的记录格式不对")
        return {"searches": data.get("searches") or [], "candidates": candidates, "lens": data.get("lens") or [],
                "enforcement": data.get("enforcement") or [], "notes": data.get("notes") or []}

    def copy_file(self, rel: str, dest: Path) -> bool:
        src = inside(self.dir, rel)
        if src is None or not src.is_file():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        return True

    def dossier(self, ctx, pairs: list) -> None:
        """演示：权利要求和附图都是录好的（比对的回答也是录好的，所以没录材料的照样往下走）。"""
        path = self.dir / "dossier.json"
        recorded = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        for _cand, finding in pairs:
            finding["right_images"] = self.right_images(finding["number"], ctx.task.dir / "rights")
            if finding["right_type"] in ("patent", "utility_model"):
                finding["claims"] = (recorded.get(finding["number"]) or {}).get("claims") or []

    def right_images(self, number: str, dest_dir: Path) -> list:
        """把某件权利录好的附图拷进任务目录，返回相对任务目录的路径。"""
        out = []
        if not re.fullmatch(r"[A-Za-z0-9]+", number or ""):
            return out
        for src in sorted((self.dir / "rights").glob(number + "-*")):
            dest = dest_dir / src.name
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            out.append("rights/" + src.name)
        return out


class LiveSources:
    """真实的采集和检索接口。采集已接上（EGO 浏览器优先，没装用 Chrome；资料入口读本地文件夹）；检索第 2 阶段接上。"""

    def __init__(self, task_dir: Path, usage, env=None):
        self.task_dir = Path(task_dir)
        self.usage = usage
        self.env = env or {}
        euipo.configure(self.env)  # 续跑时不经过检索这一步，取图也要用到账号

    def capture(self, ctx) -> dict:
        task = ctx.task
        entry = task["entry"]
        if entry.get("type") == "input":
            found = local.capture(entry["path"], task.dir, entry.get("title", ""))
            method = "用户提供的资料"
            for note in found.get("notes") or []:
                task.add_incomplete("资料文件夹", note)
        else:
            found, method = self._capture_url(ctx, entry)
        product = dict(found["product"])
        product["url"] = entry.get("url") or product.get("url", "")
        product["images"] = [{"id": "IMG-%03d" % (i + 1), "file": "images/" + Path(item["file"]).name, "url": item.get("url", "")}
                             for i, item in enumerate(found["images"]) if images.readable(Path(item["file"]))]
        product["captured_by"] = method
        wanted = list(entry.get("competitors") or []) + list(found.get("competitors") or [])
        product["competitors_wanted"] = list(dict.fromkeys(str(w).strip() for w in wanted if str(w).strip()))[:config.COMPETITOR_MAX]
        if found.get("failed_images"):
            task.add_incomplete("%d 张商品图" % len(found["failed_images"]), "没有下载下来")
        wanted, got = entry.get("asin") or "", product.get("asin") or ""
        if wanted and got and wanted != got:
            ctx.say("  注意：链接里的 ASIN 是 %s，页面实际显示的是 %s" % (wanted, got))
            product["asin_note"] = "链接里的 ASIN 是 %s，页面实际显示的是 %s（可能跳到了别的款式）" % (wanted, got)
        return product

    def competitors(self, ctx, wanted: list) -> list:
        """采竞品页（可选）：品牌、标题、页面上的专利和外观标注、主图。遇到验证码、登录不等人，记"没采到"；任何一个没采成都不影响这一单。"""
        task = ctx.task
        site = config.COUNTRIES[task.country]["site"]
        out = []
        for index, raw in enumerate(wanted[:config.COMPETITOR_MAX], 1):
            found = re.search(r"(?:/dp/|/gp/product/|/gp/aw/d/|^)(B0[A-Z0-9]{8})(?:[/?#]|$)", raw.upper())
            asin = found.group(1) if found else ""
            url = raw if config.is_amazon_url(raw) else ("https://www.%s/dp/%s" % (site, asin) if asin else "")
            record = {"input": raw[:200], "asin": asin, "url": url, "title": "", "brand": "", "marking": [], "image": "", "status": "failed", "note": ""}
            if not url:
                record["note"] = "认不出是 ASIN 还是 Amazon 商品链接"
                out.append(record)
                continue
            used = ctx.usage.run_seconds() if getattr(ctx, "usage", None) else 0
            if used >= config.COMPETITOR_TIME_SECONDS:  # 竞品是可选的：采集这一步已经花太久，剩下的不采，保住 8 分钟的线
                record["note"] = "这一单已经用了 %d 秒，为了不超时没有采" % used
                out.append(record)
                continue
            name = asin or "c%d" % index
            folder = task.dir / "competitors" / name
            ctx.say("  采竞品 %s…" % (asin or url[:60]))
            try:
                if ego.available():
                    page = ego.capture(url, folder, "竞品 " + (asin or str(index)), timeout=config.COMPETITOR_CAPTURE_SECONDS)
                elif chrome.available():
                    page = chrome.capture(url, folder, "竞品 " + (asin or str(index)), wait_for_user=0, timeout=config.COMPETITOR_CAPTURE_SECONDS)
                else:
                    raise StepFailed("没有可用的浏览器")
            except WaitingUser:
                record["note"] = "要验证码或登录，没有等，没采到（不影响这一单）"
            except NoProduct:
                record["note"] = "商品页不存在或已下架"
            except StepFailed as exc:
                record["note"] = exc.message[:160]
            except Exception as exc:  # 竞品是可选的：任何意外都只记"没采到"，不影响这一单
                record["note"] = "采集时程序出错（%s），没采到" % type(exc).__name__
            else:
                try:
                    product = page.get("product") or {}
                    shots = [Path(i["file"]) for i in page.get("images") or [] if images.readable(Path(i["file"]))]
                    # 路径照主商品那样按文件名拼（浏览器给的是解析过的绝对路径，Windows 短路径、软链接下和任务目录对不上）
                    record.update(status="ok", title=str(product.get("title") or "")[:300], brand=str(product.get("brand") or "")[:80],
                                  marking=[str(m) for m in product.get("marking") or []][:5],
                                  image="competitors/%s/images/%s" % (name, shots[0].name) if shots else "")
                except Exception as exc:
                    record.update(status="failed", note="整理竞品资料时程序出错（%s），没采到" % type(exc).__name__)
            out.append(record)
        return out

    def _capture_url(self, ctx, entry: dict):
        task = ctx.task
        url, label = entry["url"], entry.get("asin") or "商品"
        prefer = entry.get("browser") or "auto"
        errors = []
        if prefer in ("auto", "ego") and ego.available():
            ctx.say("  用 EGO 浏览器采集…")
            try:
                found = ego.capture(url, task.dir, label, entry.get("ego_space"))
                entry.pop("ego_space", None)
                return found, "EGO 浏览器"
            except WaitingUser as wait:  # 记下工作区，用户处理完续跑时接着用
                entry["ego_space"] = wait.extra.get("space_id")
                task.save()
                raise
            except StepFailed as failed:
                errors.append("EGO 浏览器：" + failed.message)
        elif prefer == "ego":
            errors.append("EGO 浏览器：没有装")
        if prefer in ("auto", "chrome"):
            if chrome.available():
                ctx.say("  用 Chrome 采集…")
                try:
                    found = chrome.capture(url, task.dir, label)
                    entry.pop("ego_space", None)
                    return found, "Chrome"
                except WaitingUser:  # 续跑时还用 Chrome，过了验证的是它的浏览器资料
                    entry["browser"] = "chrome"
                    task.save()
                    raise
                except StepFailed as failed:
                    errors.append("Chrome：" + failed.message)
            else:
                errors.append("Chrome：采集组件没有装好")
        raise NoProduct("没拿到商品资料（%s）。可以改用资料入口：自己提供一张产品图和一句描述。" % "；".join(errors))

    live = True

    def enrich(self, ctx) -> None:
        enrich.run(ctx.task, ctx.say, usage=self.usage)

    def more_figures(self, ctx, cand: dict) -> list:
        return enrich.more_figures(cand, ctx.task.dir, usage=self.usage)

    def search(self, ctx) -> dict:
        """几路并行检索。返回 {"searches": 检索记录, "candidates": 候选, "lens": 以图搜图结果, "enforcement": 维权信号, "notes": 说明}。"""
        return searching.Searcher(ctx.task, self.env, self.usage, ctx.say).run()

    def load(self, key: str):
        raise NotReady("这一部分的真实数据还没接上（%s）。" % key)

    def copy_file(self, rel: str, dest: Path) -> bool:
        return False

    def dossier(self, ctx, pairs: list) -> None:
        dossier.gather(ctx.task, pairs, usage=self.usage)


def build(task, usage, env=None, say=print) -> Ctx:
    """按任务是不是演示，配好两道接口。"""
    config.set_secrets(env)
    demo = task["demo"]
    if demo:
        fixture = fixture_dir(demo)
        if fixture is None:
            raise StepFailed("找不到演示数据 %s" % demo)
        return Ctx(task, usage, ReplayAI(fixture, usage), ReplaySources(fixture, usage), env, say)
    return Ctx(task, usage, LiveAI(task.dir, usage, env), LiveSources(task.dir, usage, env), env, say)
