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
- 站外联网搜索不自动执行。用户明确继续后先做 Agent 免费公开网页检索；免费证据追加完成后，必须再次询问用户是否启用收费增强。此前对免费搜索的同意不能代替收费确认。
- 疑似刷免评单风险、样本内季节性和 Woot 效果窗口都由 CLI 计算；agent 不要手工补结论。
- 复杂 Promotion 必须先运行 `promotion-workspace`，由 Agent 按 `references/promotion_semantics_contract.md` 逐个审核去重组合，再把完整映射交给 `run` 校验。

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

识别为 `ready` 后，先创建本轮唯一输出目录并运行：

```bash
<selected-cli> promotion-workspace "/path/to/xiyou_excel_dir" --output "/path/to/competitor_promotion_YYYYMMDD_HHMMSS/promotion_semantic_workspace.json"
```

按契约完成 `promotion_semantic_map.json` 后，再运行：

```bash
<selected-cli> run "/path/to/xiyou_excel_dir" --promotion-map "/path/to/competitor_promotion_YYYYMMDD_HHMMSS/promotion_semantic_map.json" --output "/path/to/competitor_promotion_YYYYMMDD_HHMMSS"
```

成功后交付 `竞争对手运营手段拆解与总结报告.html`。不要手工拼接报告，不要绕过 CLI 自动补充数据生成完整报告。

免费站外追加和收费增强的完整确认顺序见 `INSTRUCTIONS.md`。收费增强只允许通过 `paid-offsite-workspace` 调用统一后端；不要让用户或 Agent 接触第三方 token。收费候选必须按 `references/paid_offsite_merge_contract.md` 逐条判断，再由 `merge-paid-offsite` 校验并更新同一个 HTML。
