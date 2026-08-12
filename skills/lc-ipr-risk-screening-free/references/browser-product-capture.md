# Amazon browser capture contract

Use visible Chrome desktop through `tools/cdp/cdp-cli.mjs capture-amazon`. Run credential preflight first. The CDP launcher uses a dedicated non-default profile and a loopback-only random port. Do not inspect cookies, local storage, the default browser profile, or passwords. If Amazon requires authentication or CAPTCHA, preserve the visible page and let the user complete it.

Save a UTF-8 JSON object with:

```json
{
  "browser": "chrome_desktop",
  "capture_transport": "cdp",
  "browser_version": "Chrome/150.0.7871.187",
  "protocol_version": "1.3",
  "cdp_session_id": "sanitized-session-id",
  "status": "success",
  "requested_url": "https://www.amazon.com/dp/B012345678",
  "final_url": "https://www.amazon.com/dp/B012345678",
  "requested_asin": "B012345678",
  "actual_asin": "B012345678",
  "variant": {"label": "Color", "value": "Black", "confirmed": true},
  "title": "...",
  "brand": "...",
  "manufacturer": "...",
  "category": "...",
  "bullets": ["..."],
  "specifications": {"Material": "..."},
  "structure": ["..."],
  "visible_ip_claims": ["..."],
  "ocr_text": ["..."],
  "visual_features": ["..."],
  "main_image": {
    "path": "/absolute/run/images/main.jpg",
    "source_url": "https://m.media-amazon.com/images/I/...",
    "width": 1600,
    "height": 1600,
    "format": "JPEG",
    "sha256": "..."
  },
  "screenshots": {
    "product_core": "/absolute/run/screenshots/product-core.png",
    "product_details": "/absolute/run/screenshots/product-details.png"
  },
  "collected_at": "2026-01-01T00:00:00Z"
}
```

For a robot check, use `status: robot_check`, include the CDP provenance fields, `requested_url`, `final_url`, and a screenshot path. Do not guess product fields. The ingestion script requires a final URL on the requested Amazon host containing the actual ASIN, title/category, an Amazon media HTTPS main-image URL, a recent timezone-aware collection time, file containment, hashes, image magic bytes/dimensions, current-variant confirmation, and two screenshots. It calculates screenshot hashes itself.

Never place an endpoint, WebSocket URL, debugging port, profile path, cookies, local storage, or passwords in the capture. `cdp_session_id` is a random, non-secret correlation value and cannot encode the endpoint or profile.
