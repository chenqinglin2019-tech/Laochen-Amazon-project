"""Explicit, metered source adapters. Standard library only; no auto-provider routing.

Endpoint contracts checked against docs.scrapecreators.com/*/openapi.json on
2026-09-08. Billing is recorded per request; the selected segment's fixed
evidence range, rather than a credits cap, is the normal completion boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PRICE_DATE = "2026-09-08"
CREDIT_USD = 47 / 25000
API_BASE = "https://api.scrapecreators.com"
ENDPOINTS = {
    ("reddit", "search"): ("/v1/reddit/search", "after"),
    ("reddit", "comments"): ("/v1/reddit/post/comments", "cursor"),
    ("tiktok", "search"): ("/v1/tiktok/search/keyword", "cursor"),
    ("tiktok", "comments"): ("/v1/tiktok/video/comments", "cursor"),
    ("tiktok", "replies"): ("/v1/tiktok/video/comment/replies", "cursor"),
    ("instagram", "search"): ("/v2/instagram/reels/search", "page"),
    ("instagram", "comments"): ("/v2/instagram/post/comments", "cursor"),
    ("instagram", "replies"): ("/v1/instagram/post/comment/replies", "cursor"),
    ("youtube", "search"): ("/v1/youtube/search", "continuationToken"),
    ("youtube", "comments"): ("/v1/youtube/video/comments", "continuationToken"),
    ("youtube", "replies"): ("/v1/youtube/video/comment/replies", "continuationToken"),
}


class SourceError(Exception):
    pass


class SourceBudgetError(SourceError):
    pass


def default_config_path():
    return Path(os.environ.get("LCADMO_SCRAPECREATORS_CONFIG") or Path.home() / ".config/lc-amazon-market-opportunity/scrapecreators.env")


def load_key(path=None):
    """Read only our explicit local config or env; do not scan other skill keys."""
    path = Path(path or default_config_path())
    values = {}
    if path.exists():
        if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise SourceError("ScrapeCreators 配置权限必须为 0600")
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('\"\'')
    return str(os.environ.get("SCRAPECREATORS_API_KEY") or values.get("SCRAPECREATORS_API_KEY") or "").strip()


def configure(store, task_id, mode="free", credits_cap=None, valid_target=10000):
    if mode not in {"free", "scrapecreators"}:
        raise SourceError("collection_mode 必须为 free 或 scrapecreators")
    if mode == "scrapecreators" and credits_cap is not None and (isinstance(credits_cap, bool) or not isinstance(credits_cap, int) or credits_cap <= 0):
        raise SourceError("credits-cap 如设置必须为正整数")
    if isinstance(valid_target, bool) or not isinstance(valid_target, int) or valid_target < 3000:
        raise SourceError("valid-voc-target 必须为不低于 3000 的整数")
    task = store.task_payload(task_id)
    policy = task["collection_policy"]
    committed = budget(store, task_id)["committed_credits"]
    if mode == "scrapecreators" and credits_cap is not None and credits_cap < committed:
        raise SourceError("credits-cap 不能低于该任务已经消耗或预留的额度")
    policy.update(collection_mode=mode, credits_cap=credits_cap if mode == "scrapecreators" else 0,
                  evidence_target={"pilot_valid": 300, "checkpoint_valid": 3000,
                                   "segment_valid_min": 1000, "target_valid": valid_target},
                  counts_are_candidates=True, paid_authorization_explicit=mode == "scrapecreators",
                  spend_boundary="credits_cap" if mode == "scrapecreators" and credits_cap is not None else "task_completion")
    plan=task["research_plan"]
    plan["sample_target"].update(total_valid_min=3000,total_valid_max=valid_target)
    for scope,scope_target in plan["sample_target"]["per_scope"].items():
        scope_target.update(valid_min=3000 if scope=="category_30d" else 1000,valid_max=valid_target)
    store.update_task(task_id, collection_policy_json=json.dumps(policy, ensure_ascii=False), research_plan_json=json.dumps(plan,ensure_ascii=False))
    return policy


def budget(store, task_id):
    task = store.task_payload(task_id)
    policy = task["collection_policy"]
    rows = store.connection.execute("SELECT units,metadata_json FROM quota_ledger WHERE task_id=? AND unit_name='scrapecreators_credit'", (task_id,)).fetchall()
    used = sum(int(row["units"]) for row in rows)
    uncertain = sum(int(row["units"]) for row in rows if json.loads(row["metadata_json"]).get("charge_state") != "confirmed")
    raw_cap = policy.get("credits_cap")
    cap = raw_cap if isinstance(raw_cap, int) and not isinstance(raw_cap, bool) and raw_cap > 0 else None
    return {"credits_cap": cap, "committed_credits": used, "remaining_credits": None if cap is None else max(0, cap-used),
            "uncertain_credits": uncertain, "estimated_cost_usd": round(used*CREDIT_USD, 8),
            "price_basis": "47 USD / 25000 credits; estimate, not invoice", "price_snapshot_at": PRICE_DATE,
            "accounting_scope": "task_cumulative_including_prior_resumes",
            "spend_boundary": policy.get("spend_boundary", "credits_cap" if cap is not None else "task_completion"),
            "paid_channel_halt_reason": policy.get("paid_channel_halt_reason")}


def reserve(store, task_id, batch_id, endpoint, units=1):
    """A committed SQLite reservation precedes every request, including retries."""
    conn = store.connection
    conn.execute("BEGIN IMMEDIATE")
    try:
        policy = json.loads(conn.execute("SELECT collection_policy_json FROM tasks WHERE task_id=?", (task_id,)).fetchone()[0])
        if policy.get("collection_mode") != "scrapecreators" or policy.get("paid_authorization_explicit") is not True:
            raise SourceBudgetError("免费模式禁止收费请求")
        if policy.get("paid_channel_halt_reason"):
            raise SourceBudgetError("ScrapeCreators 任务付费通道已熔断；需核验端点价格后人工恢复")
        used = conn.execute("SELECT COALESCE(SUM(units),0) FROM quota_ledger WHERE task_id=? AND unit_name='scrapecreators_credit'", (task_id,)).fetchone()[0]
        cap = policy.get("credits_cap")
        if isinstance(cap, int) and not isinstance(cap, bool) and cap > 0 and used + units > cap:
            raise SourceBudgetError("ScrapeCreators 任务 credits 上限已达；保留检查点")
        cursor = conn.execute("""INSERT INTO quota_ledger(task_id,batch_id,source,operation,units,unit_name,
            estimated_cost_usd,cost_status,currency,price_snapshot_at,pricing_basis,occurred_at,metadata_json)
            VALUES(?,?,?,?,?,'scrapecreators_credit',?,'estimated_from_price_snapshot','USD',?,?,?,?)""",
            (task_id,batch_id,"scrapecreators",endpoint,units,units*CREDIT_USD,PRICE_DATE,
             "47 USD / 25000 credits; conservative reservation",datetime.now(timezone.utc).isoformat(),
             json.dumps({"charge_state":"reserved","reserved_credits":units,
                         "spend_boundary": policy.get("spend_boundary", "task_completion")})))
        conn.commit()
        return cursor.lastrowid
    except BaseException:
        conn.rollback()
        raise


def settle(store, ledger_id, response=None):
    row = store.connection.execute("SELECT task_id,units,metadata_json FROM quota_ledger WHERE ledger_id=?",(ledger_id,)).fetchone()
    value = response.get("credits_charged") if isinstance(response,dict) else None
    confirmed = isinstance(value,(int,float)) and not isinstance(value,bool) and value >= 0 and value == int(value)
    units = int(value) if confirmed else int(row["units"])
    metadata = json.loads(row["metadata_json"])
    metadata["charge_state"] = "confirmed" if confirmed else "uncertain"
    with store.connection:
        store.connection.execute("UPDATE quota_ledger SET units=?,estimated_cost_usd=?,metadata_json=? WHERE ledger_id=?",
                                 (units,units*CREDIT_USD,json.dumps(metadata),ledger_id))
    if confirmed and units > metadata["reserved_credits"]:
        policy = store.task_payload(row["task_id"])["collection_policy"]
        policy["paid_channel_halt_reason"] = "provider_price_exceeded_verified_reservation"
        store.update_task(row["task_id"], collection_policy_json=json.dumps(policy))
        raise SourceError("提供方计费高于已核验端点价格；停止收费并核查价格")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceError("拒绝 API 重定向，避免凭据转发")


def request_json(url, params, timeout, headers=None, method="GET"):
    body = None
    if method == "POST":
        body=json.dumps(params).encode()
        headers=dict(headers or {}, **{"Content-Type":"application/json"})
    else:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    with urllib.request.build_opener(_NoRedirect).open(req,timeout=timeout) as response:
        return json.load(response)


def _list(value):
    if isinstance(value,list): return value
    if isinstance(value,dict):
        for key in ("items","children","comments","results","data"):
            if isinstance(value.get(key),list): return value[key]
    return []


def normalize(platform, item, url="", parent="", context="", is_post=False):
    if not isinstance(item,dict): return None
    if isinstance(item.get("data"),dict): item=item["data"]
    identifier=str(item.get("cid") or item.get("id") or item.get("comment_id") or item.get("pk") or "")
    identifier=re.sub(r"^t[13]_", "", identifier) if platform=="reddit" else identifier
    # Missing native identity is never repaired with a text/position hash.
    if not identifier: return None
    author=item.get("user") or item.get("author") or {}
    if isinstance(author,str): author={"name":author}
    text=item.get("body") or item.get("text") or item.get("content") or item.get("selftext") or ""
    if is_post: text=(str(item.get("title") or item.get("desc") or "")+"\n"+str(text)).strip()
    direct=item.get("permalink") or item.get("url") or ""
    if direct.startswith("/"): direct="https://www.reddit.com"+direct
    if not direct and platform=="youtube": direct=url+('&' if '?' in url else '?')+"lc="+identifier
    if not direct and platform=="tiktok": direct=(item.get("share_info") or {}).get("url") or url
    if not direct and platform=="instagram": direct=url
    if not direct and platform=="x": direct="https://x.com/i/status/"+identifier
    if not direct and platform=="reddit": direct=url.rstrip('/')+'/'+identifier+'/'
    author_id=item.get("author_fullname") or author.get("uid") or author.get("id") or author.get("pk") or author.get("channelId") or ""
    label=author.get("unique_id") or author.get("username") or author.get("name") or author.get("nickname") or ""
    if label in {"[deleted]","[removed]"}: label=""
    parent_id = "" if is_post else (parent or re.sub(r"^t[13]_","",str(item.get("parent_id") or item.get("parent_comment_id") or "")) or context)
    return {"source":platform,"source_kind":"social","content_id":identifier,"text":str(text),
            "author_id":str(author_id),"author_label":str(label),"url":str(direct),
            "parent_content_id":parent_id,
            "thread_id":context or identifier,"published_at":item.get("created_at_iso") or item.get("created_utc") or item.get("create_time") or item.get("created_at") or item.get("publishedTime"),
            "raw":item,"geography_status":"not_verified"}


class ScrapeCreatorsCollector:
    def __init__(self,store,task_id,batch_id,key,http=None,timeout=20):
        self.store,self.task_id,self.batch_id,self.key,self.http,self.timeout=store,task_id,batch_id,key,http,timeout
        self.auth_failed=False

    def request(self,platform,operation,params,remaining):
        if not self.key: raise SourceError("ScrapeCreators 密钥未配置；该通道待配置，免费通道可继续")
        endpoint,_=ENDPOINTS[(platform,operation)]
        if operation == "search" and not str(params.get("query") or "").strip():
            raise SourceError("搜索词不能为空")
        if operation != "search" and not (platform == "youtube" and operation == "replies"):
            target = urllib.parse.urlsplit(str(params.get("url") or ""))
            allowed = {"reddit":{"reddit.com","www.reddit.com","old.reddit.com"},
                       "tiktok":{"tiktok.com","www.tiktok.com","m.tiktok.com","vm.tiktok.com","vt.tiktok.com"},
                       "instagram":{"instagram.com","www.instagram.com"},
                       "youtube":{"youtube.com","www.youtube.com","m.youtube.com","youtu.be"}}[platform]
            if target.scheme not in {"https","http"} or target.hostname not in allowed or target.username or target.password:
                raise SourceError("内容 URL 与平台不匹配；未发送收费请求")
        if operation == "replies" and not (params.get("continuationToken") if platform=="youtube" else params.get("comment_id")):
            raise SourceError("回复请求缺少原始评论 ID 或 continuationToken")
        units=15 if platform=="instagram" and operation=="comments" and params.get("include_replies")=="true" else 1
        for attempt in range(2):
            timeout=min(self.timeout,remaining())
            reservation=reserve(self.store,self.task_id,self.batch_id,endpoint,units)
            response=None
            try:
                method="POST" if platform=="reddit" and len(str(params.get("cursor") or ""))>1500 else "GET"
                if self.http is not None:
                    call=self.http.post_json if method=="POST" else self.http.get_json
                    response=call(API_BASE+endpoint,params,timeout=timeout,headers={"x-api-key":self.key})
                else:
                    response=request_json(API_BASE+endpoint,params,timeout,{"x-api-key":self.key},method)
            except Exception as exc:
                settle(self.store,reservation)
                status=getattr(exc,"code",getattr(exc,"status_code",None))
                if status in {401,403}: raise SourceError("ScrapeCreators 鉴权失败；请检查本机配置") from None
                if attempt==0 and (status in {429,500,502,503,504} or isinstance(exc,(TimeoutError,urllib.error.URLError))): continue
                raise SourceError("ScrapeCreators 请求失败；额度按不确定消费保留，检查点可恢复") from None
            settle(self.store,reservation,response)
            if not isinstance(response,dict) or response.get("success") is False:
                raise SourceError("ScrapeCreators 返回失败；已按返回计费或预留额度记录")
            def clean(value):
                if isinstance(value,dict):
                    return {k:("<redacted>" if k.lower() in {"x-api-key","api_key","scrapecreators_api_key","authorization","secret"} else clean(v)) for k,v in value.items()}
                if isinstance(value,list): return [clean(v) for v in value]
                if isinstance(value,str): return value.replace(self.key,"<redacted>")
                return value
            return clean(response)

    def collect(self,batch,emit,add_target,remaining,should_stop):
        platform=batch["source"]
        meta=batch.get("metadata") or {}
        operation=str(meta.get("operation") or ("comments" if batch.get("video_url") else "search"))
        if (platform,operation) not in ENDPOINTS: raise SourceError("不支持的 ScrapeCreators 平台或操作")
        url=str(batch.get("video_url") or meta.get("url") or "")
        context=str(batch.get("video_id") or meta.get("content_id") or url)
        params={"query":batch["query_text"]} if operation=="search" else {"url":url}
        if operation=="search" and platform=="instagram": params["page"]=1
        if operation=="comments" and platform=="instagram": params["include_replies"]="false"
        if operation=="comments" and platform=="youtube": params["order"]="newest"
        if operation=="replies":
            if platform=="youtube": params={"continuationToken":meta.get("continuationToken")}
            else: params["comment_id"]=meta.get("comment_id")
        state=self.store.checkpoint(self.task_id,self.batch_id,"direct_source")
        if state.get("done"): return
        if not state: state={"pending":[{"operation":operation,"params":params,"parent":meta.get("comment_id","")}],"seen":[],"pages":0}
        seen=set(state.get("seen",[]))
        def enqueue(op,pr,parent=""):
            marker=json.dumps([op,pr],sort_keys=True)
            if marker not in seen and not any(json.dumps([p["operation"],p["params"]],sort_keys=True)==marker for p in state["pending"]):
                state["pending"].append({"operation":op,"params":pr,"parent":parent})
        while state["pending"]:
            should_stop()
            current=state["pending"][0]
            op,pr=current["operation"],current["params"]
            marker=json.dumps([op,pr],sort_keys=True)
            payload=state.get("cached_page")
            if payload is None:
                payload=self.request(platform,op,pr,remaining)
                # Persist charged page before emission; resume does not buy it again.
                state["cached_page"]=payload
                self.store.save_checkpoint(self.task_id,self.batch_id,state,"direct_source")
            if op=="search":
                keys={"reddit":["posts"],"tiktok":["search_item_list"],"instagram":["reels"],"youtube":["videos","shorts"]}[platform]
                items=[i for key in keys for i in _list(payload.get(key))]
                for raw in items:
                    item=raw.get("aweme_info",raw) if isinstance(raw,dict) else {}
                    ident=str(item.get("id") or item.get("aweme_id") or item.get("shortcode") or "")
                    target=item.get("permalink") or item.get("url") or ("https://www.tiktok.com/@%s/video/%s"%((item.get("author") or {}).get("unique_id","_"),ident) if platform=="tiktok" else "")
                    if target and str(target).startswith("/"): target="https://www.reddit.com"+target
                    if target and ident: add_target(platform,target,ident,item)
            else:
                items=_list(payload.get("comments"))
                if meta.get("parent_context") and context:
                    emit({"source":platform,"source_kind":"social","content_id":context,
                          "text":meta["parent_context"],"thread_id":context,"url":url,
                          "is_creator_content":platform!="reddit","raw":{"content_role":"creator_context" if platform!="reddit" else "post_context"}})
                def walk(raw,parent=""):
                    record=normalize(platform,raw,url,parent,context)
                    if record: emit(record)
                    ident=record["content_id"] if record else ""
                    replies=raw.get("replies") or raw.get("reply_comment") or []
                    for child in _list(replies): walk(child,ident)
                    if platform=="reddit" and isinstance(replies,dict):
                        more=replies.get("more") or {}
                        token=more.get("cursor") or more.get("next_cursor")
                        if token: enqueue("comments",{"url":url,"cursor":token},ident)
                    if op=="comments" and ident:
                        if platform=="youtube" and raw.get("repliesContinuationToken"):
                            enqueue("replies",{"continuationToken":raw["repliesContinuationToken"]},ident)
                        elif platform in {"tiktok","instagram"} and int(raw.get("reply_comment_total") or raw.get("child_comment_count") or 0)>0:
                            enqueue("replies",{"url":url,"comment_id":ident},ident)
                post=payload.get("post")
                if isinstance(post,dict):
                    record=normalize(platform,post,url,context=context,is_post=True)
                    if record: emit(record)
                for item in items:
                    if isinstance(item,dict): walk(item,current.get("parent",""))
            cursor_key=ENDPOINTS[(platform,op)][1]
            token=payload.get(cursor_key)
            if platform=="reddit" and op=="comments":
                more=payload.get("more") or {}
                token=more.get("cursor") or more.get("next_cursor")
            if platform=="instagram" and op=="search": token=int(pr.get("page",1))+1 if items and int(pr.get("page",1))<11 else None
            # Discovery is deliberately bounded; analysis directs additional queries.
            can_page=op!="search" or state["pages"]<2
            if token not in (None,"",0,False) and payload.get("has_more") not in (False,0) and can_page:
                next_params=dict(pr);next_params[cursor_key]=token
                enqueue(op,next_params,current.get("parent",""))
            seen.add(marker)
            state["seen"]=sorted(seen)
            state["pending"].pop(0)
            state.pop("cached_page",None)
            state["pages"]+=1
            state["done"]=not state["pending"]
            self.store.save_checkpoint(self.task_id,self.batch_id,state,"direct_source")


def free_collect(batch,runner,emit,add_target,timeout,remaining):
    """Only explicit public/free endpoints. Never invoke an auto aggregator."""
    platform=batch["source"]
    url=str(batch.get("video_url") or "")
    if platform=="reddit" and url:
        parsed=urllib.parse.urlsplit(url)
        if parsed.hostname not in {"reddit.com","www.reddit.com","old.reddit.com"}: raise SourceError("Reddit 来源 URL 不合法")
        try:
            payload=request_json("https://www.reddit.com"+parsed.path.rstrip('/')+".json",{"limit":100,"depth":10,"raw_json":1},min(timeout,remaining()),{"User-Agent":"consumer-voice-research/1.0"})
        except Exception: raise SourceError("免费 Reddit 评论访问受限；保留帖子，等待可用来源或用户导入") from None
        def walk(nodes,parent=""):
            for wrapped in nodes:
                if not isinstance(wrapped,dict): continue
                if wrapped.get("kind")=="more": continue
                item=wrapped.get("data",wrapped)
                record=normalize("reddit",item,url,parent,str(batch.get("video_id") or url),is_post=wrapped.get("kind")=="t3")
                if record: emit(record)
                replies=item.get("replies")
                if isinstance(replies,dict): walk(_list(replies.get("data",{})),record["content_id"] if record else parent)
        for listing in payload if isinstance(payload,list) else []: walk(_list(listing.get("data",{})))
        return {"coverage_status":"best_effort","top_level_limit":100,"max_depth":10,
                "more_children_expanded":False,"possible_truncation":True}
    if platform not in {"reddit","x"}: raise SourceError("该平台没有已核验的免费直连适配器")
    if url: raise SourceError("X 线程深读需导入带原始 ID 的授权数据；自动路径仅搜索")
    argv=["opencli","reddit" if platform=="reddit" else "twitter","search",str(batch.get("query_text") or ""),"--limit","100","-f","json"]
    try: result=runner(argv,min(timeout,remaining()))
    except Exception: raise SourceError("OpenCLI 不可用或超时；请检查安装和浏览器登录") from None
    if result.returncode: raise SourceError("OpenCLI 来源访问失败；请检查浏览器连接或登录")
    try: payload=json.loads(result.stdout)
    except (ValueError,TypeError): raise SourceError("OpenCLI 未返回可解析 JSON") from None
    items=_list(payload)
    for item in items:
        if not isinstance(item,dict): continue
        record=normalize(platform,item,is_post=platform=="reddit")
        if record: emit(record)
        if platform=="reddit" and item.get("id") and item.get("url"):
            add_target(platform,item["url"],str(item["id"]),item)
    return {"coverage_status":"best_effort","search_result_limit":100,"search_pagination":False}
