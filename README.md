# Laochen Amazon Project

Public repository for Laochen Amazon workflow skills.

## Skills

- `skills/lc-amazon-profit-calculator/` - 易逊-亚马逊商品毛利计算。
  Read Amazon product data, open an editable form inside Codex, compare low/peak
  storage profit scenarios, and automatically save inputs and results locally.
  Version 2.1.0; includes 11-marketplace rule paths and explicit fee coverage limits.
  Last updated: 2026-10-25 (UTC+8).
  [Detailed PRD](skills/lc-amazon-profit-calculator/references/product-prd-v2.1.md).
- `skills/amazon-listing-image-studio/` - Build non-copycat Amazon listing image
  systems from product photos, selling points, and competitor references.
- `skills/lc_amazon_listing/` - Generate Amazon listings from fully imported
  user XLSX/CSV/TSV keyword files, with intent-group decisions, coverage
  feedback, and incremental validation. Last updated: 2026-10-02 (UTC+8).
- `skills/lc-amazon-listing-asin/` - Generate Amazon listings from competitor
  ASIN sets, product images, and product descriptions, with intent-group
  keyword decisions, coverage feedback, and incremental validation.
  Last updated: 2026-10-01 (UTC+8).
- `skills/lc-amazon-image-studio/` - Create Amazon Listing and A+ image sets
  from verified product assets, with user reference template intake, local
  typography, product-consistency QA, and cross-platform runtime setup (V7).
  Last updated: 2026-10-04 (UTC+8).
- `skills/lc-amazon-data-crawl/` - Crawl Amazon keyword searches, storefronts,
  and image-similar competitors through background OpenCLI tabs in daily Chrome;
  category ranking retains CDP. Includes native-format exports and merging,
  streaming visual prescreening, and checkpoint recovery.
  Last updated: 2026-10-14 (UTC+8).
- `skills/lc_amazon_competitor_promotion/` - Analyze competitor promotion,
  pricing, ads, reviews, seasonality, Woot signals, and optional offsite traces.
- `skills/lc_amazon_market_opportunity/` - Continue from market research into
  feature tagging, dual-source candidate review, a robust Top3 shortlist, and
  frozen-market keyword/ad metrics with the fixed two-round report.
  Last updated: 2026-10-12 (UTC+8).
- `skills/lc_amazon_voc_to_product/` - Develop one selected segment through
  traceable consumer evidence, KANO, a twelve-role product workshop, and the
  fixed offline report template. Includes scripts, schemas, tests and templates.
  Last updated: 2026-10-12 (UTC+8).
- `skills/lc_amazon_market_research/` - Generate Amazon market research reports
  from SellerSprite Excel exports. Last updated: 2026-07-30 23:42 (UTC+8).
- `skills/lc_amazon_niche/` - Score and rank Amazon niche candidates by seller
  profile.
- `skills/lc-ipr-risk-screening/` - Screen one US Amazon product through V2
  cloud discovery and optional local Serper searches, with full-batch candidate
  disposition, a single seven-module review, and offline evidence-bound reports.
  Includes CLI binaries for macOS (Intel and Apple Silicon), Linux, and Windows.
  Version 1.0.3. Last updated: 2026-10-27 (UTC+8).
- `skills/lc-ipr-risk-screening-free/` - Discover and review IPR candidates through
  free-tier APIs, with independent final review and relevant official evidence.
  Includes the fixed seven-section risk report, evidence-based query completion,
  and a default of unavailable structural information when users supply none.
  Preserves the authentication contract and ships blank config.json and .env.
  Credentials supplied in chat are saved locally without echoing their values.
  Last updated: 2026-10-02 (UTC+8).
  [Installation and platform validation](skills/lc-ipr-risk-screening-free/references/installation.md).

- `skills/lc-amazon-compliance-screening/` - Screen single products and selection
  spreadsheets across ten Amazon marketplaces using versioned compliance rules.
  Version 1.2.4; requires the user's own token and skill authorization.
  Includes four-platform authorization programs; macOS Apple Silicon validated,
  other platforms await real-device validation. Last updated: 2026-10-14 (UTC+8).
  [Installation and authorization](skills/lc-amazon-compliance-screening/README.md).

## Install Path

Use this repository with the skill subpath you want:

```text
https://github.com/chenqinglin2019-tech/Laochen-Amazon-project
skills/<skill-name>
```

Direct folder URLs:

```text
https://github.com/chenqinglin2019-tech/Laochen-Amazon-project/tree/main/skills/lc-amazon-profit-calculator
https://github.com/chenqinglin2019-tech/Laochen-Amazon-project/tree/main/skills/amazon-listing-image-studio
https://github.com/chenqinglin2019-tech/Laochen-Amazon-project/tree/main/skills/lc-amazon-listing-asin
https://github.com/chenqinglin2019-tech/Laochen-Amazon-project/tree/main/skills/lc-amazon-image-studio
https://github.com/chenqinglin2019-tech/Laochen-Amazon-project/tree/main/skills/lc-amazon-data-crawl
https://github.com/chenqinglin2019-tech/Laochen-Amazon-project/tree/main/skills/lc_amazon_competitor_promotion
https://github.com/chenqinglin2019-tech/Laochen-Amazon-project/tree/main/skills/lc_amazon_market_opportunity
https://github.com/chenqinglin2019-tech/Laochen-Amazon-project/tree/main/skills/lc_amazon_voc_to_product
https://github.com/chenqinglin2019-tech/Laochen-Amazon-project/tree/main/skills/lc_amazon_market_research
https://github.com/chenqinglin2019-tech/Laochen-Amazon-project/tree/main/skills/lc_amazon_niche
https://github.com/chenqinglin2019-tech/Laochen-Amazon-project/tree/main/skills/lc-ipr-risk-screening
https://github.com/chenqinglin2019-tech/Laochen-Amazon-project/tree/main/skills/lc-ipr-risk-screening-free
https://github.com/chenqinglin2019-tech/Laochen-Amazon-project/tree/main/skills/lc-amazon-compliance-screening
```

## Security

Do not commit backend tokens, cookies, API keys, or local credential files.

The two Listing skills ship blank `config.json` files and save user-supplied
backend tokens locally through `scripts/configure_credentials.py` without
echoing them. They use the existing backend CLI credential route.

The market opportunity and VOC skills ship `config.json` with an empty
`backend_token`. Configure it locally before authenticated use. The VOC backend
configuration requires file permissions `0600` on Unix (`chmod 600 config.json`).
Provider `.env` files, API keys, browser state, and collection outputs are excluded;
only credential-free provider examples are included. Local credential files and
existing authentication behavior are unchanged by this publication.
