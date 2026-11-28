"""入口与采集（R-001、R-002、R-014）：拿到商品资料和图片。拿不到是唯一不出报告的情况。"""
from __future__ import annotations

from ..outcome import NoProduct, StepFailed

HINT = "可以改用资料入口：自己提供一张产品图和一句描述。"


def run(ctx) -> None:
    task = ctx.task
    try:
        product = ctx.sources.capture(ctx)
    except StepFailed as exc:
        raise NoProduct("没拿到商品资料：%s" % exc.message)
    if not isinstance(product, dict):
        raise NoProduct("没拿到商品资料：采集返回的内容格式不对。" + HINT)
    title = str(product.get("title") or "").strip()
    images = [i for i in product.get("images") or [] if isinstance(i, dict) and (task.dir / str(i.get("file", ""))).is_file()]
    if not title:
        raise NoProduct("没拿到商品标题，无法开始排查。" + HINT)
    if not images:
        raise NoProduct("没拿到任何商品图片，无法开始排查。" + HINT)

    def texts(value):
        return [str(v).strip() for v in value if str(v).strip()] if isinstance(value, list) else []

    task["product"] = {
        "title": title,
        "brand": str(product.get("brand") or ""),
        "category": str(product.get("category") or ""),
        "bullets": texts(product.get("bullets")),
        "description": str(product.get("description") or ""),
        "asin": str(product.get("asin") or ""),
        "url": str(product.get("url") or ""),
        "marking": texts(product.get("marking")),
        "images": [{"id": str(i.get("id") or ""), "file": str(i["file"]), "url": str(i.get("url") or "")} for i in images],
        "captured_by": str(product.get("captured_by") or ""),
        "asin_note": str(product.get("asin_note") or ""),
    }
    ctx.say("  商品：%s（图片 %d 张）" % (title[:50], len(images)))
    wanted = texts(product.get("competitors_wanted"))
    task["competitors"] = []
    if wanted and hasattr(ctx.sources, "competitors"):  # 可选：竞品页上标注的专利、外观
        task["competitors"] = [c for c in ctx.sources.competitors(ctx, wanted) if isinstance(c, dict)]
        got = [c for c in task["competitors"] if c.get("status") == "ok"]
        ctx.say("  竞品：%d 个里采到 %d 个，页面标注 %d 处" % (len(wanted), len(got), sum(len(c.get("marking") or []) for c in got)))
