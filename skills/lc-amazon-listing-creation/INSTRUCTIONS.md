# Lc Amazon Listing Creation 启动鉴权

本文件只规定第一步老陈云端鉴权。鉴权通过后，严格按 `SKILL.md` 执行原有 Amazon 库存模板流程，不改变任何业务规则。

## 强制第一步

每次调用本 Skill，必须先进入 Skill 根目录并执行当前平台的鉴权命令。鉴权之前不得读取或处理用户业务输入、创建项目目录、扫描模板库、运行 `scripts/` 下的业务脚本或写入业务文件。

### Linux x64

```bash
chmod +x tools/bin/lc-listing-creation-auth-check-linux-amd64
./tools/bin/lc-listing-creation-auth-check-linux-amd64
```

### macOS Intel

```bash
xattr -dr com.apple.quarantine tools/bin/ 2>/dev/null || true
chmod +x tools/bin/lc-listing-creation-auth-check-darwin-amd64
./tools/bin/lc-listing-creation-auth-check-darwin-amd64
```

### macOS Apple Silicon

```bash
xattr -dr com.apple.quarantine tools/bin/ 2>/dev/null || true
chmod +x tools/bin/lc-listing-creation-auth-check-darwin-arm64
./tools/bin/lc-listing-creation-auth-check-darwin-arm64
```

### Windows x64

```powershell
.\tools\bin\lc-listing-creation-auth-check-windows-amd64.exe
```

鉴权器固定使用 `skill_id=amazon_listing_creation` 调用 `/auth/skill-check`。它只查询账户状态、余额和该 Skill 的用户权限，不扣除业务积分。

## Token 读取顺序

1. 当前进程已有 `LAOCHEN_BACKEND_TOKEN` 时直接使用。
2. 否则读取 Skill 根目录 `config.json` 的 `backend_token`，兼容旧的手工配置方式。
3. 两处都没有 Token 时鉴权失败。

不得把完整 Token 写入命令行、任务目录、日志、报告或回复，不得将 Token 写死进 Skill 文件。

## 结果处理

成功输出：

```json
{"message":"auth_passed","ok":true}
```

看到 `auth_passed` 后，立即回到 `SKILL.md` 的原有流程继续，不再重复鉴权。

失败时，鉴权器输出一条不含 Token 的安全原因码。Agent 必须用中文明确告知用户原因并停止本轮，不能继续原有业务流程：

| 原因码 | 告知用户 |
| --- | --- |
| `missing_token` | 未配置访问 Token。 |
| `invalid_token` | Token 无效或无权访问。 |
| `user_disabled` | 账户已停用。 |
| `insufficient_balance` | 账户余额不足。 |
| `unknown_skill` / `skill_disabled` | 该 Skill 尚未登记或已停用。 |
| `permission_disabled` / `permission_missing` | 当前用户未开通该 Skill 权限。 |
| `rate_limited` | 鉴权服务请求过于频繁，请稍后再试。 |
| `service_unavailable` | 鉴权服务暂时不可用，请稍后再试。 |
| `invalid_response` / `configuration_error` / `auth_failed` | 鉴权组件返回异常或配置无效。 |

此门禁约束官方分发包的正常执行流程，不是不可绕过的 DRM。
