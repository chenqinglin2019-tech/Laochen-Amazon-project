"""产品理解与风险假设（R-003）：一次 AI 调用说清产品，列出可能属于别人的图案、角色、文字，给出检索词。"""
from __future__ import annotations

from .. import config, prompts, watchlist
from ..outcome import QuotaExhausted, StepFailed

REQUIRED = ("description", "names")


def fallback_from_title(product: dict) -> dict:
    """AI 两次都没成时的兜底：检索词只取标题，并在报告开头写明。"""
    return {
        "description": product.get("title", ""),
        "structure": [],
        "appearance": [],
        "names": [product.get("title", "")] if product.get("title") else [],
        "core_terms": [],
        "generic_names": [],
        "local_names": [],
        "features": [],
        "text_on_product": [],
        "marking": list(product.get("marking") or []),
        "hypotheses": watchlist.apply([], page_text(product)),
        "fallback": True,
    }


def texts(value) -> list:
    """回答里应该是"一串文字"的字段：不是列表就当没有，元素统一转成文字。"""
    if isinstance(value, str):
        value = [value]
    return [str(v) for v in value if v] if isinstance(value, list) else []


def clean_hypotheses(value) -> list:
    """风险假设逐条整理：只留字典，字段统一成文字。"""
    out = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            continue
        out.append({"kind": str(item.get("kind") or ""), "name": str(item["name"]).strip(), "owner": str(item.get("owner") or "").strip(),
                    "reason": str(item.get("reason") or ""), "search_terms": texts(item.get("search_terms"))})
    return out


def page_text(product: dict) -> str:
    return " ".join([product.get("title", "")] + list(product.get("bullets") or []) + [product.get("description", "")])


def specific_names(names: list, generic: list) -> list:
    """具体叫法里如果混进了上位词（和 generic_names 重复的），去掉；全被去掉时保留原样，免得没有检索词。"""
    blocked = {g.strip().lower() for g in generic}
    kept = [n for n in names if n.strip().lower() not in blocked]
    return kept or names


def run(ctx) -> None:
    task = ctx.task
    product = task["product"]
    prompt = prompts.understand(product, task.country)
    pictures = [task.dir / image["file"] for image in product["images"][:config.UNDERSTAND_IMAGES]]
    answer, last = None, ""
    for attempt in (1, 2):  # 会话本身的失败由 ai.ask 重试；这里只在"答了但内容不合格"时再问一次
        try:
            answer = ctx.ai.ask("understand", "understand", prompt, images=pictures, schema=prompts.UNDERSTAND_SCHEMA, tier="strong")
        except StepFailed as exc:
            answer, last = None, exc.message
            break
        except QuotaExhausted:
            task["understanding"] = fallback_from_title(product)
            raise
        missing = [key for key in REQUIRED if not (isinstance(answer, dict) and answer.get(key))]
        if not missing:
            break
        answer, last = None, "回答缺少 %s" % "、".join(missing)
    if answer is None:
        task["understanding"] = fallback_from_title(task["product"])
        task.add_incomplete("产品理解", "AI 没给出可用的回答（%s），检索词来自标题" % last)
        ctx.say("  产品理解未完成，改用标题里的词")
        return

    task["understanding"] = {
        "description": str(answer["description"]),
        "structure": texts(answer.get("structure")),
        "appearance": texts(answer.get("appearance")),
        "names": specific_names(texts(answer.get("names")), texts(answer.get("generic_names"))),
        "core_terms": specific_names(texts(answer.get("core_terms")), texts(answer.get("generic_names")))[:3],
        "generic_names": texts(answer.get("generic_names")),
        "local_names": texts(answer.get("local_names")),
        "features": texts(answer.get("features")),
        "text_on_product": texts(answer.get("text_on_product")),
        "marking": sorted(set(texts(answer.get("marking")) + list(product.get("marking") or []))),
        "hypotheses": watchlist.apply(clean_hypotheses(answer.get("hypotheses")), page_text(product)),
        "fallback": False,
    }
    ctx.say("  理解：%s" % task["understanding"]["description"][:60])
    for item in task["understanding"]["hypotheses"]:
        ctx.say("  风险假设：%s（%s）%s" % (item.get("name", ""), item.get("kind", ""),
                                      " → " + item["owner"] if item.get("owner") else ""))
