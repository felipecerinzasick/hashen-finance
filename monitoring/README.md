# Holdings monitor

GitHub Actions runs `monitoring/monitor.py` every other day. Claude searches for
new developments around the treasury-stock holdings, assesses whether each item
is positive, negative, or neutral for the thesis, emails a compact alert, and
writes dashboard JSON files under `monitoring/reports/`.

The dashboard pages read those JSON files, so each treasury page can show the
latest assessment at the bottom.

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
- likely price-impact assessment
- source-linked updates

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

This is a research monitor, not trading advice. It can miss items, misread
filings, or overstate market impact. Verify primary sources before acting.
