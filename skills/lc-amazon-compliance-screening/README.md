# 禁限售合规排查 · 授权标准版

版本：`1.2.4`。用于单个商品、选品表格及多站点合规初筛，需在支持 Skill 和本地脚本执行的 AI 工具中使用。

## 安装与授权

1. 解压后，将整个 `lc-amazon-compliance-screening` 文件夹放入所用 AI 工具的 Skill 目录，保留所有文件。
2. 准备 Python 3.9 或以上版本；处理 Excel 还需要 `openpyxl>=3.1,<4`。具体步骤见 [安装说明](references/installation.md)。
3. 使用用户自己的老陈访问 Token：设置环境变量 `LAOCHEN_BACKEND_TOKEN`，或在技能根目录自行创建私有 `config.local.json`，填写 `backend_token`。不要把 Token 发到聊天、命令行参数或报告中，也不要把填写过 Token 的文件夹转发他人。
4. 让 AI 读取 [SKILL.md](SKILL.md)，按要求先运行授权检查，再处理商品资料。

本包不含任何用户 Token。需要账户已启用、余额大于零，并拥有 `amazon_compliance_screening` 权限；授权检查不扣积分。生产授权目录已开通，具体能否使用以当前账户授权为准，管理员关闭的权限不会因重复迁移重新开启。

每条业务命令都会重新检查云端授权；缺少 Token、无权限、账户停用、余额为零、断网或授权服务异常时停止。详细配置见 [INSTRUCTIONS.md](INSTRUCTIONS.md)。帮助和离线自检不代表授权通过。

## 使用

向 AI 提供商品标题、卖点、链接或选品表格，并说明目标站点。例如：“使用禁限售合规排查，检查这张选品表中的商品，并在表格后追加判断结果。”

输入文件和输出报告放在 Skill 文件夹之外，保留原始文件。该工具提供合规初筛；具体限制及人工复核要求见 SKILL.md。

## 平台与验证范围

随包包含 macOS Apple Silicon、macOS Intel、Linux x64、Windows x64 的鉴权程序。macOS Apple Silicon 已实际运行验证，其他平台已交叉编译，待实机验证。

1.2.4 将内部超时和二进制摘要移至 `tools/auth.json`，用户 `config.json` 只保留后端地址和 Token。业务规则、鉴权程序及云端授权条件不变，缺失或损坏的鉴权文件仍会阻止业务执行。随包测试使用本地模拟服务与合成凭据；不含生产迁移、服务器配置或真实凭据。本包用于直接分发安装，未登记到 Skilldeck 货架。
