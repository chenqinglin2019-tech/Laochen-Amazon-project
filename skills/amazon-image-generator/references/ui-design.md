# Website UI Integration

Use these rules only when integrating 飞鱼神图 into a separate calling website. Do not add website code to the `amazon-image-generator` skill repository.

## Page Baseline

The page has a fixed design baseline. Read `references/page-blueprint.md` and the
file it points at, `assets/reference-page/feiyushentu-page.html`, before designing
or building anything. Reproduce that page 1:1: same layout, tokens, components,
and interaction behaviour. Do not redesign it, and do not restate its structure
from memory — copy it from the baseline file.

The baseline carries no demo mode and no seeded data. Never add either.

Only two things are expected to differ per integration: the transport (a
production site proxies the FeiyuShentu API through its own backend instead of
sending a Token from the browser) and the history endpoint path. When the host
site has its own design system, follow the token-substitution rule at the end of
the blueprint; structure and behaviour still do not change.

## UI Skill Dependency

1. Resolve the Codex skills directory as `${CODEX_HOME:-$HOME/.codex}/skills`.
2. Check for `ui-ux-pro-max/SKILL.md`.
3. If present, do not reinstall or overwrite it. Read its `SKILL.md` completely and invoke `$ui-ux-pro-max` for the UI task.
4. If absent, use `$skill-installer` to install:

```text
https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/tree/main/.claude/skills/ui-ux-pro-max
```

5. After installation, invoke `$ui-ux-pro-max` on the next available turn and continue the website task.

The current skill's `install.sh` performs the same conditional check during installation.

## Design Workflow

1. Read `references/page-blueprint.md` and `assets/reference-page/feiyushentu-page.html` first. They define what to build; the steps below decide how it fits the host project.
2. Inspect the calling project's repository-level instructions, stack, existing navigation, route registration, components, design tokens, authentication, API conventions, and database layer.
3. Preserve existing stable flows. Make only the smallest necessary navigation and route additions; do not refactor unrelated logic.
4. Detect the actual frontend stack before querying `ui-ux-pro-max`. Do not assume a framework.
5. For a new page, run the installed UI design search tool with a product-focused query before implementation:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/ui-ux-pro-max/scripts/search.py" \
  "Amazon AI product image generator workspace modern clear trustworthy" \
  --design-system \
  -p "飞鱼神图"
```

6. Query the detected stack separately with `--stack <stack>` when stack-specific guidance is needed.
7. Treat the calling site's existing design system as authoritative for colors, typography, and spacing. It does not override the baseline's layout, components, or interaction behaviour.
8. Before delivery, read the installed UI skill's `references/pro-rules.md` and complete its pre-delivery checks, then the delivery checks at the end of `references/page-blueprint.md`.

## Naming

- Navigation label: `飞鱼神图`.
- Page title: `飞鱼神图 · 亚马逊图片生成`.
- Route segment and code directory: `amazon-image-generator`.
- Recommended route: `/amazon-image-generator`.

Follow the calling project's naming convention when it requires a prefix, locale segment, nested tool route, or framework-specific directory.

## Required Page Capabilities

- Token state: show only `已配置` or `未配置`.
- Token replacement: use an empty password-style input for the new Token. Never fetch, prefill, reveal, or mask the stored value.
- Product input: title, description, generation count, model, model settings, style, language, scene, and one or more reference images. Generation count is a fixed 1–15 dropdown: display `生成 N 张`, submit only `N` as the `total` value, and do not wait for API configuration to provide these options.
- Upload feedback: preview selected images, allow removal before submission, and show clear upload errors.
- Generation feedback: represent queued, generating, success, generation failure, timeout, archive partial, and archive failure as distinct states.
- Results: show generated images in a responsive gallery with original URL state, local archive state, retry-download action, and accessible download controls. The preview dialog offers only single-image download; packaged `.zip` download remains in the result/history UI and must not appear in the preview toolbar.
- Generation history: a second view listing past generations with server-side date filtering and pagination, per-row preview, single download, and packaged `.zip` download. Title and description are each one line with an ellipsis; expose their full text in a shared viewport-safe tooltip on hover, keyboard focus, click, and touch. The tooltip wraps long content and uses bounded width/height with internal scrolling. Serve history from the calling website's own database using the contract in `references/api.md`.
- Messages: show transient messages as toasts. Never insert a message block into the page layout. Field validation errors stay next to the field and keep the user's input.
- Persistence: let the calling website store task IDs, parameters, statuses, URLs, local paths, image metadata, and errors in its own database. It owns the history endpoint.

## Interaction and Accessibility

- Use visible labels; do not rely on placeholders as labels.
- Preserve visible keyboard focus and logical tab order.
- Provide accessible names for icon-only controls and use SVG icons instead of emoji icons.
- Keep interactive targets at least `44 × 44px` with sufficient spacing.
- Meet at least WCAG AA contrast (`4.5:1` for normal text).
- Announce async status changes with appropriate live-region semantics without excessive repetition.
- Disable duplicate submissions while a request is active, but keep cancellation or recovery actions reachable when supported.
- Show errors next to the affected field or task and retain the user's valid input.
- Reserve image-card dimensions to avoid layout shifts; lazy-load result images when appropriate.
- Fit oversized preview images inside the current visual viewport at the default scale. Derive a concrete pixel width and height from the dialog's rendered size and padding; do not rely only on percentage `max-height`. User zoom may exceed the viewport, and the zoomed image must support pointer/touch dragging. Provide an accessible reset control that restores the fitted scale, zero rotation, and centred pan position after zooming or dragging.
- Respect `prefers-reduced-motion`; use motion only to clarify state transitions.
- Verify responsive behavior at `375px`, `768px`, `1024px`, and `1440px` without horizontal scrolling.

## Delivery Checks

- Confirm the delivered page matches `assets/reference-page/feiyushentu-page.html` 1:1 and completes the delivery checks in `references/page-blueprint.md`.
- Confirm no demo mode and no seeded data shipped.
- Confirm the page is reachable from the agreed navigation entry and direct route.
- Confirm refresh and back/forward navigation preserve correct state according to the calling project.
- Confirm no Token value appears in HTML, serialized page data, browser storage, network responses, logs, or error messages.
- Confirm generated files are stored in the calling website's data directory, never inside either skill directory.
- Confirm database failures do not delete already archived files or lose source URLs needed for recovery.
- Run the calling project's narrowest relevant typecheck, tests, lint, and build.
