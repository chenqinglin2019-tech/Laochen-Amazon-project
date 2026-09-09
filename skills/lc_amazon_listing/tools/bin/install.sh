#!/bin/sh
# 可选的旧安装入口；正常调用 backend_cli.py 时已自动准备当前平台 CLI。
# 复用统一准备逻辑，不递归改变其他文件，不读取鉴权配置、不调用后端。
set -eu
listing_installer_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 - "$listing_installer_dir/../../scripts/backend_cli.py" <<'PY'
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("listing_backend_installer", sys.argv[1])
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
try:
    backend.prepare_cli(backend.select_cli())
except backend.BackendError as error:
    print("CLI 准备失败：" + error.code, file=sys.stderr)
    sys.exit(1)
print("当前平台 CLI 已准备，可通过 backend_cli.py 使用。")
PY
