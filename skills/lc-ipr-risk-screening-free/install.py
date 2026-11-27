#!/usr/bin/env python3
"""安装和自检（需求 R-012）。在 Skill 目录里运行：

    Mac：      python3 install.py
    Windows：  py -3 install.py        （没有 py 的话用 python install.py）

它会：补上空的配置文件（.env、config.json，已有的不动）→ 在本目录建 .venv 并把图像库装进去（不动系统的 Python）→
没装 EGO 浏览器时装 Chrome 采集要用的组件 → 自检。只想自检：加 --check。
不改系统设置、不动代理、不装 Python / Node / 浏览器这些系统程序；缺哪样就告诉你去哪装。"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

OK, BAD, WARN = "ok", "bad", "warn"
ON_WINDOWS = os.name == "nt"
MARKS = {OK: "[通过]", BAD: "[没过]", WARN: "[提醒]"}  # 用文字不用 ✓ ✗：中文 Windows 的默认编码里没有那两个符号，会变成问号
MIRROR_HINT = "国内装得慢或连不上时，先设镜像再重跑：Mac `export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`，Windows `$env:PIP_INDEX_URL=\"https://pypi.tuna.tsinghua.edu.cn/simple\"`"


VENV_READY = "lc-ipr-ready"  # 依赖装好之后放在 .venv 里的记号；run.py 看到它才会换到 .venv 里跑（两边的名字要一致）
PYTHON_NAME = "py -3" if os.name == "nt" else "python3"


def venv_python(root: Path = HERE) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def venv_ready(root: Path = HERE) -> bool:
    return venv_python(root).is_file() and (root / ".venv" / VENV_READY).is_file()


def runtime_python(root: Path = HERE) -> str:
    """跑任务时实际用哪个 Python：本目录的 .venv 装好了就用它，否则用现在这个。"""
    return str(venv_python(root)) if venv_ready(root) else sys.executable


def has_pillow(python: str) -> str:
    """这个 Python 里有没有图像库。有返回版本号，没有返回空字符串。"""
    try:
        result = subprocess.run([python, "-c", "import PIL; print(PIL.__version__)"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


# ---------------- 安装 ----------------
def ensure_files(root: Path = HERE, say=print) -> None:
    """补上空的配置文件。已有的一个字节都不动。"""
    for name, template in ((".env", ".env.example"), ("config.json", "config.example.json")):
        target, source = root / name, root / template
        if target.exists():
            say("  %s 已经有了，没有动它" % name)
            continue
        if not source.is_file():
            say("  缺少模板 %s，没法建 %s（分发包不完整，请重新解压）" % (template, name))
            continue
        shutil.copyfile(str(source), str(target))
        if os.name != "nt":
            os.chmod(str(target), stat.S_IRUSR | stat.S_IWUSR)  # 只有自己能读写
        say("  建了空的 %s，请把你自己的 key 填进去" % name)


def ensure_pillow(root: Path = HERE, say=print, runner=subprocess.run) -> None:
    """在本目录的 .venv 里装图像库（不动系统的 Python）。总是用这个 .venv：不管以后是用 python、python3 还是 py 来跑，
    run.py 都会换到它里面，用到的是同一套东西。装不成时，当前的 Python 里正好有图像库就先用当前的。"""
    python, ready = venv_python(root), root / ".venv" / VENV_READY
    if venv_ready(root) and has_pillow(str(python)):
        say("  图像库已经装在本目录的 .venv 里了")
        return
    try:
        ready.unlink()  # 要重装：先把"装好了"的记号拿掉
    except OSError:
        pass
    usable = python.is_file() and _works(runner, [str(python), "-m", "pip", "--version"])
    try:
        say("  在本目录建 .venv（不动系统的 Python）…" if not python.is_file() else "  本目录的 .venv 不完整，重建…" if not usable else "  用本目录已有的 .venv…")
        if not usable:
            runner([sys.executable, "-m", "venv", "--clear", str(root / ".venv")], check=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        say("  .venv 没建成（%s）。%s" % (type(exc).__name__, _fallback(root)))
        return
    try:
        say("  安装图像库 Pillow…")
        runner([str(python), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", str(root / "requirements.txt")],
               check=True, timeout=900)
        ready.write_text("ok\n", encoding="utf-8")
    except (OSError, subprocess.SubprocessError) as exc:
        say("  图像库没装上（%s）。%s %s" % (type(exc).__name__, MIRROR_HINT, _fallback(root)))


def _works(runner, command: list) -> bool:
    try:
        return runner(command, capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _fallback(root: Path) -> str:
    if has_pillow(sys.executable):
        return "当前的 Python 里有图像库，先用它；要用同一个 Python（%s）来运行 run.py。" % sys.executable
    return "处理好之后重新运行 install.py；一直不行就把本目录的 .venv 文件夹删掉再运行。"


def ensure_tools(root: Path = HERE, say=print, runner=subprocess.run) -> None:
    from ipr.capture import ego
    if ego.available():
        say("  找到了 EGO 浏览器，采集用它（Chrome 那套组件不用装）")
        return
    npm = shutil.which("npm")
    if (root / "tools" / "node_modules" / "playwright-core").is_dir():
        say("  Chrome 采集的组件已经有了")
    elif not npm:
        say("  没找到 EGO 浏览器，也没有 Node（npm）：装了其中一个才能从 Amazon 链接采集商品")
    else:
        say("  没找到 EGO 浏览器：安装 Chrome 采集要用的组件…")
        try:
            runner([npm, "install", "--omit=dev", "--no-audit", "--no-fund", "--loglevel=error"], cwd=str(root / "tools"), check=True, timeout=900)
        except (OSError, subprocess.SubprocessError) as exc:
            say("  组件没装上（%s）。可以稍后重跑 install.py，或者装 EGO 浏览器" % type(exc).__name__)


# ---------------- 自检 ----------------
# ---- 老版（2.x）留下的 Codex 钩子 ----
# 老版安装时在 Codex 的 hooks.json 里登记过四个钩子（开会话、发消息、停止、中断时运行它的 scripts/codex_guard.py）。
# 换成新版后那个文件没有了，钩子还在：Codex 里每发一条消息都会被它拦下并报"can't open file …codex_guard.py"。
OLD_GUARD_LABEL = "LC IPR completion guard"


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _dead_guard(handler) -> bool:
    """是不是老版登记的、而且它要运行的那个文件已经不在了的钩子。文件还在的（别处还装着老版）不碰。"""
    import re
    command = str(handler.get("command") or "") if isinstance(handler, dict) else ""
    if not isinstance(handler, dict) or handler.get("statusMessage") != OLD_GUARD_LABEL or "codex_guard.py" not in command:
        return False
    found = re.search(r'"([^"]*codex_guard\.py)"|(\S*codex_guard\.py)', command)
    script = (found.group(1) or found.group(2)) if found else ""
    return not (script and Path(script).is_file())


def stale_hooks(home: Path = None):
    """返回 (hooks.json 的内容, 失效的老版钩子个数)。没有这个文件、读不懂它，都当成 0 个，不动它。"""
    import json
    path = (home or codex_home()) / "hooks.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, 0
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return None, 0
    count = sum(1 for groups in hooks.values() if isinstance(groups, list) for group in groups
                if isinstance(group, dict) and isinstance(group.get("hooks"), list) for handler in group["hooks"] if _dead_guard(handler))
    return data, count


def ensure_no_stale_hooks(home: Path = None, say=print) -> None:
    """摘掉失效的老版钩子：先原样备份 hooks.json，只动这几条，别的钩子一个字不改。"""
    import json
    import time
    home = home or codex_home()
    data, count = stale_hooks(home)
    if not count:
        return
    path = home / "hooks.json"
    backup = path.with_name("hooks.json.ipr-backup-%s-stale" % time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    try:
        shutil.copy2(path, backup)
        for event in list(data["hooks"]):
            groups = data["hooks"][event]
            if not isinstance(groups, list):
                continue
            kept = []
            for group in groups:
                if not (isinstance(group, dict) and isinstance(group.get("hooks"), list)):
                    kept.append(group)
                    continue
                left = [handler for handler in group["hooks"] if not _dead_guard(handler)]
                if left or not group["hooks"]:
                    kept.append(dict(group, hooks=left))
            if kept:
                data["hooks"][event] = kept
            else:
                data["hooks"].pop(event)
        temp = path.with_name("hooks.json.ipr-tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
    except OSError as exc:
        say("  老版留下的 %d 个 Codex 钩子没能摘掉（%s）：请手动打开 %s 删掉带 codex_guard.py 的那几条" % (count, type(exc).__name__, path))
        return
    say("  摘掉了老版留下的 %d 个 Codex 钩子（它们要运行的 codex_guard.py 已经不在了，留着会把 Codex 里的每条消息都拦下）；原文件备份在 %s"
        % (count, backup.name))
    say("  已经开着的 Codex 要重开一次才生效")


def check_hooks() -> list:
    _data, count = stale_hooks()
    if not count:
        return []
    return [(BAD, "老版留下的 Codex 钩子", "还有 %d 个：它们要运行的 codex_guard.py 已经不在了，Codex 里发消息会被拦下。运行 %s install.py（不带 --check）会摘掉"
             % (count, PYTHON_NAME))]


def check_python() -> tuple:
    version = "%d.%d.%d" % sys.version_info[:3]
    if sys.version_info < (3, 9):
        return BAD, "Python 版本", "现在是 %s，需要 3.9 或更新的。到 python.org 装一个新的再运行" % version
    return OK, "Python 版本", version


def check_pillow(root: Path = HERE) -> tuple:
    version = has_pillow(runtime_python(root))
    if version:
        return OK, "图像库 Pillow", "%s（%s）" % (version, "本目录的 .venv" if venv_ready(root) else "当前的 Python")
    return BAD, "图像库 Pillow", "没装上：外观专利要拼图给 AI 看，少了它外观查不了。重新运行 install.py。" + MIRROR_HINT


def check_codex(runner=subprocess.run) -> tuple:
    from ipr import ai
    from ipr.outcome import StepFailed
    try:
        binary = ai.find_codex()
    except StepFailed as exc:
        return BAD, "Codex", exc.message
    try:
        version = runner([binary, "--version"], capture_output=True, text=True, timeout=30)
        status = runner([binary, "login", "status"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return BAD, "Codex", "找到了 codex 但运行不了（%s）。在终端里直接运行 codex 看看报什么" % type(exc).__name__
    said = [line.strip() for line in ((status.stdout or "") + "\n" + (status.stderr or "")).splitlines() if line.strip()]
    logged = next((line for line in said if line.lower().startswith("logged in")), "")
    if status.returncode != 0 or not logged:
        return BAD, "Codex", "还没有登录。在终端里运行 codex login，用 ChatGPT 账号登录后再自检"
    if "chatgpt" not in logged.lower():  # AI 会话走的是 ChatGPT 订阅额度，用 API key 登录的用不了
        return BAD, "Codex", "现在不是用 ChatGPT 账号登录的（%s）。运行 codex logout 再 codex login，选 ChatGPT 账号" % logged[:40]
    return OK, "Codex", "%s，%s" % ((version.stdout or version.stderr or "").strip()[:40], logged[:60])


def check_browser() -> tuple:
    from ipr.capture import chrome, ego
    if ego.available():
        return OK, "采集用的浏览器", "EGO 浏览器"
    if chrome.available():
        if chrome_installed():
            return OK, "采集用的浏览器", "Chrome（没装 EGO 浏览器时用它）"
        return BAD, "采集用的浏览器", "采集组件装好了，但没找到 Chrome 浏览器。装上 Google Chrome，或者装 EGO 浏览器（并完成首次引导）"
    return BAD, "采集用的浏览器", ("EGO 浏览器和 Chrome 采集组件都没有：装好 EGO 浏览器（并完成首次引导），或者装 Node 和 Chrome 后重新运行 install.py。"
                             "装好之前只能用「自己传资料」的入口")


def chrome_installed() -> bool:
    """按系统的常见安装位置找 Google Chrome。"""
    if sys.platform == "darwin":
        places = [Path("/Applications/Google Chrome.app")]  # 采集组件只认装在这里的
    elif ON_WINDOWS:
        places = [Path(os.environ[name]) / "Google" / "Chrome" / "Application" / "chrome.exe"
                  for name in ("PROGRAMW6432", "PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA") if os.environ.get(name)]
    else:
        return bool(shutil.which("google-chrome") or shutil.which("google-chrome-stable"))
    return any(place.exists() for place in places)


def check_auth(root: Path = HERE) -> tuple:
    from ipr import auth
    try:
        auth.require(root)
    except auth.AuthFailed as exc:
        hint = ""
        if exc.reason == "missing_token":
            hint = "把后台 token 填进本目录 config.json 的 backend_token"
        elif exc.reason == "configuration_error" and not (root / "config.json").exists():
            hint = "本目录没有 config.json：重新运行 install.py 会补一个空的，再把后台 token 填进去"
        elif exc.reason == "configuration_error":
            hint = "本目录的 config.json 写坏了（要保持 {\"backend_url\": \"…\", \"backend_token\": \"…\"} 这个样子，引号和逗号都是英文的）"
        elif ON_WINDOWS and exc.reason.startswith("auth_component"):
            hint = "Windows 把鉴权程序拦下时，在本目录的 PowerShell 里运行 Unblock-File tools\\bin\\*.exe 再自检"
        return BAD, "后台鉴权", "%s%s" % (exc.message.rstrip("。"), "。" + hint if hint else "")
    except Exception as exc:
        return BAD, "后台鉴权", "检查时出错（%s）" % type(exc).__name__
    return OK, "后台鉴权", "通过"


def check_keys(env: dict) -> list:
    """各数据源的 key：填了的顺便看一眼余量（这几个查询都不计次）；没填的说明少了哪一路。"""
    from ipr.sources import serpapi, serper, signa
    rows = []
    plan = (("SERPAPI_API_KEY", "SerpApi", serpapi.remaining, "次", "美国单的外观少一路辅助来源（美国专利局那一路照查）；美国以外的专利和外观不查，会写未检索"),
            ("SERPER_API_KEY", "Serper", serper.balance, "点", "不做以图搜图、不查维权报道，版权图案这一类会写未检索"),
            ("SIGNA_API_KEY", "Signa", signa.credits, "点", "商标不查，这一类会写未检索"))
    for name, label, probe, unit, missing in plan:
        key = env.get(name) or ""
        if not key:
            rows.append((WARN, "%s 的 key" % label, "没填：%s。填在本目录的 .env 里" % missing))
            continue
        try:
            left = probe(key)
        except Exception:
            left = -1
        if left < 0:
            rows.append((BAD, "%s 的 key" % label, "填了，但查不到余量：key 可能不对，或者连不上 %s" % label))
        elif left == 0:
            rows.append((WARN, "%s 的 key" % label, "余量是 0：%s" % missing))
        else:
            rows.append((OK, "%s 的 key" % label, "还剩 %d %s" % (left, unit)))
    if env.get("EUIPO_CLIENT_ID") and env.get("EUIPO_CLIENT_SECRET"):
        rows.append((OK, "欧盟知识产权局的账号", "填了（法、德、意、西的单子用它查欧盟外观并取图）"))
    else:
        rows.append((WARN, "欧盟知识产权局的账号", "没填：只影响法、德、意、西的单子，欧盟外观只能列名单、没法看图比对。"
                     "账号在 dev.euipo.europa.eu 免费申请，填在本目录 .env 的 EUIPO_CLIENT_ID 和 EUIPO_CLIENT_SECRET"))
    return rows


def check_network() -> list:
    from ipr.sources import http, ppubs
    rows = []
    try:
        ppubs.Session().open()
        rows.append((OK, "连美国专利局", "通"))
    except Exception as exc:
        rows.append((BAD, "连美国专利局", "不通（%s）。检查网络或代理后再自检" % str(getattr(exc, "message", type(exc).__name__))[:80]))
    try:
        status, _headers, _raw = http.fetch("https://patents.google.com/patent/US10633217B2/en", timeout=30, max_bytes=0)
        rows.append((OK, "连 Google Patents", "通") if status == 200 else (BAD, "连 Google Patents", "返回状态码 %d。检查网络或代理后再自检" % status))
    except Exception as exc:
        rows.append((BAD, "连 Google Patents", "不通（%s）。检查网络或代理后再自检" % str(getattr(exc, "message", type(exc).__name__))[:80]))
    return rows


def check_runs_dir() -> tuple:
    from ipr import config
    try:
        config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        probe = config.RUNS_DIR / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return BAD, "任务目录", "%s 写不进去（%s）" % (config.RUNS_DIR, type(exc).__name__)
    return OK, "任务目录", str(config.RUNS_DIR)


def self_check(root: Path = HERE, say=print) -> int:
    """逐项自检并打印。返回没通过的项数（[提醒] 不算没通过）。"""
    from ipr import config
    try:
        env = config.load_env(root / ".env")
    except Exception:
        env = {}
    config.set_secrets(env)  # 下面打印的每一行都会把这些 key 抹掉
    rows = []
    for name, check in (("Python 版本", check_python), ("图像库 Pillow", lambda: check_pillow(root)), ("Codex", check_codex), ("老版留下的 Codex 钩子", check_hooks),
                        ("采集用的浏览器", check_browser), ("后台鉴权", lambda: check_auth(root)), ("各数据源的 key", lambda: check_keys(env)),
                        ("网络", check_network), ("任务目录", check_runs_dir)):
        try:  # 哪一项检查自己出了意料之外的错，只算这一项没过，别的照常查，最后照样给结论
            found = check()
        except Exception as exc:
            found = (BAD, name, "检查这一项时程序出错（%s）" % type(exc).__name__)
        rows += found if isinstance(found, list) else [found]
    say("\n自检：")
    for state, name, detail in rows:
        say("  %s %s：%s" % (MARKS[state], name, config.redact(detail)))
    failed = sum(1 for state, _name, _detail in rows if state == BAD)
    warned = sum(1 for state, _name, _detail in rows if state == WARN)
    if failed:
        say("\n自检结果：有 %d 项没通过（上面标着 [没过] 的），处理完再运行一次 %s install.py --check" % (failed, PYTHON_NAME))
    elif warned:
        say("\n自检结果：可以用了。有 %d 项提醒（上面标着 [提醒] 的）：对应的那一路不查，报告里会写明" % warned)
    else:
        say("\n自检结果：全部通过，可以开始查了")
    return failed


def main(argv=None) -> int:
    from ipr import config
    config.setup_streams()
    parser = argparse.ArgumentParser(description="侵权风险快查：安装和自检")
    parser.add_argument("--check", action="store_true", help="只自检，不安装")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 9):
        print("需要 Python 3.9 或更新的（现在是 %d.%d）。到 python.org 装一个新的再运行。" % sys.version_info[:2])
        return 1
    if not args.check:
        print("安装：")
        ensure_files()
        ensure_pillow()
        ensure_tools()
        ensure_no_stale_hooks()
    return 1 if self_check() else 0


if __name__ == "__main__":
    sys.exit(main())
