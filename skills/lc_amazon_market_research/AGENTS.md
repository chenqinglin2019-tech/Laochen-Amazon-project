# Amazon Market Research（Agent 入口）

完整指令请阅读 `INSTRUCTIONS.md`，那是平台无关的核心定义。

## 概要

用户给已经准备好的卖家精灵市场调研 Excel → 创建 `market_project_<YYYYMMDD_HHmmss>/` 项目目录 → CLI 在 `market_research/` 子目录本地清洗和计算 → 生成 HTML 看板、辅助 Excel、JSON 底稿 → 你按固定口径解读。主报告完成后，可按固定流程追加头部品牌/卖家外部调研。

本 skill 主报告只做文档中市场主报告前半段：市场规模、趋势、垄断度、广告压力、基础透视、8 项规则结论和过程留痕。头部品牌/卖家外部调研只作为公开信息推断追加，不改写结构化市场数据。

## 工具

- `tools/bin/market-research-windows-amd64.exe`：Windows x64 Go CLI（不调用后端）。
- `tools/bin/market-research-linux-amd64`：Linux x64 Go CLI（不调用后端）。
- `tools/bin/market-research-darwin-amd64`：macOS Intel Go CLI（不调用后端）。
- `tools/bin/market-research-darwin-arm64`：macOS Apple Silicon Go CLI（不调用后端）。
- macOS 首次运行前默认执行预处理：`chmod +x ./tools/bin/market-research-darwin-*`，然后执行 `xattr -d com.apple.quarantine ./tools/bin/market-research-darwin-* 2>/dev/null || true`。不要等报错后才处理。
- `<所选CLI> relevance-workspace`：从硬规则清洗后的近 30 天有效 listing 生成全量相关性打标工作区；agent 必须每个 ASIN 输出一条 relevance tag。
- `<所选CLI> relevance-exclusions`：校验 agent 全量相关性打标结果，并只把 `relevance=irrelevant` 的 ASIN 导出为剔除清单。
- `<所选CLI> review-candidates`：旧兼容入口，只提取疑似不相关候选；主流程优先使用全量 `relevance-workspace`。
- `<所选CLI> external-targets`：从已有报告中导出 Top 品牌/卖家外部调研对象和填报模板。
- `<所选CLI> attach-external`：把 agent 联网调研结果追加到 JSON、Excel 和 HTML 看板。
- `tools/market_report_template.html`：固定 HTML 看板模板
- `references/input_contract.md`：输入文件和字段约定
- `references/calculation_spec.md`：指标和规则结论口径

## 优先动作

读 `INSTRUCTIONS.md`。

主报告完成后，只用一句话询问用户是否继续联网调研 Top10 品牌/卖家并追加到同一个 HTML 看板；不要写“尚未追加”这类提示。

用户可见回复不要出现“第几章”“步骤几”等内部流程词。

主报告运行前必须完成全量相关性打标：可以先看候选提示，但不能只核查候选后把其余默认保留；每个 ASIN 都要基于标题/类目/参数做轻量相关性判断。`related` 和 `uncertain` 都保留，只有 `irrelevant` 剔除。主报告运行后会生成 `cleaned_30d_listings.json`，这是硬规则清洗和 agent 明显不相关 ASIN 剔除后的近 30 天有效 listing 样本；后续商品机会深挖应复用它，不要重新读原始竞品表绕过清洗。

主报告运行后还会在项目根目录生成 `project_manifest.json`。如果用户继续做商品机会深挖，直接把项目根目录传给 `lc_amazon_market_opportunity`，不要让用户复制 `market_research/` 子目录路径。

最终回复必须单独突出 `本次项目目录：<market_project_...>`。后续商品机会深挖只从当前上下文读取这条真实项目目录继续，不会让用户补路径。

外部调研必须按 `external-targets` 给出的品牌/卖家逐个联网搜索、逐个记录来源。来源标题、品牌名、公司名和 URL 可以保留原文，但写入看板的调研正文必须中文。生成 `external_research_filled.json` 时，任何平台都不要用 shell 字符串拼接、here-doc/here-string、`echo`/`printf`、默认重定向、默认 `Out-File` 或命令行 stdin 管道写中文 JSON；写完必须确认 JSON 可解析且不含 `???` 或替换字符。
