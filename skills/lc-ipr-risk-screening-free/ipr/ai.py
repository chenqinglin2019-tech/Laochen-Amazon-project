"""真实的 AI 会话：用 `codex exec` 开一个不带任何工具的子会话，走 ChatGPT 订阅额度。

- 模型按档位选（config.MODEL_TIERS），不用最贵的那档；
- 回答按给定格式返回（--output-schema），用量从事件流里取；
- 被限流就等一等再试；额度用尽立刻抛 QuotaExhausted，由流水线收场；其他失败自动重试一次；
- 本机所有会话共用并发名额（沿用老版的 model_slots，两单同时跑也不会互相挤爆）。
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import config, faults, model_slots
from . import images as image_tools
from .outcome import QuotaExhausted, StepFailed

# 子会话里关掉的功能：不给工具、不加载插件和技能，既安全也省固定开销（沿用老版清单）。
DISABLED_FEATURES = ("shell_snapshot", "shell_tool", "unified_exec", "code_mode_host", "code_mode", "code_mode_only",
                     "plugins", "remote_plugin", "skill_search", "skill_mcp_dependency_install", "apps",
                     "unbounded_connection_retries",
                     # 下面这些是 2026-11-26 在 codex-cli 0.172.0 上实测加的：连同精简指令，
                     # 每个会话的固定开销从约 1.7 万（luna）/ 2.2 万（sol）降到约 1.2 万 / 1.6 万 token。
                     "browser_use", "browser_use_external", "browser_use_full_cdp_access", "computer_use", "goals",
                     "image_generation", "sleep_tool", "tool_suggest", "view_image", "hooks", "in_app_browser",
                     "in_app_local_automation", "workspace_dependencies", "worktrees", "realtime_conversation")
INSTRUCTIONS_FILE = Path(__file__).resolve().parent / "data" / "ai_instructions.md"  # 用一句话的指令换掉 Codex 自带的长指令
PROVIDER = {  # 沿用老版：走 HTTPS、不用长连接、不让 CLI 自己悄悄重试
    "model_provider": "ipr_chatgpt_https",
    "model_providers.ipr_chatgpt_https.name": "ChatGPT HTTPS",
    "model_providers.ipr_chatgpt_https.base_url": "https://chatgpt.com/backend-api/codex",
    "model_providers.ipr_chatgpt_https.wire_api": "responses",
    "model_providers.ipr_chatgpt_https.requires_openai_auth": True,
    "model_providers.ipr_chatgpt_https.supports_websockets": False,
    "model_providers.ipr_chatgpt_https.request_max_retries": 0,
    "model_providers.ipr_chatgpt_https.stream_max_retries": 0,
    "model_providers.ipr_chatgpt_https.stream_idle_timeout_ms": 600000,
    "suppress_unstable_features_warning": True,
}
QUOTA_TEXT = re.compile(r"usage limit|insufficient_quota|quota", re.I)  # 用在会话返回的错误事件上
STDERR_QUOTA = re.compile(r"usage limit|insufficient_quota|quota exceeded|exceeded your (current )?quota", re.I)  # 标准错误里杂音多，认得窄一些
RESUME_AT = re.compile(r"try again (?:at|in) ([^.\n]+)", re.I)


CODEX_ENV = "LC_IPR_CODEX_BINARY"  # 找不到时用它指定 Codex 程序的完整路径
ON_WINDOWS = os.name == "nt"


def native_codex(wrapper: str) -> str:
    """Windows 上用 npm 装的 Codex 只有一个 codex.cmd 包装脚本：经它传带引号的参数会被 cmd 改坏，
    所以到它旁边的 node_modules/@openai/codex 里找真正的 codex.exe。找不到返回空字符串。"""
    base = Path(wrapper).resolve().parent / "node_modules" / "@openai"
    try:
        found = sorted(path for path in base.glob("codex*/**/codex.exe") if path.is_file())
    except OSError:
        found = []
    wanted = "aarch64" if "arm" in platform.machine().lower() else "x86_64"  # 装了不止一个平台的包时，取和这台电脑对得上的
    found.sort(key=lambda path: 0 if wanted in str(path) else 1)
    return str(found[0]) if found else ""


def find_codex() -> str:
    given = os.environ.get(CODEX_ENV, "").strip().strip('"')
    if given:
        if Path(given).is_file():
            return given
        raise StepFailed("环境变量 %s 指的 Codex 程序不存在。" % CODEX_ENV)
    path = shutil.which("codex")
    if not path:
        raise StepFailed("找不到 codex 命令。请确认 Codex 已安装并且在这个终端里能直接运行 codex。")
    if ON_WINDOWS and Path(path).suffix.lower() != ".exe":  # .cmd、.ps1，或者没有后缀的包装脚本
        native = native_codex(path)
        if not native:
            raise StepFailed("找到了 codex.cmd，但没找到它包里的 codex.exe。请把 codex.exe 的完整路径设到环境变量 %s 里。" % CODEX_ENV)
        return native
    return path


def build_command(binary: str, model: str, effort: str, workspace: Path, schema_file: Path = None, image_files=()) -> list:
    command = [binary, "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check",
               "--json", "--sandbox", "read-only"]
    for feature in DISABLED_FEATURES:
        command += ["--disable", feature]
    command += ["--enable", "skip_host_skill_discovery"]
    settings = dict(PROVIDER, model=model, model_reasoning_effort=effort, model_instructions_file=str(INSTRUCTIONS_FILE))
    for key, value in settings.items():
        command += ["-c", "%s=%s" % (key, json.dumps(value))]
    command += ["-c", "mcp_servers={}"]
    if schema_file:
        command += ["--output-schema", str(schema_file)]
    for image in image_files:
        command += ["--image", str(image)]
    return command + ["-C", str(workspace), "-"]


def parse_events(stdout: str) -> dict:
    """从事件流里取：最后一段回答、用量、错误说明。"""
    answer, usage, errors = "", None, []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        if kind == "item.completed" and item.get("type") == "agent_message" and isinstance(item.get("text"), str) and item["text"]:
            answer = item["text"]
        elif kind == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = event["usage"]
        elif kind == "error" and event.get("message"):
            errors.append(str(event["message"]))
        elif kind == "turn.failed":
            error = event.get("error")
            errors.append(str((error.get("message") if isinstance(error, dict) else error) or "turn failed"))
    return {"answer": answer, "usage": usage, "errors": errors}


def parse_answer(text: str) -> dict:
    """回答应该是一个 JSON 对象；外面包了说明文字或代码块时取最外层的大括号。"""
    text = (text or "").strip()
    for candidate in (text, text[text.find("{"):text.rfind("}") + 1] if "{" in text and "}" in text else ""):
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise StepFailed("AI 的回答不是约定的格式")


class LiveAI:
    def __init__(self, task_dir: Path, usage, env=None, runner=subprocess.run, sleep=time.sleep):
        self.task_dir = Path(task_dir)
        self.usage = usage
        self.env = env or {}
        self.runner = runner
        self.sleep = sleep
        self._binary = None

    def ask(self, step: str, key: str, prompt: str = None, images=(), schema: dict = None, tier: str = "light",
            timeout: int = None, image_max_px: int = None) -> dict:
        if not prompt:
            raise StepFailed("这一步的提示词还没有写（%s）" % key)
        pretend = faults.ai_quota(key)
        if pretend:  # 测试开关：演练额度用尽
            raise QuotaExhausted("AI 额度用尽了，后面需要 AI 的步骤先不做。", resume_at=pretend)
        tier_settings = config.MODEL_TIERS[tier]
        session_dir = self.task_dir / "sessions" / re.sub(r"[^A-Za-z0-9_\-]+", "_", key)
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "prompt.txt").write_text(config.mask_secrets(prompt), encoding="utf-8")
        last_error = ""
        rate_attempt = 0
        tries = 0
        while tries < 2:  # 普通失败自动重试一次；被限流的等待不算在这两次里
            tries += 1
            started = time.monotonic()
            outcome = self._run_once(session_dir, prompt, images, schema, tier_settings, timeout or config.AI_TIMEOUT_SECONDS,
                                     image_max_px or config.AI_IMAGE_MAX_PX)
            seconds = time.monotonic() - started
            parsed, failure = outcome["parsed"], outcome["failure"]
            trace = outcome["stdout"]
            if QUOTA_TEXT.search(" ".join(parsed["errors"])):
                self.usage.add_session(step, key, tier_settings["model"], seconds, parsed["usage"], ok=False)
                message = " ".join(parsed["errors"])
                resume = RESUME_AT.search(message)
                raise QuotaExhausted("AI 额度用尽了，后面需要 AI 的步骤先不做。", resume_at=resume.group(1).strip() if resume else "")
            if not parsed["answer"] and model_slots.rate_limited(trace) and rate_attempt < model_slots.MAX_RATE_LIMIT_RETRIES:
                self.usage.add_session(step, key, tier_settings["model"], seconds, parsed["usage"], ok=False)
                self.sleep(model_slots.note_rate_limit(rate_attempt))
                rate_attempt += 1
                tries -= 1
                continue
            if not failure:
                try:
                    answer = parse_answer(parsed["answer"])
                except StepFailed as exc:
                    failure = exc.message
                else:
                    self.usage.add_session(step, key, tier_settings["model"], seconds, parsed["usage"], ok=True)
                    (session_dir / "answer.json").write_text(config.mask_secrets(json.dumps(answer, ensure_ascii=False, indent=1)),
                                                             encoding="utf-8")
                    return answer
            self.usage.add_session(step, key, tier_settings["model"], seconds, parsed["usage"], ok=False)
            last_error = failure
        raise StepFailed("AI 会话两次都没成：%s" % last_error)

    def _run_once(self, session_dir: Path, prompt: str, images, schema, tier_settings: dict, timeout: int, image_max_px: int) -> dict:
        if self._binary is None:
            self._binary = find_codex()
        with tempfile.TemporaryDirectory(prefix="ipr-ai-") as temp:
            workspace = Path(temp)
            attached = image_tools.prepare(images, workspace, image_max_px)
            schema_file = None
            if schema:
                schema_file = workspace / "schema.json"
                schema_file.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
            command = build_command(self._binary, tier_settings["model"], tier_settings["effort"], workspace, schema_file, attached)
            failure, stdout, stderr = "", "", ""
            try:
                with model_slots.slot():
                    result = self.runner(command, input=prompt, text=True, encoding="utf-8", errors="replace",
                                         capture_output=True, timeout=timeout, env=config.child_env())
                stdout, stderr = result.stdout or "", result.stderr or ""
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
                failure = "超过 %d 秒没有答完" % timeout
            except (OSError, ValueError) as exc:
                failure = "会话没能启动（%s）" % type(exc).__name__
        (session_dir / "events.jsonl").write_text(config.mask_secrets(stdout), encoding="utf-8")
        parsed = parse_events(stdout)
        if not parsed["answer"]:  # 有的版本只把"额度用尽"写在标准错误里：把命中的那几行也算作错误说明
            parsed["errors"] += [line.strip() for line in (stderr or "").splitlines() if STDERR_QUOTA.search(line)]
        if not failure and not parsed["answer"]:
            detail = "；".join(parsed["errors"]) or (stderr.strip().splitlines() or ["没有任何回答"])[-1]
            failure = "没有拿到回答（%s）" % detail[:200]
        return {"parsed": parsed, "failure": failure, "stdout": stdout}
