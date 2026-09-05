# Input Rules

## Supported Scope

Support these tasks:

Generate Amazon product images from:

- Product title.
- Product description.
- Generation count.
- One or more reference images.
- CSV batch generation with one product per row.

### CSV Batch

The input CSV must contain `title`, `desc`, `total`, and either `image_urls` or `images`. Multiple image URLs in a row use `|` as the separator. The batch command writes a result CSV with `row`, `title`, `task_ids`, `status`, `image_urls`, `local_paths`, `image_records`, `archive_status`, `archive_error`, and `error`. `image_records` is a JSON array containing the per-image metadata. Process rows sequentially and continue after row-level failures.

Do not ask the user to choose Amazon image subtypes such as main image, lifestyle image, infographic, A+ image, or comparison image.

## Required Inputs

- `title`: required product title.
- `desc`: required product description.
- `total`: required generation count from 1 through 15. Send only the selected
  number as a string (`"1"` … `"15"`), never a label such as `"生成 1 张"`.
- `images`: required reference images.
- `fixedSetting`: required object confirmed from the config endpoint.
- `aiModel`: required model value confirmed from the config endpoint.
- `setting`: required object confirmed from the selected model settings.

## User-Facing Collection Order

Use this order in normal conversations:

1. Check token. If missing or empty, say: `请输入飞鱼神图的token`.
2. Ask: `请输入商品标题、商品描述、生成几张图`.
3. Fetch configuration and ask: `请输入模型，模型如下，建议使用 1|nano-banana-2`.
4. Ask: `请选择风格，风格如下，建议使用 亚马逊风格`.
5. Ask the user to upload product images.

Status messages:

- Never mention internal upload infrastructure, storage providers, temporary tokens, URL conversion, or storage implementation details to the user.
- Before preparing images or submitting: `生成图片中`
- While handling product images: `上传产品图片`
- Do not separately say `提交任务中`; task submission is covered by `生成图片中`.
- While polling: `生成中`
- On success: `完成`

## Reference Images

Reference images may be:

- Public HTTP(S) URLs.
- Local image paths.

Rules:

- Public URLs can be used directly.
- Local image paths must be prepared internally before generation.
- `setting.images` must be an array of final public image URLs.
- If no reference image is available, stop and ask the user for one.

## Local Image Upload

Use the upload endpoint from `api.md`. This is an internal implementation detail; do not mention it to users.

Object naming:

```text
/Plug/RRRRRS//YYYYMMDD/uuid_original-filename
```

After upload, the final internal image URL must use the `domain` from the upload token response, for example:

```text
https://f-v.feiyushuju.com/Plug/RRRRRS//20260525/uuid_product.png
```

## Generated Image Output

- On success, show image URLs first.
- If the caller supplied `--output-dir`, archive the images immediately under task-specific subdirectories.
- Otherwise, ask the user whether to archive the images. If yes, ask for the output directory.
- Do not choose a default local download directory unless the user asks you to choose.
- Never use the skill directory as the output directory.
- Keep URL-only behavior when no output directory is supplied.
- Return a record for every image with its original URL, local path, file metadata, archive status, and error.
- If some downloads fail, preserve successful files and URLs and report `partial`; do not regenerate the images.
- Leave database persistence to the calling application.

## Retry

If a task fails:

- Tell the user generation failed.
- Offer retry.
- Retry by submitting a new async task with the last confirmed `total`, `title`, `desc`, `fixedSetting`, `aiModel`, and `setting`.
- Do not keep polling the failed task.
