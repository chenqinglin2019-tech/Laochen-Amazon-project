# Codex 页面填写与自动保存

## 启动

`node scripts/cli.cjs ui bundle-or-v2.json <本次任务目录>` 会准备数据，启动脱离终端的 Node 标准库服务并输出 JSON。使用返回的完整 URL 调用 `open_in_codex({target:{type:"browser",url}})`。Node 18+；无需 npm 安装、框架或构建。仅缺经营参数不算启动失败。

`examples/quick-intake-bundle.json` 是已有商品资料、经营参数全空的演示；可用 `--offline` 验收。新任务仍自动取数、核验缓存，不依靠示例数据。

## 保存与恢复

- 每次修改立即本地计算，停止输入约 500ms 后串行保存；按钮立即执行。保存未完成时不显示“已保存”。
- 输入空白按 null，0 按已提供数值处理。缺项草稿同样保存，但 result.scenarios 为 null，页面隐藏失效结果。
- 服务端对白名单参数重新计算；不会信任浏览器上传毛利金额。input/result/report/ui-state 四份输出先暂存，正常写入失败回滚已替换文件。ui-state 最后提交，是重启恢复的权威快照；异常断电后重启会重新生成派生文件。
- 刷新用最新已保存输入。网络或磁盘失败保留本页输入，点击按钮重试；关闭前有未保存改动会提示。版本冲突不会覆盖新版本：先导出当前输入，再刷新对照修改。
- 同一输出目录复用现有服务；不同任务使用不同目录、令牌、端口。不同 ASIN/站点不能复用同一目录。相同商品开始新的测算也应使用新目录。
- 服务停止后重复 ui 命令恢复草稿。相同目录以草稿为准；原 bundle 的新值不会悄悄覆盖已有编辑。更新费率时把已保存 input 与新费率另存新目录启动。
- 页面每分钟保活；最后一次请求后空闲 30 分钟关闭服务。临时进程信息和令牌放在操作系统临时目录，不装入 Skill 包或离线报告。

## 本地接口

服务监听 127.0.0.1 的随机端口，校验 Host、同源 Origin、会话令牌；未开放 CORS。URL hash 中令牌只用于本机请求，不随来源链接发送。

- `GET /` 返回当前表单（嵌入最新草稿和版本号）。
- `GET /api/state`：`X-Session-Token`，返回 input、revision、result、savedAt。
- `POST /api/save`：同源 Origin、同令牌、JSON `{revision,editable}`。可编辑 product 的 price/category/packQuantity/variant/packaging，scenario 经营字段，logistics 已支持渠道。其他字段拒绝。409 为版本冲突，500 为保存失败。

独立 report.html 不包含会话令牌及接口连接；它可以离线计算，但无法自动写入任务目录，需导出参数。主流程必须打开 ui 返回的 URL。
