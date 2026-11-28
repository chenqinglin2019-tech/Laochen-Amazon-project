---
name: lc-ipr-risk-screening-free
description: 查一个 Amazon 商品（或用户给的产品资料）在一个目的国有没有专利、外观、商标、版权图案的侵权风险，几分钟出一份中文 HTML 报告。用户说"查侵权""侵权排查""能不能上架"并给了 Amazon 链接或产品资料时用。IP infringement risk screening for one Amazon product in one country.
---

# IP risk screening (v3.2.0)

Version 3.2.0. If the user asks which version this is, read the `VERSION` file in this folder and answer with that.

(The instructions below are in English on purpose: some shells show Chinese text in this file as garbage. Always answer the user in Chinese.)

`run.py` in this folder does the whole job in one command: product capture, searches, AI comparison, report. You do three things only: **run the command, wait for it to finish, relay what it printed**. Do not search for patents yourself, do not compare images yourself, do not rewrite its conclusions.

## Run

From this skill folder (on Windows use `py -3` instead of `python3`; if `py` is missing use `python`):

```bash
python3 run.py --url "<Amazon product link>"
```

- The target country defaults to the marketplace of the link. If the user names the country they will sell in, add `--country US` (one of US, GB, FR, DE, IT, ES, JP). One run covers one country. The US is covered most fully; parts that cannot be searched for other countries are reported as "not searched".
- No link, only a folder with product material (at least one product picture plus a product name or one-line description): `python3 run.py --input "<folder>" --country US --title "<product name>"`.
- Optional competitors (ASIN or link, up to 3): add `--competitor B0XXXXXXXX` once per competitor, or put `"competitors": [...]` in the folder's `product.json`. Their pages are captured for brand and patent markings. Never ask for competitors; use them only when the user gives them.
- A run usually takes 3-6 minutes, at most about 12. **Give the command a timeout of at least 15 minutes**, let it finish, do not interrupt it.
- It needs network access, opens a browser to capture the product page, starts its own AI sub-sessions, and writes task files under `ipr-runs` and `.lc-ipr` in the user's home folder. Allow all of that.
- Never run two commands for the same product at once. Two different products may run in parallel.

## After it finishes

After the numbered progress steps `[1/6]` to `[6/6]`, the command prints its final lines in Chinese: result, note, recovery time and how to resume (when it stopped early), a conclusion summary (overall risk level, confidence, advice, the level of each right type, and the items that need manual checking), the report path, and time used. Relay **all of these final lines to the user exactly as printed, in Chinese**, give the report path, and remind the user to open the report and manually check the listed items.

- **Do not open or read `report.html`.** It embeds images and is 1-2 MB; reading it only burns tokens. Everything you need is in the printed conclusion summary.
- Where the output says a right type is pending, not searched, or could not be compared, repeat exactly those words. Never turn them into "low risk" or "no problem".
- Do not add your own opinion on whether the product infringes.

## Four outcomes

| outcome | exit code | what you do |
|---|---|---|
| done | 0 | relay as above |
| stopped with an error | 1 | relay the note line. A report usually exists (not when the product data could not be captured). Running the same command again within 24 hours continues where it stopped; finished parts are not redone |
| AI quota used up | 3 | relay the recovery time. After that time, run the same command again |
| waiting for the user | 4 | Amazon asks for a captcha or login: ask the user to handle it in the browser window that opened, then run the same command again |

- To start over instead of continuing the previous run: add `--fresh`.
- The user gives a task folder to continue: `python3 run.py --task-dir "<task folder>"`.
- The user wants to share or archive one finished run: `python3 run.py --pack "<task folder>"` writes a zip next to it (no keys inside) and prints its path.
- It refuses to start (prints one line and exits with code 1 right away): relay the reason as printed (usually a bad link, failed authentication, or the same product is being checked in another window).

## First use, or the command says something is missing

Run `python3 install.py --check` (self-check only) and relay its output; the lines that failed carry the fix right after them. If it was never installed, run `install.py` without `--check`. Step-by-step instructions for the user are in the Chinese `.md` file next to this one.

## Do not

- Do not read, print or repeat the contents of `.env` or `config.json`.
- Apart from running `install.py`, do not change files in this folder; do not change the user's proxy or system settings.
- Do not treat intermediate files in the task folder as conclusions.
