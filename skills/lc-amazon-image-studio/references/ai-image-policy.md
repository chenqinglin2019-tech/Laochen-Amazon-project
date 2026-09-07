# AI 图片来源与导出规则

最近核对：2026-09-05。这里区分平台明确要求与本 skill 的交付约定；未来生产如规则、站点、类目或渠道有变化，重新读取官方来源并记录适用版本。

## 平台要求

包含逼真 AI 生成人物的 Listing 与 A+ 图片，须按亚马逊规则披露来源。全球店铺公告指定在文件 XMP `dc:subject` 中加入 `contains-synthetic-performer`，平台在适用时显示提示；无人、非逼真人物及只含真人（即使经 AI 修改）的图片不适用这项人物标签。[Amazon 官方公告](https://sellercentral.amazon.com/seller-forums/discussions/t/aa0aee06-aff4-497a-a4b6-9b2ebe06f715)

局部人物需看是否仍为逼真 AI 人物，不能因为只露手或半身就省略标签。A+ 可预先嵌入，或在上传界面选中 AI 人物选项由平台添加；本 skill 默认对适用成品统一预先嵌入，便于独立验证。[Amazon 员工补充说明](https://sellercentral.amazon.co.uk/seller-forums/discussions/t/2a1428e1-6fd7-4f3e-b75c-23170da8654b)

生成背景或商品本身，不等于含合成人物。上传 A+ 时仍按当前界面处理适用的额外声明；不得把元数据检查等同于所有渠道合规。广告素材需另行核对 [Amazon Ads 指南](https://advertising.amazon.co.uk/help/GZZX6RJVMWBVBB6W)，本流程的 Listing 放行不能替代广告审核。

## Manifest 中的来源判断

每张图记录 `ai_disclosure.human_source`、`notes`，并在实际查看当前画面后用 `reviewed_image_sha256` 绑定 `job.image_sha256`（本地待排版画面；model_native则为已经含模型文字的当前画面像素哈希）：

- `synthetic`：画面含逼真 AI 生成人物，包括符合这一条件的手、面部局部或半身。
- `real`：仅有真实人物，可含基于真实人物的 AI 编辑。
- `none`：无人。
- `non_photorealistic`：仅非逼真人物。
- `unknown`：来源或是否逼真尚未确定；完成审阅后才能交付。

多种来源混合且包含任何逼真合成人物时选 `synthetic`。判断基于原始素材、生成过程和成品查看，不能只看提示或只看“AI 编辑”这个工具名称。

有 `layout.items[].image` 或V3 `layout.panels[].image` 照片插图时，来源判断同时覆盖所有插图；除了底图绑定，还将 `reviewed_visual_fingerprint` 绑定 `job.disclosure_visual_fingerprint`（底图像素与全部插图文件内容共同形成的依赖指纹）。底图无人但插图含AI手部仍须标记；修改插图内容需重审人物来源，仅修改本地文字无需重审来源；model_native改字返回新图仍须检查当前像素。

## 本 skill 的导出约定

1. 保留原始输入及来源记录；不要复制编辑前的 C2PA 签名并声称仍有效。
2. 完成图层合成、排版、统一缩放与压缩后，再写入适用的 XMP 标签。
3. 回读最终交付文件，检查真实嵌入的字段及精确关键词，再计算最终哈希。旁边的 JSON 或日志不能替代文件内部元数据。
4. 标签补写属于导出阶段；复用已通过的底图和排版，不触发图像生成。
5. 保存元数据验证结果及当前来源判断。平台是否展示提示由平台决定，本地嵌入成功不能当成已上传审核通过。

主图不因 AI 披露自行加画面水印。DigitalSourceType、C2PA 等来源机制不在本 skill 中宣称为亚马逊所有图片的统一强制要求。图片本身仍需满足类目内容、真实性、尺寸和文字可读性要求。
