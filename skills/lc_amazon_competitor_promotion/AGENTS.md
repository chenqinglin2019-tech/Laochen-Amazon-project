# Amazon Competitor Promotion（Agent 入口）

完整指令请阅读 `INSTRUCTIONS.md`。

## 概要

用户给一个本地文件夹，里面放 1-10 个竞品 ASIN 的西柚找词“流量得分趋势”Excel。你先用 CLI 识别 ASIN、站点、日期范围和关键字段；识别结果为 `ready` 后，必须继续用 CLI `run` 生成单文件 HTML 报告。

## 关键边界

- 输入只接受解压后的本地目录，不把 zip 当作输入直接处理。
- 不要求用户提供除西柚目录之外的额外数据。
- 西柚 Excel 本地读取；商品画像、销量、Woot、上架时间和类目背景由 CLI 自动补充。
- 价格、促销、评价、流量分数、新增广告活动等规则数据只来自西柚 Excel。
- 如果用户没有给文件夹，只问西柚“流量得分趋势”Excel 所在文件夹，不要先问站点、ASIN、类目或其它信息。
- 站外联网搜索不自动执行；除非用户后续明确要求追加公开网页证据，否则不要自行搜索和改写主报告。
- 疑似刷免评单风险、样本内季节性和 Woot 效果窗口都由 CLI 计算；agent 不要手工补结论。
- 复杂 Promotion 多折扣文案暂不精确还原；报告按 CLI 的保守估算和边界提示为准。

## 工具

按当前平台选择一个 CLI：

- Windows x64：`tools/bin/competitor-promotion-windows-amd64.exe`
- Linux x64：`tools/bin/competitor-promotion-linux-amd64`
- macOS Intel：`tools/bin/competitor-promotion-darwin-amd64`
- macOS Apple Silicon：`tools/bin/competitor-promotion-darwin-arm64`

macOS 首次运行前静默执行：

```bash
chmod +x ./tools/bin/competitor-promotion-darwin-*
xattr -d com.apple.quarantine ./tools/bin/competitor-promotion-darwin-* 2>/dev/null || true
```

## 优先动作

读 `INSTRUCTIONS.md`。

涉及商品画像、销量、Woot、上架时间和类目背景时，再读 `references/supplemental_data_contract.md`；不要让 agent 询问或处理其它来源的数据或配置。

拿到目录后先运行：

```bash
<selected-cli> inspect-inputs "/path/to/xiyou_excel_dir"
```

识别结果为 `ready` 时，向用户简短说明站点、ASIN 数、日期范围和关键字段齐全。识别结果为 `needs_confirmation` 或 `failed` 时，只说明缺失或冲突项，不要猜测和补造。

识别为 `ready` 后继续运行：

```bash
<selected-cli> run "/path/to/xiyou_excel_dir" --output "/path/to/competitor_promotion_YYYYMMDD_HHMMSS"
```

成功后交付 `竞争对手运营手段拆解与总结报告.html`。不要手工拼接报告，不要绕过 CLI 自动补充数据生成完整报告。
