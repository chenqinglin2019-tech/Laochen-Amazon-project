"""Fixed-tab OpenCLI bridge. Never opens, selects, closes or recreates a tab."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from run_outcome import CrawlStop, needs_human


def decode_json(text: str) -> Any:
    # OpenCLI may print an update notice before/after its JSON response.
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char in "[{":
            try:
                return decoder.raw_decode(text[index:])[0]
            except ValueError:
                continue
    raise ValueError("OpenCLI 未返回 JSON")


def cli_command() -> list[str]:
    executable = shutil.which("opencli")
    if not executable:
        raise needs_human("未找到 OpenCLI。请安装 OpenCLI CLI 和日常 Chrome 的 Browser Bridge 扩展。")
    if executable.lower().endswith((".cmd", ".bat")):
        # Do not send JavaScript or user input through cmd.exe quoting.
        entry = Path(executable).parent / "node_modules/@jackwener/opencli/dist/src/main.js"
        node = shutil.which("node")
        if not node or not entry.is_file():
            raise needs_human("无法定位 OpenCLI 的 Node 入口，请修复 npm 全局安装；不会调用 cmd.exe 执行页面代码。")
        return [node, str(entry)]
    return [executable]


class BridgeTransientError(CrawlStop):
    """A coded transport failure; only read-only callers may retry it."""
    def __init__(self, code: str):
        self.bridge_code = code
        super().__init__(f"OpenCLI 暂时无法读取原工作标签（{code}）。", exit_code=30)


TRANSIENT_CODES = {"client_timeout", "target_navigated", "detached_mid_command", "cdp_timeout", "attach_failed"}


def raise_transient(result):
    error = result.get("error") if isinstance(result, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    if isinstance(code, str) and code in TRANSIENT_CODES:
        raise BridgeTransientError(code)


class OpenCliBridge:
    def __init__(self, session: str, target: str = "", *, command: Optional[list[str]] = None):
        self.session = session
        self.target = target
        self.command = command if command is not None else cli_command()
        self.expected_url = ""
        self.document_id = ""
        self.script = Path(__file__).with_name("sellersprite_panel.js").read_text(encoding="utf-8")

    def call(self, args: list[str], *, targeted: bool = True, timeout: float = 35,
             allow_error: bool = False) -> Any:
        if targeted and not self.target:
            raise needs_human("尚未绑定工作标签，已停止；请先选好日常 Chrome 工作页。")
        argv = self.command + ["browser", self.session] + args
        if targeted:
            argv += ["--tab", self.target]
        env = dict(os.environ, OPENCLI_WINDOW="background", NO_COLOR="1")
        deadline = getattr(self, "read_deadline", None)
        if deadline is not None:
            timeout = min(timeout, max(0.001, deadline - time.monotonic()))
        try:
            process = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                                     env=env, timeout=timeout, check=False)
            result = decode_json(process.stdout)
        except subprocess.TimeoutExpired as exc:
            raise BridgeTransientError("client_timeout") from exc
        except (OSError, ValueError) as exc:
            raise needs_human("OpenCLI 连接中断或响应无法识别；未自动重新绑定、建页或切换窗口。") from exc
        if process.returncode or (isinstance(result, dict) and result.get("error")):
            raise_transient(result)
            if allow_error:
                return result
            # Avoid printing arbitrary page content / provider responses as an error.
            error = result.get("error", {}) if isinstance(result, dict) else {}
            code = error.get("code", "bridge_error") if isinstance(error, dict) else "bridge_error"
            raise needs_human(f"OpenCLI 操作失败（{code}）；请检查原工作标签，未自动重建连接。")
        return result

    def tabs(self) -> list[dict]:
        rows = self.call(["tab", "list"], targeted=False)
        if not isinstance(rows, list):
            raise needs_human("无法确认 OpenCLI 工作标签。")
        return rows

    def bind(self) -> dict:
        self.call(["bind"], targeted=False)
        rows = self.tabs()
        # A newly bound lease must contain exactly one page. Never guess among tabs.
        if len(rows) != 1 or not rows[0].get("page"):
            raise needs_human("绑定结果不唯一，请选好一个工作标签后重新运行。")
        self.target = rows[0]["page"]
        return rows[0]

    def validate_target(self) -> dict:
        matches = [row for row in self.tabs() if row.get("page") == self.target]
        if len(matches) != 1:
            raise needs_human("原工作标签已关闭或失联；未自动绑定其他标签。重新运行时请准备工作页。")
        return matches[0]

    def evaluate(self, expression: str) -> Any:
        return self.call(["eval", expression], allow_error=True)

    def dom(self, script: str, arguments: dict) -> dict:
        """Execute one public DOM module on the already-bound target."""
        result = self.evaluate(f"JSON.stringify(({script})({json.dumps(arguments, ensure_ascii=False)}))")
        if isinstance(result, str):
            result = json.loads(result)
        if not isinstance(result, dict) or result.get("error"):
            error = result.get("error") if isinstance(result, dict) else None
            known = {"工作页网址已变化", "工作页已刷新或被替换", "卖家精灵容器不唯一"}
            code = error.get("code", "") if isinstance(error, dict) else ""
            raise_transient(result)
            safe_code = code if isinstance(code, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", code) else ""
            detail = error if isinstance(error, str) and error in known else (safe_code or "Bridge 返回值异常")
            stop = needs_human(f"工作标签 DOM 检查失败（{detail}，action={arguments.get('action', 'unknown')}）；请核对原页面，未切换或重新绑定其他标签。")
            if isinstance(error, str) and error in known and isinstance(result.get('page_identity'), dict):
                stop.page_identity = {k: str(result['page_identity'].get(k, ''))[:2048] for k in
                                      ('expected_url', 'actual_url', 'expected_document', 'actual_document', 'dom_asin')}
            raise stop
        return result

    def panel(self, action: str = "snapshot", **arguments: Any) -> dict:
        payload = {"action": action, "expectedUrl": self.expected_url,
                   "documentId": self.document_id, **arguments}
        result = self.evaluate(f"JSON.stringify(({self.script})({json.dumps(payload, ensure_ascii=False)}))")
        if isinstance(result, str):
            result = json.loads(result)
        if not isinstance(result, dict):
            raise needs_human("卖家精灵 DOM 返回值无法识别。")
        if result.get("error"):
            raise_transient(result)
            error = result["error"]
            known = {"工作页网址已变化", "工作页已刷新或被替换", "卖家精灵容器不唯一"}
            detail = error if isinstance(error, str) and error in known else "Bridge 返回值异常"
            raise needs_human(f"卖家精灵界面检查失败：{detail}（action={action}）")
        return result

    def navigate(self, url: str) -> None:
        # The CLI's `open` retries stale targets by creating new pages. Do not use it.
        self.panel("navigate", url=url)
        self.expected_url = ""
        self.document_id = ""

    def wait_download(self, pattern: str, timeout_ms: int = 5000) -> dict:
        result = self.call(["wait", "download", pattern, "--timeout", str(timeout_ms)],
                           timeout=min(timeout_ms / 1000 + 20, 35), allow_error=True)
        return result.get("download", result)
