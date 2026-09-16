# LC IPR Risk Screening 技能

> **待核：客户最终验收和当前客户端发行版本与 master 的对应关系，本次只整理文档未重新验收。**

给美国站单商品做有证据留痕的知识产权风险筛查。

**状态：** 本地技能，云端 `ipr-backend-dev3` 在跑；非盘点五项货架；master 已有 6e708f2 单审更新，验收不能仅凭提交推定。运行状态基线为 2026-09-08；代码核对日期 2026-09-09。

## 接口

CLI 不监听端口。`../go-cli/auth.go` 调 `/auth/skill-check`；`product_cloud.go` 经 Gateway `/ipr` 调商品详情、图片和 operation，后端 8909。Serper 可选增强由本地环境配置直连，不要求通过云端旧 Serper 路由。

## 代码一分钟

- [INSTRUCTIONS.md](INSTRUCTIONS.md)：云端发现与一次完整 Agent 审阅。
- [../go-cli/main.go](../go-cli/main.go)：CLI 入口。
- [../go-cli/product_cloud.go](../go-cli/product_cloud.go)：云端和 operation 恢复。
- [../go-cli/review.go](../go-cli/review.go)：审阅门禁。
- [../docs/project-status.md](../docs/project-status.md)：当前产品范围及已知限制。

## 数据

本地 task/raw/evidence/report 目录为证据资产，无本地数据库服务；远程 operations/images 持久卷归 backend，见后端 README。

## 部署

见[部署手册](../../../docs/deploy.md#7-交付记录与仍待核实的范围)；这是客户端/离线资产，按手册对应范围交付。

## 已知坑

WIP 分支保留 0904 未验收快照，不是当前 master/生产版本。无结果不代表无风险；确定性门禁不能替代 Agent 真正的图像比较。
