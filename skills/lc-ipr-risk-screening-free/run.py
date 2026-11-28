#!/usr/bin/env python3
"""侵权风险快查：一条命令开跑，一单只查一个国家。

  python run.py --url <Amazon 链接> [--country US]       链接入口；不给国家就取链接所在站点的国家
  python run.py --input <资料文件夹> --country US          资料入口
  python run.py --task-dir <原任务目录>                    续跑（停下之后用同一条命令接着做）
  python run.py --demo sun-badge-reel                      用录好的数据演示（不联网、不开 AI 会话）
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ipr import auth, backends, config, outcome, pipeline, runlock  # noqa: E402
from ipr.capture import local  # noqa: E402
from ipr.state import TaskState, now_iso  # noqa: E402
from ipr.usage import Usage  # noqa: E402


DEMO_COUNTRY = "US"  # 录好的演示数据都是美国站的任务
PYTHON_NAME = "py -3" if os.name == "nt" else "python3"  # 提示用户续跑时写哪个命令（和安装说明一致）
VENV_MARK = "LC_IPR_IN_VENV"  # 已经换到 .venv 里跑了的记号，免得来回换
VENV_READY = "lc-ipr-ready"   # 安装脚本在 .venv 里放的记号：依赖装好了，可以用


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="侵权风险快查（版本 %s）" % config.VERSION)
    entry = parser.add_mutually_exclusive_group()
    entry.add_argument("--url", help="Amazon 商品链接")
    entry.add_argument("--input", help="产品资料文件夹（没有链接时用）")
    entry.add_argument("--demo", help="用 fixtures/ 里录好的数据演示，例如 sun-badge-reel")
    parser.add_argument("--country", help="目的国：US、GB、FR、DE、IT、ES、JP 之一")
    parser.add_argument("--title", help="资料入口用：一句品名或描述（文件夹里没有文字说明时）")
    parser.add_argument("--browser", choices=["auto", "ego", "chrome"], default="auto",
                        help="链接入口用哪个浏览器采集。默认 auto：装了 EGO 浏览器就用它，没装用 Chrome")
    parser.add_argument("--task-dir", help="任务目录；续跑时给原来的目录")
    parser.add_argument("--fresh", action="store_true", help="不接着上次停下的任务，重新开一单")
    parser.add_argument("--pack", metavar="任务目录", help="把一单打成可分享的运行包（不跑排查，不联网）")
    parser.add_argument("--competitor", action="append", default=[], metavar="ASIN或链接",
                        help="可选：竞品（可以给多次，最多 3 个）。会采它的页面，看它标注了哪些专利、外观")
    return parser.parse_args(argv)


def resolve_country(url: str, country: str):
    """返回 (目的国, 链接站点国家)。目的国不在七国内时抛 ValueError，里面是给用户看的话。"""
    site = config.country_from_url(url) if url else None
    if country:
        code = country.strip().upper()
        if code == "UK":
            code = "GB"
        if code not in config.COUNTRIES:
            raise ValueError("目的国 %s 不在支持的七国内。请用 --country 指定：%s。" % (country, "、".join(config.COUNTRIES)))
        return code, site
    if site:
        return site, site
    raise ValueError("这个链接的站点不在支持的七国内，也没有指定目的国。请加 --country，可选：%s。" % "、".join(config.COUNTRIES))


def asin_from_url(url: str) -> str:
    match = re.search(r"/(?:dp|gp/product|gp/aw/d)/([A-Za-z0-9]{10})(?![A-Za-z0-9])", url or "")
    return match.group(1).upper() if match else ""


def task_prefix(label: str, country: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_\-]+", "-", label).strip("-")[:40] or "task"
    return "%s-%s-" % (safe, country)


def default_task_dir(label: str, country: str) -> Path:
    stamp = re.sub(r"[^0-9]", "", now_iso()[:19])
    return config.RUNS_DIR / (task_prefix(label, country) + stamp[:8] + "-" + stamp[8:])


def load_task(folder: Path):
    """读一个任务目录；内容不完整或不是我们的任务就返回 None。"""
    try:
        task = TaskState.load(folder)
        ok = (isinstance(task.data, dict) and isinstance(task["entry"], dict) and isinstance(task["outcome"], dict)
              and isinstance(task["demo"], str) and isinstance(task["steps"], dict)
              and all(isinstance(task[key], dict) for key in ("product", "understanding", "overall"))
              and all(isinstance(task[key], list) for key in ("searches", "candidates", "findings", "rights_summary", "incomplete"))
              and all(isinstance(step, dict) for step in task["steps"].values())
              and task.country in config.COUNTRIES and not set(config.STEPS) - set(task["steps"]))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return task if ok else None


def unfinished_task(label: str, country: str, entry: dict):
    """"把同一条命令原样再跑一次"就能续跑：默认目录下同一个入口的最近一个任务，如果停在"等用户处理"或"额度用尽"，返回它。"""
    if not config.RUNS_DIR.is_dir():
        return None
    for folder in sorted(config.RUNS_DIR.glob(task_prefix(label, country) + "*"), reverse=True):
        task = load_task(folder)
        if task is None or task["demo"] or task.country != country:
            continue
        if any(task["entry"].get(key) != entry.get(key) for key in ("type", "url", "path", "title")):
            continue  # 不是同一个入口（或换了说明）：接着往前找
        if runlock.holder(folder):
            raise ValueError("这个商品正在另一个窗口里查（任务目录 %s）。等它跑完再看报告；确实要再开一单请加 --fresh。" % folder)
        kind = task["outcome"].get("kind")
        if kind in (outcome.WAITING_USER, outcome.QUOTA_STOPPED):
            return task
        if kind == outcome.ERROR_STOPPED and hours_since(task["outcome"].get("finished_at")) <= config.RESUME_ERROR_HOURS:
            return task  # 出错停下的：一天之内再跑同一条命令算续跑，已经查过的不重查
        if not kind and hours_since(task.data.get("created_at")) <= config.RESUME_ERROR_HOURS:
            return task  # 没跑完就断了的（比如窗口被关掉、电脑睡眠）：同样接着跑
        return None
    return None


def hours_since(stamp) -> float:
    """从这个时间到现在过了几个小时；时间写得不对的当作很久以前。"""
    try:
        then = datetime.fromisoformat(str(stamp))
        now = datetime.now(then.tzinfo) if then.tzinfo else datetime.now()
        return max(0.0, (now - then).total_seconds() / 3600.0)
    except (TypeError, ValueError):
        return float("inf")


def check_resume(task: TaskState, args) -> str:
    """续跑时：入口和国家以原任务为准，给了不一样的就拒绝。只检查，不改任务。
    返回要改用的浏览器（--browser 可以在续跑时改），不用改时返回空字符串。"""
    entry = task["entry"]
    conflicts = []
    if args.country and args.country.strip().upper().replace("UK", "GB") != task.country:
        conflicts.append("目的国（原任务是 %s）" % task.country)
    if args.url and args.url != entry.get("url"):
        conflicts.append("链接")
    if args.input and (entry.get("type") != "input" or str(Path(args.input).expanduser().resolve()) != entry.get("path")):
        conflicts.append("资料入口")
    if args.demo and args.demo != task["demo"]:
        conflicts.append("演示数据")
    if args.title and args.title.strip() != entry.get("title", ""):
        conflicts.append("--title 的说明")
    if conflicts:
        raise ValueError("这个任务目录里已经有一个任务，和这次给的%s不一致。续跑只需要 --task-dir；要查别的请换一个目录。" % "、".join(conflicts))
    if args.browser != "auto" and entry.get("type") == "url" and entry.get("browser") != args.browser:
        return args.browser
    return ""


def prepare(args) -> dict:
    """只做检查，不联网、不建目录。返回 {"resume": 任务} 或 {"create": 建任务要的参数}；参数不对抛 ValueError。"""
    task_dir = Path(args.task_dir).expanduser().resolve() if args.task_dir else None
    if task_dir and (task_dir / config.STATE_FILE).exists():
        task = load_task(task_dir)
        if task is None:
            raise ValueError("任务目录 %s 里的状态文件读不了或内容不完整。请换一个新的任务目录重新跑。" % task_dir)
        return {"resume": task, "browser": check_resume(task, args)}
    if args.demo:
        if backends.fixture_dir(args.demo) is None:
            raise ValueError("找不到演示数据 %s。" % args.demo)
        country, site = resolve_country("", args.country or DEMO_COUNTRY)
        if country != DEMO_COUNTRY:
            raise ValueError("演示数据是按%s录的，只能按%s演示。" % ((config.COUNTRIES[DEMO_COUNTRY]["name"],) * 2))
        entry = {"type": "demo", "name": args.demo}
        label = args.demo
    elif args.url:
        if not config.is_amazon_url(args.url):
            raise ValueError("这不是一个 Amazon 商品链接（要以 http:// 或 https:// 开头，域名是 amazon 的站点，中间不能有空格；"
                             "a.co、amzn.to 这类分享短链不支持，请打开后复制地址栏里的完整链接）。")
        country, site = resolve_country(args.url, args.country)
        entry = {"type": "url", "url": args.url, "asin": asin_from_url(args.url), "site_country": site, "browser": args.browser}
        label = entry["asin"] or "link"
    elif args.input:
        if not args.country:
            raise ValueError("资料入口必须用 --country 指定目的国，可选：%s。" % "、".join(config.COUNTRIES))
        country, site = resolve_country("", args.country)
        folder = Path(args.input).expanduser().resolve()
        blocking = local.inspect(folder, args.title or "")["blocking"]
        if blocking:
            raise ValueError("资料不够：%s。" % "；".join(blocking))
        entry = {"type": "input", "path": str(folder), "title": (args.title or "").strip()}
        label = folder.name
    elif args.task_dir:
        raise ValueError("任务目录 %s 里没有可以续跑的任务。" % args.task_dir)
    else:
        raise ValueError("请给一个 --url 链接、--input 资料文件夹，或用 --task-dir 续跑。")
    if args.competitor and entry.get("type") in ("url", "input"):
        entry["competitors"] = [c.strip() for c in args.competitor if c.strip()][:config.COMPETITOR_MAX]
    if task_dir is None and not args.demo and not args.fresh:
        waiting = unfinished_task(label, country, entry)
        if waiting is not None:
            return {"resume": waiting, "found": True, "browser": check_resume(waiting, args)}
    return {"create": {"task_dir": task_dir or default_task_dir(label, country), "entry": entry, "country": country, "demo": args.demo or ""}}


def venv_python() -> Path:
    return config.SKILL_DIR / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _hand_over(command: list, env: dict):
    """把这一次运行交给另一个 Python。Mac / Linux 上直接替换掉当前进程（中断、超时都作用在同一个进程上，不会留下孤儿）；
    Windows 上没有这种替换，只能起一个子进程等它结束。"""
    if os.name == "nt":
        try:
            code = subprocess.call(command, env=env)
        except KeyboardInterrupt:
            return 130  # 用户按了 Ctrl+C：子进程也收到了，这里安静退出
        if code not in outcome.EXIT_CODES.values() and code != 2:  # 2 是参数写错
            print("本目录的 .venv 用不了了（退出码 %d）。请重新运行 %s install.py 再试。" % (code, PYTHON_NAME))
        return code
    sys.stdout.flush()
    sys.stderr.flush()
    os.execve(command[0], command, env)


def relaunch_in_venv(argv: list, runner=_hand_over):
    """安装脚本把图像库装进了本目录的 .venv 时：换到那个 Python 里跑，用户和 Codex 都只用记一条命令。
    已经在里面了、或者没有 .venv，返回 None；换过去跑完了，返回它的退出码。"""
    target = venv_python()
    ready = config.SKILL_DIR / ".venv" / VENV_READY  # 安装脚本装好图像库之后才放这个记号：建到一半的 .venv 不用
    if os.environ.get(VENV_MARK) or not target.is_file() or not ready.is_file():
        return None
    try:
        # 看的是"现在是不是在这个环境里"，不能比解释器的路径：Mac 上 .venv/bin/python 只是指向系统 Python 的链接
        if Path(sys.prefix).resolve() == (config.SKILL_DIR / ".venv").resolve():
            return None
        return runner([str(target), str(Path(__file__).resolve())] + list(argv), env=dict(os.environ, **{VENV_MARK: "1"}))
    except OSError:
        return None  # 换不过去就用现在这个 Python 接着跑；缺图像库的话后面会说明


def summary_lines(task) -> list:
    """结论摘要：给用户（和替用户读输出的 Codex）看的几行，不用再去打开报告——报告里内嵌着图片，很大。"""
    overall = task["overall"] or {}
    if not overall:
        return []
    lines = ["结论摘要：", "  总风险等级：%s%s　置信度：%s" % (overall.get("risk", ""), "（仅就已查部分）" if overall.get("partial") else "",
                                                 overall.get("confidence") or "—"),
             "  建议：%s" % overall.get("advice", "")]
    rows = ["%s %s" % (row.get("name", ""), {"not_applicable": "不适用", "not_searched": "未检索", "nothing": "无可查项"}.get(row.get("state"), row.get("risk") or "—"))
            for row in task["rights_summary"] or []]
    if rows:
        lines.append("  各类权利：" + "；".join(rows))
    comps = [c for c in task.data.get("competitors") or [] if isinstance(c, dict)]
    if comps:
        got = [c for c in comps if c.get("status") == "ok"]
        lines.append("  竞品：%d 个里采到 %d 个，页面上有专利或外观标注的 %d 个（标注的号码已列入深查）" % (
            len(comps), len(got), sum(1 for c in got if c.get("marking"))))
    image_notes = [n for n in (task["understanding"] or {}).get("image_notes") or [] if isinstance(n, dict) and n.get("what")]
    if image_notes:
        lines.append("  上架图片要注意的有 %d 处（道具、水印或别人的标识），明细见报告" % len(image_notes))
    marks = [str(m.get("term", "")) for m in task.data.get("manual_marks") or [] if isinstance(m, dict) and m.get("term")]
    if marks:
        lines.append("  商标未检索，要人工核对的词：%s（检索链接见报告\"商标要人工核对的词\"）" % "、".join(marks))
    middle = config.risk_rank(config.RECHECK_FROM)
    key = [f for f in task["findings"] if f.get("status") == "compared" and config.risk_rank(f.get("risk", "")) >= middle]
    key.sort(key=lambda f: -config.risk_rank(f["risk"]))
    for finding in key[:12]:
        lines.append("  要人工核对：[%s] %s %s %s" % (finding["risk"], config.RIGHT_NAMES.get(finding["right_type"], ""),
                                               finding.get("number", ""), " ".join(str(finding.get("title", "")).split())[:60]))
    if len(key) > 12:
        lines.append("  （评为中及以上的共 %d 件，其余见报告）" % len(key))
    if task["incomplete"]:
        lines.append("  没查到或没查完的有 %d 项，明细见报告" % len(task["incomplete"]))
    return [config.redact(line) for line in lines]


def pack_command(task_dir: str, env=None) -> int:
    from ipr import pack
    try:
        if env is None:  # 后台鉴权 token 也要核对（它在 config.json 或环境变量里，不在 .env 里）
            env = dict(config.load_env())
            try:
                env["_backend_token"] = auth.load_backend()[1]
            except Exception:
                pass
        out = pack.pack(task_dir, env)
    except ValueError as exc:
        print("没有打包：%s" % str(exc).replace("没有打包：", ""))
        return outcome.EXIT_CODES[outcome.ERROR_STOPPED]
    except OSError as exc:
        print("没有打包：读写文件出错（%s）" % type(exc).__name__)
        return outcome.EXIT_CODES[outcome.ERROR_STOPPED]
    print("运行包：%s" % out)
    return outcome.EXIT_CODES[outcome.DONE]


def main(argv=None, env=None) -> int:
    """env 不给时读 Skill 目录的 .env 和环境变量；测试传空字典，不碰真实的 key。"""
    if argv is None and env is None:  # 只在真的从命令行运行时换
        code = relaunch_in_venv(sys.argv[1:])
        if code is not None:
            return code
    config.setup_streams()
    args = parse_args(argv)
    if args.pack:
        return pack_command(args.pack, env)
    try:
        plan = prepare(args)  # 先检查参数
        demo = plan["resume"]["demo"] if "resume" in plan else plan["create"]["demo"]
        if not demo:  # 再鉴权：演示不联网不鉴权，其余每次运行（包括续跑）都鉴权；不通过就不建任务目录
            auth.require()
        if "resume" in plan:
            task = plan["resume"]
            lock = runlock.RunLock(task.dir, count=not demo).acquire()  # 先占住任务目录，再动里面的东西
            if plan.get("browser"):  # 续跑时改用另一个浏览器采集：鉴权通过之后才写进任务
                task["entry"]["browser"] = plan["browser"]
                try:
                    task.save()
                except BaseException:
                    lock.release()
                    raise
            if plan.get("found"):
                print("接着上次停下的任务续跑：%s（已经查过的不重查；要重新开一单请加 --fresh）" % task.dir)
        else:
            task = TaskState.create(**plan["create"])
            lock = runlock.RunLock(task.dir, count=not demo).acquire()
    except ValueError as exc:
        print("没有开跑：%s" % exc)
        return outcome.EXIT_CODES[outcome.ERROR_STOPPED]
    except outcome.StopSignal as stop:
        print("没有开跑：%s" % stop.message)
        return outcome.EXIT_CODES[outcome.ERROR_STOPPED]
    except OSError as exc:
        print("没有开跑：任务目录或资料文件夹读写不了（%s）。请检查路径和权限，或者换一个任务目录。" % type(exc).__name__)
        return outcome.EXIT_CODES[outcome.ERROR_STOPPED]
    print("任务目录：%s　目的国：%s" % (task.dir, config.COUNTRIES[task.country]["name"]))
    try:
        try:
            usage = Usage(task.dir)
        except (ValueError, OSError, TypeError, AttributeError, KeyError):
            print("没有开跑：任务目录里的用量文件读不了。请加 --fresh 重新开一单（用 --task-dir 的话换一个新的目录）。")
            return outcome.EXIT_CODES[outcome.ERROR_STOPPED]
        usage.lock = lock
        try:
            ctx = backends.build(task, usage, config.load_env() if env is None else env)
        except (outcome.StopSignal, outcome.StepFailed) as stop:
            print("没有开跑：%s" % stop.message)
            return outcome.EXIT_CODES[outcome.ERROR_STOPPED]
        result = pipeline.run(ctx)
    finally:
        lock.release()  # 不管怎么结束，都把"正在跑"的记号拿掉

    print("\n结果：%s" % outcome.TITLES[result["kind"]])
    if result.get("message"):
        print("说明：%s" % result["message"])
    if result.get("resume_at"):
        print("恢复时间：%s" % result["resume_at"])
    elif result["kind"] == outcome.QUOTA_STOPPED:
        print("恢复时间：Codex 这次没有给出，可以在 Codex 里看额度什么时候恢复")
    if result["kind"] in (outcome.QUOTA_STOPPED, outcome.WAITING_USER, outcome.ERROR_STOPPED):
        within = "（出错停下的要在 %d 小时以内）" % config.RESUME_ERROR_HOURS if result["kind"] == outcome.ERROR_STOPPED else ""
        again = "" if task["demo"] else "把刚才的命令原样再跑一次%s，已经查过的不重查；或者" % within  # 演示只能用 --task-dir 接着跑
        print("续跑：%s用 %s run.py --task-dir \"%s\"" % (again, PYTHON_NAME, task.dir))
    if result.get("report"):
        for line in summary_lines(task):
            print(line)
        print("报告：%s" % result["report"])
    summary = result["usage"]
    if task["demo"]:
        print("用时 %.1f 分钟，演示数据，用了 %d 份固定样例，没有真实的 AI 会话" % (summary["seconds"] / 60.0, summary["sessions"]))
    else:
        print("用时 %.1f 分钟，AI 会话 %d 个，token %s" % (summary["seconds"] / 60.0, summary["sessions"],
              "未知" if summary["unknown_sessions"] and not summary["tokens"] else format(summary["tokens"], ",")))
    return outcome.EXIT_CODES[result["kind"]]


if __name__ == "__main__":
    sys.exit(main())
