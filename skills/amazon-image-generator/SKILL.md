---
name: amazon-image-generator
description: Generate and archive Amazon product images through the FeiyuShentu API, or safely install, update, and remove the tested 飞鱼神图 module in a Codex Harness website. Use for image generation, Token configuration, local uploads, async tasks, retries, downloads, galleries, or the Harness module lifecycle.
---

# 飞鱼神图

## Choose the Mode

- **Website installation/update:** When the user asks to install, add, deploy, or integrate 飞鱼神图 into a Codex Harness website, read `references/harness-install.md` and `references/ui-design.md`, then carry out that workflow. Do not run the image-generation intake questions during installation. Use the bundled website template and safe defaults; ask only for blockers listed in the installation reference.
- **Website removal:** When the user asks to delete, uninstall, or remove the 飞鱼神图 website module, read the removal section in `references/harness-install.md` and prefer `scripts/remove_harness_app.py`. Default to a recoverable archive outside the live `apps/` directory; do not interpret module removal as permanent data destruction.
- **Image generation:** When the user asks to create product images, use the User Flow below and read the API/input/prompt references required by that work.
- **Website UI changes:** Use `$ui-ux-pro-max`, preserve the established host design, and read `references/ui-design.md` and `references/page-blueprint.md` before editing.

Any mode that produces or edits the 飞鱼神图 page is bound by the Page Baseline below.

## Skills

- Securely configure or replace `feiyushentu_token` in the default or caller-selected TOML file.
- Generate Amazon product images from product title, product description, generation count, and product reference image.
- Generate images in batch from a CSV file and export per-row task status and generated URLs to a result CSV.
- Fetch FeiyuShentu model and style configuration.
- Guide users through model selection, style selection, and model settings.
- Upload local product images for generation.
- Submit FeiyuShentu Amazon image async tasks.
- Poll generation task status until success, failure, or timeout.
- Return generated image URLs and optionally archive the actual files under a caller-provided directory.
- Retry failed tasks using the previous confirmed parameters.
- Guide calling websites through an accessible, responsive image-generation UI designed with `ui-ux-pro-max`.
- Reproduce one fixed page design across every integration from the bundled baseline.
- List past generations with server-side date filtering, pagination, preview, and packaged `.zip` download.

## Core Rules

- Generate Amazon images from `title`, `desc`, `total`, and required reference images, either for one product or for every row in a CSV batch.
- Do not split the workflow into main image, lifestyle image, infographic, A+ image, or other image types unless the skill is expanded later.
- Keep arbitrary site-specific code out of the skill. The verified Codex Harness adapter is intentionally bundled under `assets/codex-harness-app/`; other calling websites continue to own their navigation, routes, UI, and persistence.
- Never save generated files inside the skill directory. Use only a directory explicitly provided by the user or calling application.
- Read `references/api.md` before calling FeiyuShentu endpoints.
- Read `references/input-rules.md` when collecting user inputs or handling local images.
- Read `references/prompt-rules.md` before turning product information into generation text.
- Read `references/ui-design.md` and `references/page-blueprint.md` before designing, building, or reviewing any calling website page.
- Build every page from `assets/reference-page/feiyushentu-page.html`. Never redesign it and never ship demo mode or seeded data.
- Render selectable options by `name` and submit `value`. Store both when a submitted value must be displayed again later.
- Treat generation count as a fixed page contract, not API-provided configuration: offer every integer from 1 through 15, display each option as `生成 N 张`, and submit only the numeric string `N` as `total` (never submit the display label).
- Use `scripts/feiyushentu_amazon.py` for token handling, API calls, local image upload, async polling, and downloads.
- For website UI work, use `$ui-ux-pro-max`. If it is unavailable, install it with `$skill-installer` from `https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/tree/main/.claude/skills/ui-ux-pro-max`, then resume the UI task. Never reinstall or overwrite it when already present.
- Do not mention internal upload infrastructure, storage providers, temporary upload tokens, URL conversion, or storage implementation details to the user. Use neutral user-facing messages such as `上传产品图片`, `生成图片中`, and `完成`.

## User Flow

Follow this user-facing order:

1. Check the FeiyuShentu token.
   - Default token location: `~/.codex/config.toml`.
   - A calling application may override it with global `--config-path /path/to/config.toml` or `FEIYUSHENTU_CONFIG_PATH`.
   - Resolution priority: `--config-path`, then `FEIYUSHENTU_CONFIG_PATH`, then the default path.
   - Token key: top-level `feiyushentu_token = "xxx"`.
   - If missing or empty, say exactly: `请输入飞鱼神图的token`.
   - Save the token through a hidden terminal prompt or `set-token --stdin` before calling any API.
   - Never pass a token as a command argument, show the existing token, show a masked fragment, or return it from a status command.
   - If the user asks to replace the token, overwrite `feiyushentu_token` atomically and keep the file permission at `0600`.

2. Ask for product information.
   - Say: `请输入商品标题、商品描述、生成几张图`.
   - Collect `title`, `desc`, and `total`.
   - For a page dropdown, offer `生成 1 张` through `生成 15 张` without gaps. Its wire values are only `1` through `15`.

3. Ask for the model.
   - Fetch FeiyuShentu configuration.
   - Say: `请输入模型，模型如下，建议使用 1|nano-banana-2`.
   - List every available `model` with its display `name`, the `value` submitted as `aiModel`, points, and required settings.
   - Recommended model for the current initial flow: `1|nano-banana-2`.
   - After the user selects a model, list that model's `setting` fields, defaults, required flags, and options.

4. Ask for style.
   - Say: `请选择风格，风格如下，建议使用 亚马逊风格`.
   - List fixed style choices from `fixedSetting`, especially `style`. Show each option by its `name`; submit its `value`.
   - Recommended style: `亚马逊风格`.
   - Use defaults for other fixed settings only after showing them to the user:
     - `language`: `en`
     - `scene`: `混合 (以使用场景为主)`

5. Ask for product images.
   - Say: `上传产品图片`.
   - Collect at least one image.
   - Public URLs can be used directly.
   - Local paths are handled internally.
   - Do not explain upload infrastructure or storage details to the user.

6. Generate.
   - Before preparing images or submitting, say: `生成图片中`.
   - Do not separately say `提交任务中`; submitting the task is covered by `生成图片中`.
   - While polling task status, say: `生成中`.
   - When successful images are returned, say: `完成`.

## Page Baseline

Every page this skill produces must match one design, so all integrations look and
behave the same.

- Baseline file: `assets/reference-page/feiyushentu-page.html` — a single
  self-contained page, no build step, no runtime dependency. It is the source of
  truth.
- Specification: `references/page-blueprint.md` — layout, tokens, components,
  preview geometry, toast rules, accessibility, and delivery checks.
- Read both before building. Copy structure and tokens out of the baseline file;
  do not reconstruct the page from the description alone.
- The baseline has no demo mode and no seeded data. Do not add either.
- Two things are expected to differ per integration: the transport (a production
  site proxies the API through its own backend instead of sending a Token from the
  browser) and the history endpoint path. Layout, tokens, components, and
  behaviour do not change.
- When the host site has its own design system, substitute its colors, typography,
  and spacing tokens. Keep the baseline's grid, component structure, and
  interaction behaviour.

Page requirements that hold in every integration:

- Two views on one route: the generation workbench and 生图历史.
- 商品图 accepts a local upload or an image link, one or the other, upload first.
- No native `<select>`. Dropdown popups mount on `<body>` so a card cannot clip
  them.
- The generation-count dropdown contains all 15 fixed choices from `生成 1 张`
  through `生成 15 张`; it submits only the matching numeric string as `total`.
- Transient messages are toasts. Never insert a message block into the layout.
  Field validation stays next to its field.
- Image preview is a full-viewport dialog showing only the image, the backdrop, a
  top-right toolbar, and the page arrows. Oversized images must fit inside the
  available viewport at the default scale. Compute the fitted image dimensions
  from the dialog's current pixel size and padding rather than relying only on
  percentage `max-height`; only user-initiated zoom may exceed the viewport, and
  a zoomed image must remain draggable. The toolbar must provide a reset control
  that restores fit, rotation, and pan after any transform. Preview supports
  single-image download only; never place a packaged `.zip` action in the
  preview toolbar.
- History rows and result sets support single download and packaged `.zip`
  download.
- In generation history, render both the title and description as one-line
  ellipsized controls. Their full text must remain available through one shared
  top-level tooltip on hover, keyboard focus, click, and touch. The tooltip wraps
  long text, has bounded viewport-safe width and height, and scrolls internally
  instead of expanding the row or page.

## Generation History

The history list is served by the calling application from its own database.
FeiyuShentu has no history endpoint. Follow the request and response contract in
`references/api.md` so every integration stays interchangeable:

```http
GET /api/amazon-image-generator/history?page=1&size=5&start=YYYY-MM-DD&end=YYYY-MM-DD
```

- Filter, sort newest first, and paginate on the server.
- Store the submitted values (`ai_model`, `fixed`, `setting`) so a row can be
  resubmitted, and the matching display names (`model_label`, `fixed_label`) so the
  list can render names instead of wire values.
- Return `code = 200` with an empty `list` when nothing matches.

## Website UI Integration

- For Codex Harness installation, updates, or removal, follow `references/harness-install.md` and prefer its deterministic lifecycle scripts over recreating operations manually.
- Treat an explicit request to install on the detected website as authorization for the reversible app installation and its dedicated same-origin API proxy. Do not ask for choices covered by the tested defaults.
- When the API route is missing, automatically create only `amazon-image-generator.conf` in a pre-existing, verified per-site extension/include directory that the active Harness server block for the user's actual HTTP/HTTPS origin already loads. Prefer `scripts/configure_harness_proxy.py`; pass every active public origin and require its health response to be JSON with `data.ok = true`. Never ask for confirmation in this safe case. This authorization does not cover the main site file, a new include directive, an unmanaged/conflicting file, certificates, public ports, or unrelated ingress. Stop and report a blocker if the dedicated safe location cannot be proven.
- Never copy a Token, database, uploads, generated images, logs, PIDs, certificates, or proxy configuration into the skill or out of one website into another.
- Apply deployed code and all runtime state only in the calling website. Keep the bundled template immutable and free of site data.
- Preserve the calling website's existing stack, design system, navigation structure, route conventions, authentication, and database layer.
- Use the navigation label `飞鱼神图`, page title `飞鱼神图 · 亚马逊图片生成`, route segment `amazon-image-generator`, and recommended path `/amazon-image-generator` unless the calling project requires another convention.
- Use the Token API only as configured/unconfigured state plus replacement input. Never render, prefill, retrieve, or mask the stored Token.
- Follow the complete dependency, workflow, page-state, responsive, accessibility, and delivery rules in `references/ui-design.md`.

## API Workflow

1. Submit the async image task.
   - Send `Content-Type: application/json`.
   - Send the FeiyuShentu token as header `token: <feiyushentu_token>`.
   - Submit `fixedSetting` as an object and `setting` as an object.
   - Required `setting` shape:

```json
{
  "aspect_ratio": "1:1",
  "images": ["https://..."]
}
```

2. Poll task status.
   - Keep method as POST and send `taskIds` in the URL query string: `/amazon/amazon.img.task.status?taskIds=...`.
   - Poll every 5 seconds.
   - Stop after 120 polls or 10 minutes.
   - `status = 3`: success; return generated image URLs.
   - `status = 2`: generating; keep polling.
   - `status = -1`: failed; tell the user generation failed.

3. Handle retry and download.
   - On failure, offer retry. Retry means submit a new task with the last confirmed `total`, `title`, `desc`, `fixedSetting`, `aiModel`, and `setting`; do not keep polling the old task.
   - On success, show generated image URLs first.
   - If the calling application supplied `--output-dir`, archive the files immediately and return the original URL, local path, file metadata, and archive status.
   - If no output directory was supplied, ask whether the user wants to archive the images. If yes, ask for the save directory, then download.
   - Treat generation and archiving as separate states. Preserve successful URLs when any download fails and return partial or failed archive records for download-only retry.

## Script Usage

Batch CSV generation:

```bash
python3 scripts/feiyushentu_amazon.py batch \
  --csv products.csv \
  --output products-results.csv \
  --output-dir "/srv/example-site/data/generated-images" \
  --fixed-setting '{"language":"en","style":"亚马逊风格","scene":"混合 (以使用场景为主)"}' \
  --ai-model "1|nano-banana-2" \
  --setting '{"aspect_ratio":"9:16","resolution":"2K"}'
```

The input CSV must contain `title`, `desc`, `total`, and either `image_urls` or `images`. Separate multiple reference URLs with `|`. The output CSV contains the source row, task IDs, status, generated image URLs, local paths, JSON image records, archive status, archive error, and generation error. A failed row does not stop later rows.

Check whether the token is configured:

```bash
python3 scripts/feiyushentu_amazon.py check-token
```

Save or replace the token through a hidden terminal prompt:

```bash
python3 scripts/feiyushentu_amazon.py set-token
```

For a non-interactive caller, place `--config-path` before the command and send the new token through standard input to `set-token --stdin`. Do not place the token in a shell command or process argument.

Fetch selectable settings:

```bash
python3 scripts/feiyushentu_amazon.py fetch-config
```

Generate and poll:

```bash
python3 scripts/feiyushentu_amazon.py generate \
  --total "2" \
  --title "32 oz Stainless Steel Insulated Water Bottle" \
  --desc "BPA-free double-wall vacuum insulated bottle for gym, travel, and daily hydration." \
  --fixed-setting '{"language":"en","style":"亚马逊风格","scene":"混合 (以使用场景为主)"}' \
  --ai-model "1|nano-banana" \
  --setting '{"aspect_ratio":"1:1"}' \
  --image "https://f-v.feiyushuju.com/Plug/RRRRRS//20260525/example.png" \
  --output-dir "/srv/example-site/data/generated-images"
```

Download after the user confirms a directory:

```bash
python3 scripts/feiyushentu_amazon.py download \
  --output-dir "/path/to/save" \
  --url "https://f-v.feiyushuju.com/ShenTu/20260525/example.png"
```

## Error Handling

- Missing or empty `feiyushentu_token`: ask the user to provide a token and save it.
- API `code = 10002`: token is empty or not passed; ask the user to provide and save a token.
- API `code = 10003`: token is invalid; ask the user to replace the token.
- API `code = 11008`: account is disabled; stop and tell the user to check the FeiyuShentu account or replace the token.
- Any task with `status = -1`: report generation failure and offer retry with the last confirmed payload.
