# Page Blueprint

The visual and behavioural baseline for the 飞鱼神图 page. Every page this skill
produces must match it 1:1 unless the calling project's own design system
overrides a specific token (see *Adapting to a host design system* below).

## The Baseline File

```text
assets/reference-page/feiyushentu-page.html
```

A single self-contained file: one `<style>` block, one `<script>` block, no build
step, no runtime dependency. It is the source of truth. When this document and the
file disagree, the file wins.

Read the file before building. Do not reconstruct the page from this document
alone — copy the structure, tokens, and components out of the baseline and adapt
only what the host stack requires (framework components, routing, the history
endpoint path, the API transport).

The baseline calls the FeiyuShentu API directly with a Token entered on the page.
A production integration normally proxies through its own backend instead. That
changes the transport layer only; layout, tokens, components, and behaviour stay
identical.

The baseline contains no demo mode and no seeded data. Do not add either.

## Layout

Two views in one page, switched by hash route:

- `#/` — generation workbench.
- `#/history` — generation history.

```text
┌────────────────────────────────────────────────────────────┐
│ topbar  logo · tabs(图片生成 / 生图历史) ······· Token pill │  62px, sticky
├────────────────────────────────────────────────────────────┤
│  ┌── left column ────────┐  ┌── right column ───────────┐  │
│  │ 商品图                 │  │ 本次生成                   │  │
│  │  上传 / 链接（二选一）  │  │  任务状态 · 结果画廊        │  │
│  ├───────────────────────┤  │  （sticky）                │  │
│  │ 商品信息               │  │                           │  │
│  ├───────────────────────┤  │                           │  │
│  │ 生成设置               │  │                           │  │
│  ├───────────────────────┤  │                           │  │
│  │ [ 开始生成 ] (sticky)  │  │                           │  │
│  └───────────────────────┘  └───────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

Grid:

- `< 1080px`: single column, right panel below the form.
- `≥ 1080px`: `452px minmax(0, 1fr)`, gap `18px`.
- `≥ 1400px`: `496px minmax(0, 1fr)`, gap `22px`.
- Page wrapper: `max-width: 1560px`, padding `20px clamp(16px, 2.4vw, 28px) 60px`.

No hero, no marketing band, no decorative section that carries no data. Every
block on the page must hold an input, a state, or a result.

## Design Tokens

Copy verbatim from the baseline's `:root`. The full set:

```css
/* surface */
--bg:#F4F5FA;  --bg-sunk:#EFF0F7;  --card:#FFFFFF;  --tint:#F7F7FC;  --tint-2:#F1F1F8;
/* line */
--line:#EBECF4;  --line-2:#E1E2EE;  --line-3:#D5D7E6;
/* ink */
--ink:#171826;  --ink-2:#454864;  --ink-3:#6E7190;  --ink-4:#9A9DB6;  --ink-5:#B9BBCE;
/* accent */
--ac:#5A4BE8;  --ac-2:#7C6DF2;  --ac-ink:#4438C9;
--ac-tint:#EFEDFE;  --ac-tint-2:#E4E1FD;  --ac-line:#D3CEFB;
/* semantic */
--ok:#0FA968;  --ok-tint:#E6F7EF;
--warn:#E8890B; --warn-tint:#FDF2E1;
--bad:#E14B52; --bad-tint:#FDECEC;
--info:#2E6BE6; --info-tint:#EAF2FE;
/* shadow */
--sh-1:0 1px 2px rgba(23,24,38,.05);
--sh-2:0 1px 2px rgba(23,24,38,.05),0 10px 26px -16px rgba(23,24,38,.22);
--sh-3:0 2px 6px rgba(23,24,38,.06),0 22px 48px -24px rgba(23,24,38,.30);
--sh-pop:0 32px 70px -28px rgba(23,24,38,.42);
--sh-ac:0 10px 22px -10px rgba(90,75,232,.55);
/* radius */
--r-s:8px; --r-m:11px; --r-l:16px; --r-xl:20px;
/* type */
--fs:'Manrope','Noto Sans SC',system-ui,-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;
--fm:'DM Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
/* metrics */
--topbar-h:62px;
```

Typography:

- Body `14px / 1.6`. Card title `15px / 700`. Section subtitle `12.5px`,
  `--ink-4`. Field label `12.5px / 600`. Helper text `12px`, `--ink-4`.
- `--fm` (DM Mono) is reserved for machine values: task IDs, model values, counts,
  points, byte sizes, ratio strings. Never set prose in it.
- Chinese and Latin share one stack so mixed strings keep one baseline.

Light theme only. The page declares `color-scheme: light`; do not add a dark
variant unless the host site has one.

## Components

### Segmented control — 商品图 upload / link

Upload and link are mutually exclusive, not two stacked inputs. A two-segment
control with a sliding indicator sits at the top of the 商品图 card; upload is
selected by default.

- `role="tablist"` with two `role="tab"` buttons and two `role="tabpanel"` panels.
- The inactive panel carries `hidden`; roving `tabIndex` follows selection.
- ←/→ switch segments.
- Switching clears the field error and focuses the URL input in link mode.
- The thumbnail strip and error line live outside both panels and stay visible in
  either mode.

### Dropdown

Native `<select>` is not allowed anywhere on the page. The custom control:

- Trigger: `min-height 44px`, `border 1px var(--line-2)`, radius `--r-m`; when
  open, `border-color var(--ac)` and a `3.5px var(--ac-tint)` ring. The chevron
  rotates 180°.
- Popup: appended to `document.body`, `position: fixed`, `z-index: 900`. It is a
  child of `<body>` so a card's `overflow` can never clip it.
- Placement measures the space below the trigger and flips up when it is short,
  then clamps to the viewport on both axes. It repositions on scroll and closes
  on resize.
- Selected option: `600` weight, `--ac-tint` background, check mark. An option may
  carry a badge chip (`推荐`, `12 积分`) in `--fm`.
- ARIA: `combobox` / `listbox` / `option`, plus `aria-haspopup`, `aria-expanded`,
  `aria-controls`, `aria-selected`, `aria-activedescendant`, `aria-labelledby`.
- Keys: ↑↓ move, Enter/Space select, Esc/Tab close, Home/End jump.

Options are normalized through the `pair()` helper in `references/api.md`:
display `name`, submit `value`.

The `生成数量` dropdown is the fixed exception to API-provided option lists. It
contains every integer from 1 through 15 without gaps. Display its choices as
`生成 N 张`, but keep each option value as the numeric string `N` and submit only
that value in `total`.

### Image preview (lightbox)

Full-viewport `<dialog>`. On screen there is the image, the backdrop, a top-right
toolbar, and the two page arrows — nothing else. No title, no caption, no counter,
no bottom bar.

```text
                                    ┌──────────────────────────┐
                                    │ ⊖  ⊕  ⛶  ↻  ⤓ │ ✕       │  top:22 right:25
                                    └──────────────────────────┘   h:46 r:13
        ┌───────────────────────────────────────────┐
   ‹    │                  image                    │    ›
        └───────────────────────────────────────────┘
   ↑ left:19, 48×56, border-radius 50%, vertically centred
```

Exact values:

- Backdrop: `rgba(0,0,0,.47)` with `backdrop-filter: blur(8px)`.
- Image: centred, square corners, no shadow, `padding: 46px 84px` around it. At
  the default scale, its containing figure has a definite width and height equal
  to the available padded viewport, so an oversized source is always contained
  on both axes and never extends beyond the screen. On image load and visual
  viewport resize, calculate the base image dimensions in pixels from the
  dialog's rendered width/height minus its computed padding. Percentage
  `max-height` alone is not sufficient for this guarantee.
- Toolbar: `top 22px`, `right 25px`, `height 46px`, `border-radius 13px`,
  background `rgba(35,42,54,.94)` with `blur(12px)`.
- Toolbar buttons: `44 × 44`, icons `22px`, stroke `1.85`, colour
  `rgba(255,255,255,.85)`, `#fff` on hover with a `rgba(255,255,255,.11)` wash.
- Order: zoom out, zoom in, restore fitted size, rotate, download, divider,
  close. The preview toolbar never contains a packaged `.zip` action.
- Arrows: `48 × 56`, `border-radius 50%`, `background rgba(45,50,59,.94)`,
  `left/right: 19px`.
- The toolbar always contains the same six buttons. For a single image, both
  page arrows are hidden; for multiple images, the arrows remain available.

Behaviour: 8 zoom steps `0.4 → 3` (buttons disable at each end), 90° rotate,
wheel zoom, double-click to toggle, drag to pan while zoomed, ←/→ to page,
`+`/`-` to zoom, `0` to restore, click outside the image to close. The restore
button resets scale to the fitted `1×` step, rotation to `0°`, and pan to the
centre. The fitted `1×` image never exceeds the visible viewport height; zoom
above `1×` may exceed it and remains draggable with mouse, pen, or touch. A drag
that ends outside the image must not close the dialog.

Below `640px`: the toolbar centres at the top and the arrows move to `8px`.

### Toast

All transient messages are toasts. The page never inserts a message block into the
layout — no banner strip, no alert row, no status card.

- Container: `position: fixed`, top-centre, below the topbar, `z-index: 220`,
  `width: min(520px, 100vw - 24px)`, `pointer-events: none`.
- Toast: white `rgba(255,255,255,.95)` with `blur(16px)`, `1px var(--line-2)`,
  radius `13px`, shadow `0 20px 44px -16px rgba(23,24,38,.34)`.
- A round tinted icon chip on the left: indigo for info, `--ok-tint` for success,
  `--bad-tint` for failure.
- Optional action button (e.g. `配置 Token`) and an always-present close button
  with a `44 × 44` hit area.
- Auto-dismiss `3.4s`, `6.5s` for errors, `0` for a message the user must act on.
  Hovering pauses the timer. At most four stack; `key` de-duplicates and allows
  targeted clearing.

Field-level validation is the exception: an invalid Token, a missing title, a bad
image URL renders next to its input and keeps the user's text. Those are not
toasts.

### Result gallery and history rows

- The gallery reserves each card's aspect ratio from the selected `aspect_ratio`
  so results do not shift the layout as they arrive.
- Queued, generating, success, generation failure, and poll timeout are five
  distinct visible states.
- Each history row shows the source image, time, title, model / ratio / resolution
  / style / language chips, points, the result thumbnails, and per-row download
  and package actions.
- History title and description are separate one-line ellipsized controls. A
  shared `role="tooltip"` element mounted at page root shows the selected field's
  full text on mouse hover, keyboard focus, click, or touch. Clamp it within the
  viewport, use `max-width: min(420px, 100vw - 24px)` and
  `max-height: min(240px, 100dvh - 24px)`, wrap long words/content, and scroll
  internally when necessary. Clicking elsewhere or pressing Escape closes it.
- History filters: a date range with quick chips, plus a keyword field. Page size
  is a dropdown. Filtering or changing page size resets to page 1.

### Packaged download

Outside the preview dialog, `.zip` is built in the browser with a stored-method (uncompressed) writer: local
file header, central directory, EOCD, CRC-32 per entry, UTF-8 filename flag
`0x0800`. No library. When an image host refuses cross-origin reads, fall back to
opening the images in new tabs and say so in a toast. Packaged download belongs
to the result gallery and history rows, never the preview toolbar.

## Accessibility

- Visible labels on every field; placeholders are never the label.
- Interactive targets at least `44 × 44`, including icon-only buttons — use a
  transparent `::before` to enlarge a small visual control.
- Contrast at least WCAG AA (`4.5:1` for body text).
- Async state changes announce through a live region without repeating.
- `prefers-reduced-motion` disables the entrance animations.
- No horizontal scrolling at `375`, `768`, `1024`, `1440`, and `1920px` in either
  view.

## Adapting to a Host Design System

`references/ui-design.md` makes the calling site's design system authoritative.
When it defines its own tokens:

- Replace `--bg`, `--card`, `--line*`, `--ink*`, `--ac*` with the host's
  equivalents and keep the same roles and contrast relationships.
- Keep the structural values regardless: the grid breakpoints, `--topbar-h`, the
  radius scale, the lightbox geometry, the `44px` control height, and every
  component behaviour above.

The look may inherit the host's palette and type. The structure and behaviour do
not change.

## Delivery Checks

Before delivering, confirm:

- No native `<select>` remains.
- No demo mode, demo data, or seeded records.
- Dropdown popups are children of `<body>` and are not clipped by any card.
- The preview matches the geometry table above and shows nothing besides the
  image, backdrop, toolbar, and arrows.
- An oversized preview fits inside the available viewport at `1×`, and the
  restore button returns zoom, rotation, and pan to that fitted state.
- The preview toolbar has single-image download only and contains no `.zip`
  package action.
- History titles and descriptions stay on one ellipsized line, while their full
  text remains available by hover, focus, click, and touch in a bounded,
  wrapping, internally scrollable tooltip.
- Every message is a toast; no message block sits in the layout.
- Dropdowns display `name` and submit `value`; verify against a real payload.
- `生成数量` lists `生成 1 张` through `生成 15 张` and its payload contains only
  the corresponding numeric `total` value.
- No Token value appears in the DOM, storage, logs, or any request other than the
  `token` request header.
- No horizontal scrolling at the five widths above.
