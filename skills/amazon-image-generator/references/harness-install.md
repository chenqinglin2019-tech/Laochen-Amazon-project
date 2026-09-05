# Codex Harness Website Installation

Use this workflow when the user asks to install or integrate 飞鱼神图 into a Codex Harness website. The app template was validated on Harness 0.20.1 and the missing-ingress behavior was reproduced on Harness 0.22.1. Always read the installed host guide because its current version remains authoritative.

## Start Without a Questionnaire

An explicit request to install this skill on the website authorizes the normal, reversible installation work inside the detected custom-app directory and the module's isolated same-origin API proxy described below. Inspect first, then proceed with these defaults instead of asking the user to choose them:

- App slug: `amazon-image-generator`
- Navigation name: `飞鱼神图`
- Page title: `飞鱼神图 · 亚马逊图片生成`
- Visibility: `root`
- Navigation order: `40`
- Navigation icon: follow the host navigation. The bundled Harness 0.20.1 manifest omits `icon` because the native primary navigation is text-only.
- Page behavior: standalone custom-app page with a visible `工作台` back link; do not imitate or duplicate the Harness navigation.
- Page design: `web/` reproduces the design baseline in `assets/reference-page/feiyushentu-page.html` 1:1, minus the transport layer. See `references/page-blueprint.md`. Do not redesign it during installation, and do not add demo mode or seeded data.
- Views: `#/` generation workbench and `#/history` generation history. History reads `GET /api/jobs?page=&size=&start=&end=`, which filters, sorts, and paginates in SQLite.
- Product images: local upload or a public image link, either one. Uploads go to `data/uploads/` and are served read-only from `files/uploads/`.
- Storage: app-owned SQLite plus `data/uploads/` and `data/generated/`.
- Token: configure or replace from the page; store only in `data/feiyushentu.toml`; never request it during installation.
- Backend: Python standard library, user `skilldeck`, loopback `127.0.0.1`, default port `39081`.
- Transport: the page works over HTTP and HTTPS. Public HTTP Token submission requires a visible risk acknowledgement. Do not claim HTTPS is configured merely because the page supports it.
- Existing app updates: back up and replace only app code; preserve `data/`, SQLite, Token, uploads, generated images, and logs.

Only ask when a safe default cannot resolve one of these conditions:

1. Codex Harness or the target custom-app root cannot be detected, or multiple plausible targets exist.
2. The target slug contains a different/unrecognized app or replacement could destroy unknown data.
3. The required same-origin backend route is absent and there is no pre-existing, verified per-site extension/include directory in the active Harness server block. Do not guess a path or modify the main site file.
4. A file or route conflict exists, including an unmanaged `amazon-image-generator.conf` or an existing route owned by another service.
5. The user asks for a public certificate or another external action that requires accepting third-party terms.
6. A port or existing process conflict cannot be resolved without changing unrelated services.

Combine related blockers into one concise question. Do not re-ask defaults already listed above.

## Required Host Inspection

1. Read `/opt/skilldeck/share/diy.md` completely. Treat its current version as authoritative.
2. Confirm `/var/lib/skilldeck-custom/apps/` and the `skilldeck` user/group exist.
3. Inspect an existing `amazon-image-generator` app before updating it.
4. Inspect the actual primary navigation before deciding whether an icon belongs in `app.json`.
5. Inspect the existing application-proxy route and loopback port. Identify the exact origin the user opens, including scheme and bound hostname; inspect that origin's active server block rather than an IP/default vhost. Reuse a working scoped route; do not add a second route.
6. Do not modify `/opt/skilldeck`, `/var/lib/skilldeck`, Harness databases/credentials, systemd, Caddy, the main Nginx/BT Panel site file, certificates, listeners, or unrelated routes. The only ingress exception included in an explicit 飞鱼神图 installation request is one managed `amazon-image-generator.conf` location file inside a pre-existing per-site extension/include directory already loaded by the active Harness server block.

## Install or Update

The bundled template contains no Token, SQLite database, uploads, generated files, PID, log, certificate, or site-specific proxy configuration.

Run from the installed skill directory:

```bash
python3 scripts/install_harness_app.py
```

The installer:

- validates that Codex Harness is present;
- recognizes the existing app before replacing code;
- stops only a verified backend process belonging to this app;
- backs up `app.json`, `web/`, and `backend/` under `.install-backups/`;
- installs the tested page and backend template;
- vendors the current `feiyushentu_amazon.py` helper;
- preserves all app-owned data and the Token;
- restores restrictive modes and `root:skilldeck` / `skilldeck:skilldeck` ownership;
- starts the loopback backend unless `--no-start` is passed.

For an installation-only staging pass:

```bash
python3 scripts/install_harness_app.py --no-start
```

The backend launcher accepts environment overrides when the detected Harness origin or reserved port differs:

```bash
HARNESS_ORIGIN="http://127.0.0.1:38080" FEIYUSHENTU_APP_PORT="39081" \
  python3 scripts/install_harness_app.py
```

Do not use these overrides until read-only inspection confirms the values.

## Existing Same-Origin Route

The frontend calls `/custom-api/amazon-image-generator/`. A working deployment therefore needs a same-origin route to the loopback backend. Reuse and verify it when present. Do not describe installation as complete until this public route reaches the backend health endpoint.

If the route is absent, inspect `nginx -T` and the active site includes to determine one exact, dedicated path named `amazon-image-generator.conf` inside a pre-existing per-site extension/include directory already loaded by the matching Harness server block. Match `server_name`, port, and TLS state to the actual browser origin; a file included only by an IP, default, HTTP-only, or different-domain vhost is not a match. In this verified safe case, configure it automatically without asking; the user's module-install request already authorizes this isolated API route:

```bash
python3 scripts/configure_harness_proxy.py \
  --config-file "/absolute/verified/server/include/amazon-image-generator.conf" \
  --backend-port 39081 \
  --verify-origin "https://actual-harness-domain.example" \
  --apply
```

Repeat `--verify-origin` for every active origin that must work, such as both `http://domain.example` and `https://domain.example`; redirects are followed. `--apply` is the helper's mutation switch, not a request for another user confirmation. The helper refuses unmanaged existing files and symlinks, writes only the dedicated location, runs `nginx -t`, reloads only after a valid test, then requires each public health response to be HTTP 200 JSON with `data.ok = true`. It rolls back and reloads the prior configuration when the route returns HTML, `null`, malformed JSON, a proxy error, or any unexpected envelope. Never guess the include directory, add a new include directive, edit the main site file, change certificates/listeners, or expose the backend on a public interface. If the verified dedicated location is unavailable or a conflict exists, stop with the exact evidence instead of asking the user to approve a broader change.

Capture the original site's status before applying the proxy. After success, verify that status again plus `/custom-api/amazon-image-generator/health`, `/api/bootstrap` through the public proxy while logged in, and a hard refresh of the module page. A `200` response containing Harness HTML is a failed/misrouted API, not success. If any check regresses, remove or restore only the managed file, validate and reload Nginx, then report the exact evidence. Do not claim a usable installation merely because the loopback health check passes.

## Remove the Website Module

An explicit request to delete, uninstall, or remove the 飞鱼神图 module authorizes a reversible removal from the live Harness app list. Do not ask whether to keep the database, Token, uploads, or generated images; preserve them by default.

Run:

```bash
python3 scripts/remove_harness_app.py
```

If installation created the verified managed API proxy, remove that proxy as part of the same module-removal request without asking again:

```bash
python3 scripts/configure_harness_proxy.py \
  --config-file "/absolute/verified/server/include/amazon-image-generator.conf" \
  --remove
```

Run proxy removal only when the exact file starts with `# managed-by: amazon-image-generator`. The helper archives the file beside the include directory, validates Nginx, rolls back on failure, and reloads after a valid test. Never remove an unmanaged or ambiguous route.

The remover:

- confirms the target is the manifest-identified `飞鱼神图` app;
- refuses to touch an unknown app, file, or conflicting directory;
- stops only a verified backend process belonging to this app;
- moves the entire app directory from `apps/` to a timestamped sibling under `/var/lib/skilldeck-custom/removed/`;
- preserves code, Token, SQLite, uploads, generated images, logs, certificates, and any app-owned backups;
- leaves the installed skill available for a later reinstall;
- removes only the separately managed API proxy when its exact path and management marker are verified; it does not modify Harness, systemd, the main Nginx/BT Panel site file, Caddy, certificates, listeners, or other website modules;
- succeeds safely when the app is already absent.

After removal, verify that the live app path and managed proxy file are absent, the backend port is no longer listening, the custom page and API route return `404`, and the original website still responds normally.

Do not permanently delete the timestamped archive unless the user separately and explicitly asks to destroy the retained data after being told what it contains. A generic request to “delete the module” is not authorization to purge the archive.

## Verification

Run the narrow checks that apply:

```bash
python3 -m json.tool /var/lib/skilldeck-custom/apps/amazon-image-generator/app.json
(cd /var/lib/skilldeck-custom/apps/amazon-image-generator && python3 -m unittest -v backend.test_server)
curl http://127.0.0.1:39081/health
```

Also confirm:

- the original website still responds normally;
- the custom entry redirects unauthenticated users to login;
- unauthenticated business API requests return `401`;
- `GET /api/v1/custom/apps` has no rejection for this app when an authenticated session is available;
- no Token appears in HTML, browser storage, responses, logs, process arguments, or backups;
- generated files remain under the app `data/` directory;
- HTTP support is described separately from actual HTTPS certificate availability.
- the exact public HTTP/HTTPS origin returns an application/json health envelope rather than the Harness HTML fallback page.

## Installed Feature Set

The bundled page provides local JPG/PNG/WebP upload (up to 6 files, 12 MB each), a fixed 1–15 generation-count selector whose labels are `生成 N 张` and whose submitted values are numeric-only, server-side Token configuration, model and style settings, asynchronous status tracking, distinct generation/archive errors, retry, responsive result gallery, local archive downloads, recent task history, SQLite persistence, root-only Harness session checks, CSRF validation, and HTTP risk acknowledgement.
