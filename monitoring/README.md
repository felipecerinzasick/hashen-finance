# Holdings monitor

GitHub Actions runs `monitoring/monitor.py` once a week (Monday 07:20 UTC). Claude searches for
new developments around the treasury-stock holdings, assesses whether each item
is positive, negative, or neutral for the thesis, emails a compact alert, and
writes dashboard JSON files under `monitoring/reports/`.

The monitor runs one Claude sweep per holding plus one small sector sweep. If a
single company response fails to produce valid JSON, the script asks once for a
no-search JSON repair, skips only that company if repair fails, and continues.
The email calls out failed company sweeps at the top. The workflow exits with
code 0 when at least one company succeeds and code 1 only when every company
sweep fails.

The dashboard pages read those JSON files, so each treasury page can show the
latest assessment at the bottom.

## Archive

Every run also appends a compact copy of each company assessment (and the
sector sweep) to `monitoring/reports/history/<slug>.json`, newest first, capped
at 104 entries (two years of weekly runs). The dashboard shows these under
"Archive" in the Management Monitor panel, so earlier verdicts and their
source-linked updates stay readable after the live report is replaced. The
files are committed by the workflow like the rest of `monitoring/reports/`.

## Cost and cadence

One full sweep (four holdings plus the sector check) uses roughly 1.3 million
input tokens and about 45 web searches on `claude-sonnet-5`, which is about
4-5 USD. The weekly schedule therefore costs at most about 5 USD per week. The
workflow sets `LOOKBACK_DAYS=8` so a weekly alert run still covers the whole
gap since the previous sweep. To change the model, set `CLAUDE_MODEL` in the
workflow environment.

## Required GitHub secrets

- `ANTHROPIC_API_KEY`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `MAIL_TO`

Optional:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_SSL`

If `SMTP_HOST` is not set, the script infers a reasonable default from
`SMTP_USER` for Gmail, Yahoo, or Outlook/Hotmail.

## What is monitored

- `mstr`: Strategy / MSTR
- `metaplanet`: Metaplanet
- `asst`: Asset Entities / Strive
- `bitmine`: BitMine Immersion

Each report includes:

- short email summary
- overall verdict
- bottom-line thesis assessment
- company snapshot: holdings, share price, mNAV, and as-of date where available
- source-conflict notes when reported figures disagree
- source-linked updates
- one separate sector section for macro news that affects the group

## Manual test

In GitHub Actions, run **Holdings monitor** manually.

For a no-network dashboard/email-format test, set:

- `mode`: `alert`
- `sample_data`: `1`

Local dry run:

```bash
SAMPLE_DATA=1 DRY_RUN=1 python monitoring/monitor.py
```

## Notes

The monitor is instructed to search primary sources first: company IR releases,
filings, SEC EDGAR, EDINET, and exchange disclosures. It labels an item as
"primary source" only when it comes from a filing or company/exchange release.
Every Claude response logs `stop_reason`, `usage`, and the last 500 characters
of model text to the GitHub Actions log so parse failures can be diagnosed.

This is a research monitor, not trading advice. It can miss items or misread
filings. Verify primary sources before acting.
