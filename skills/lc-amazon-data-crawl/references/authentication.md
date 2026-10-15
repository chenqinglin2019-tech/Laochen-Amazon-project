# 云端鉴权与接收者安装

## 保持不变的边界

保留四个平台的原生 `lc-auth-check-*` 二进制、默认 backend_url 和 `/public/account` 请求／响应协议。未改变账户准入判定、采集规则、判断阈值、限速或休息。`check_auth.sh` / `check_auth.ps1` 继续处理组件准备，随后调用同一 `auth_runtime.py`；该入口只需 Python 3.8+ 标准库。Windows 优先使用 `py -3`，再尝试 python/python3，不要求先装采集依赖。

## 凭据来源

公开包的 config.json 保持 token 为空；用户的凭据只写忽略提交的 config.local.json。读取两者时按 token 内容决定来源：空／null／纯空格的本地 token 不遮住旧公开 token，也不改变其 endpoint；只有本地 token 时可继承公开 backend_url。两个非空 token 相同可用，不同则明确报告配置冲突，禁止静默猜测账户或在拒绝后回退另一个 token。损坏的 JSON、非字符串 token 和控制字符单独报告配置错误。

`configure_credentials.py` 从 stdin 接收 JSON：backend_token 必填，backend_url 可选。它原子写入私有配置，并清除公开配置中的旧 token，保留双方其他字段；Unix 文件权限 0600，拒绝符号链接，不回显值。显式替换允许修复损坏的本地 JSON；第二次写入失败时尝试回滚第一次写入，不报告假成功。不要通过 argv、shell 文本、临时脚本或 Git 传递真实 token。

安装器首次缺 token 时隐藏提示输入；替换已有 token 需 --replace-token（bash）或 -ReplaceToken（PowerShell）。用户主动在对话提供 token 时，由代理用安全 stdin 写入入口，再执行原门禁与 runner 更新，而不是修改公开模板后让旧覆盖继续生效。

## Runner 更新

setup_runner 首先验证 Skill 当前有效凭据，成功后同步 backend_url/backend_token 至指定 runner 的私有配置，并清空 runner 旧公开 token。只同步云端鉴权字段，任务配置、输入、输出、模型 API key 均保留。源鉴权失败不更新 runner 凭据；不同 runner 只有在被明确指定更新时才改变。用户提供新 token 后，应完成 configure → Skill check_auth → setup_runner → runner check_auth 的全链路，再恢复采集。

安装器通过后设置进程内时间及凭据指纹，setup/install/doctor 最多复用 10 分钟；指纹只含有效 backend_url/token 的单向摘要，无 token 原文，不持久化或输出到报告。凭据变化或记录过期重新鉴权。正式采集不使用此复用。setup 安装外仍重新鉴权。

## 安全失败与恢复

保留退出码 0 成功、2 工具缺失、3 本地启动失败、4 配置或云端鉴权失败。云端／配置失败输出固定两行：原停止提示＋脱敏原因，区分缺 token、配置冲突、账户拒绝／未启用、429、连接／5xx、请求超时、404、返回格式异常。机器码按白名单映射，未知码仅报固定原因，不展示原始正文、异常文本或凭据。最多等待现有检查器一次调用（20 秒外部上限），不新增鉴权自动重试，也不降低 TLS 或账户要求。

网络或服务不可用不能证明 token 无效；明确账户拒绝也不自动换用另一份凭据。根据原因修复配置或网络后重新执行原入口。鉴权通过不等于第三方模型 API key 已配置，二者不能互相替代。

## 验证范围

tests/test_auth_runtime.py 覆盖空覆盖、非空冲突、partial override、BOM、替换、回滚、权限、runner 轮换、错误脱敏与安装缓存。macOS 使用原二进制、合成 token 和只允许 loopback 的沙盒，验证首次安装、显式替换、源鉴权失败保护及 runner 业务入口；不访问真实账户或平台。PowerShell 脚本可在 pwsh 下运行同类安装／轮换链路；在 macOS 上通过并不等于 Windows 原生二进制／ACL 已实测。发布前还需全量离线回归、凭据扫描与原生二进制哈希核对。
