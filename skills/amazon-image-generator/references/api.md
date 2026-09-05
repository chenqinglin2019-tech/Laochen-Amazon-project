# FeiyuShentu API Reference

Base URL: `https://server.feiyushentu.com/api/v0.1`

All requests use:

- Method: `POST`
- Header: `token: <feiyushentu_token>`
- Header: `Content-Type: application/json`
- Body: JSON

## Token Storage

Read the token from the resolved TOML path. Use this priority:

1. Global CLI option `--config-path`.
2. Environment variable `FEIYUSHENTU_CONFIG_PATH`.
3. Default `~/.codex/config.toml`.

```toml
feiyushentu_token = "xxx"
```

Do not hard-code the token in skill files, command arguments, logs, or responses. Update it through `set-token --stdin` for non-interactive callers or a hidden terminal prompt for an operator. Keep the token file at permission `0600`. Token checks return only `token_configured`.

## Common Token Errors

- `code = 10002`, `msg = "Token为空"`: token is empty or was not sent. Ask the user to provide and save a token.
- `code = 10003`: token is invalid. Ask the user to replace the token.
- `code = 11008`, `msg = "账号已被禁用"`: account is disabled. Stop the flow and tell the user to check the account or replace the token.

## Get Selectable Configuration

Endpoint:

```http
POST /common/plug.select.field
```

Purpose: Fetch `fixedSetting` and AI model configuration before generation.

Important response fields:

- `data.fixedSetting`: fixed style settings.
- `fixedSetting[].title`: display name of the group.
- `fixedSetting[].field`: request field name.
- `fixedSetting[].default`: default value.
- `fixedSetting[].value`: selectable options.
- `data.model`: model list.
- `model[].name`: display name.
- `model[].value`: value passed as `aiModel`.
- `model[].points`: points charged per generated image.
- `model[].setting`: model-specific settings.
- `model[].setting[].field_key`: request field name in `setting`.
- `model[].setting[].field_option`: selectable options.
- `model[].setting[].default_value`: default value.
- `model[].setting[].is_required`: required flag.

### Option Shape: Display `name`, Submit `value`

`fixedSetting[].value[]` and `model[].setting[].field_option[]` return selectable
options. An option is either a plain string or an object:

```json
{ "name": "英语", "value": "en" }
```

- `name` is the human-readable label. Render this.
- `value` is the wire value. Submit this in `fixedSetting` and `setting`.
- A plain string is both at once.

Never display `value` when `name` exists, and never submit `name`. Normalize every
option through one function so both dropdown groups behave identically:

```js
function has(x){ return x !== undefined && x !== null && x !== ""; }
function pair(o){
  if(o && typeof o === "object"){
    const v = has(o.value) ? o.value : has(o.key) ? o.key
            : has(o.id) ? o.id : has(o.name) ? o.name : o.label;
    const t = has(o.name) ? o.name : has(o.label) ? o.label
            : has(o.title) ? o.title : v;
    return { value: String(v), label: String(t) };
  }
  return { value: String(o), label: String(o) };
}
```

`label`, `title`, `key`, and `id` are defensive fallbacks for older or changed
response shapes; `name` and `value` are the contract. Apply the same rule to
`model[]`: display `model[].name`, submit `model[].value`.

When a submitted value is displayed again later (a run summary, a history row),
translate it back to its `name` first. Store both: the value for re-submission,
the name for display.

Rules:

- List all `fixedSetting` options for the user before generation.
- List all models for the user before generation.
- After model selection, list that model's `setting` fields and options.
- `images` is required even if the config response marks it optional.
- `images` must be public image URLs by the time the generation task is submitted.

## Get Upload Token

Internal implementation detail: do not mention COS, object storage, temporary tokens, or public URL conversion to the user.

Endpoint:

```http
POST /common/yun.token
```

Purpose: Prepare local reference images so they can be used by the generation API.

Successful response shape:

```json
{
  "code": 200,
  "data": {
    "expiredTime": 1779694590,
    "token": "<temporary-cos-token>",
    "secretId": "<temporary-secret-id>",
    "secretKey": "<temporary-secret-key>",
    "type": "cos",
    "bucket": "ai-image-video-1251050854",
    "region": "ap-guangzhou",
    "domain": "f-v.feiyushuju.com",
    "prefix": "ShenTu"
  },
  "msg": "获取成功"
}
```

Rules:

- Use this endpoint only when the user provides a local image path.
- Upload object naming: `/Plug/RRRRRS//YYYYMMDD/uuid_original-filename`.
- If the upload result domain is not `data.domain`, replace the public URL domain with `data.domain`.
- Do not store temporary upload credentials.

## Add Async Image Task

Endpoint:

```http
POST /amazon/amazon.img.task.agent.add
```

Payload:

```json
{
  "total": "2",
  "title": "32 oz Stainless Steel Insulated Water Bottle",
  "desc": "BPA-free double-wall vacuum insulated bottle for gym, travel, and daily hydration.",
  "fixedSetting": {
    "language": "en",
    "style": "亚马逊风格",
    "scene": "混合 (以使用场景为主)"
  },
  "aiModel": "1|nano-banana",
  "setting": {
    "aspect_ratio": "1:1",
    "images": [
      "https://f-v.feiyushuju.com/Plug/RRRRRS//20260525/example.png"
    ]
  }
}
```

Required fields:

- `total` string: number of images to generate, from `"1"` through `"15"`.
  Submit only the numeric string; `生成 N 张` is a page label and must never be
  sent in the payload.
- `title` string: product title.
- `desc` string: product description.
- `fixedSetting` object: `{field: value}` from the config endpoint.
- `aiModel` string: `model[].value`.
- `setting` object: `{field_key: value}` from the selected model settings. Must include `images`.

Successful response:

```json
{
  "code": 200,
  "data": [
    {
      "task_id": "RRJEGF",
      "status": 1,
      "status_str": "已排队"
    }
  ],
  "msg": "添加成功"
}
```

Use every returned `task_id` for status polling.

## Get Task Status

Endpoint:

```http
POST /amazon/amazon.img.task.status
```

Request:

```http
POST /amazon/amazon.img.task.status?taskIds=RRJEGF,ABC123
```

Rules:

- `taskIds` is a comma-separated string of task IDs returned by the add-task endpoint.
- Live integration showed `taskIds` must be sent in the URL query string while keeping the request method as POST.
- Sending `taskIds` as a JSON body can return `code = 10006`, `msg = "请求方式错误"`.
- Poll every 5 seconds.
- Poll at most 120 times.
- Stop after 10 minutes.

Successful response:

```json
{
  "code": 200,
  "data": [
    {
      "task_id": "RRJEGF",
      "progress": 100,
      "status": 3,
      "images": [
        "https://f-v.feiyushuju.com/ShenTu/20260525/example.png"
      ]
    }
  ],
  "msg": "获取成功"
}
```

Status values:

- `3`: success. Collect `images`.
- `2`: generating. Continue polling.
- `-1`: failed. Report failure and offer retry by submitting a new task with the previous confirmed payload.

## Generation History (Calling Application)

FeiyuShentu has no history endpoint. The generation-history list is served by the
**calling application** from its own database, using the persistence rule in
`references/ui-design.md`. This section fixes one request and response shape so
every integration behaves the same.

Endpoint (the path is owned by the calling application; keep the query and
response shape identical):

```http
GET /api/amazon-image-generator/history?page=1&size=5&start=2026-08-01&end=2026-08-26
```

Query parameters:

- `page` integer, 1-based.
- `size` integer, rows per page.
- `start` `YYYY-MM-DD`, inclusive, may be empty.
- `end` `YYYY-MM-DD`, inclusive, may be empty.

Response:

```json
{
  "code": 200,
  "data": {
    "list": [],
    "total": 0,
    "page": 1,
    "size": 5
  },
  "msg": "获取成功"
}
```

`HistoryItem`:

```json
{
  "task_id": "RRJEGF,RRJEGG",
  "created_at": "2026-08-26 14:03:11",
  "title": "32 oz Stainless Steel Insulated Water Bottle",
  "desc": "BPA-free double-wall vacuum insulated bottle.",
  "ai_model": "1|nano-banana-2",
  "model_label": "Nano Banana 2",
  "fixed": { "style": "亚马逊风格", "language": "en", "scene": "混合 (以使用场景为主)" },
  "fixed_label": { "style": "亚马逊风格", "language": "英语", "scene": "混合 (以使用场景为主)" },
  "setting": { "aspect_ratio": "1:1", "resolution": "2K" },
  "points": 24,
  "source_images": ["https://..."],
  "images": ["https://...", "https://..."]
}
```

Field rules:

- `task_id`: join multiple task IDs from one submission with a comma.
- `created_at`: local time, `YYYY-MM-DD HH:mm:ss`. Do not return an epoch number.
- `ai_model` / `fixed` / `setting`: the values that were submitted, so a row can be
  resubmitted unchanged.
- `model_label` / `fixed_label`: the matching display names, per the option-shape
  rule above. The list renders `*_label` and falls back to the raw value when a
  label is missing.
- `points`: total points charged for the whole submission, not per image.
- `source_images`: the product images the user supplied.
- `images`: generated image URLs, in generation order.
- Omit failed entries from `images`. An empty `images` array means the row produced
  nothing.

Rules:

- Filter, sort, and paginate on the server. Return rows newest first.
- Clamp `page` into range and return the clamped value in `data.page`.
- `total` counts rows matching the date filter, not rows on the current page.
- Return `code = 200` with an empty `list` when nothing matches. Do not return 404.
- Never include a Token, temporary upload credentials, or internal storage paths.
- The page inserts a just-finished generation at the top of page 1 locally, so a
  write that lands slightly late does not look like a lost run. The server stays
  the source of truth on the next query.

## Archive Generated Images

Generated URLs may expire. When a caller supplies `--output-dir` to `generate`, `status`, or `batch`:

- Download each successful image immediately.
- Store it under `<output-dir>/<task_id>/`.
- Reject any output directory inside the installed skill directory.
- Preserve `source_url`, `task_id`, `local_path`, filename, byte size, MIME type, SHA-256, archive status, and per-image error.
- Return `archive.status` as `success`, `partial`, or `failed`.
- Keep successful generation URLs when archiving fails so the caller can retry only the download.
- Do not write to a database. The calling application owns database persistence.
