"""
Treasury-holdings monitor.

Runs from GitHub Actions every other day. It asks Claude with web search for
new developments on the monitored treasury holdings, emails a compact alert when
something new appears, and writes JSON reports for the dashboard.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "state.json"
REPORT_DIR = ROOT / "reports"

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
MODE = os.environ.get("MODE", "alert").lower()
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "3" if MODE == "alert" else "8"))
MAX_SEARCHES = int(os.environ.get("MAX_SEARCHES", "14"))
BASE_URL = os.environ.get("BASE_URL", "https://hashen-finance.onrender.com").rstrip("/")

HOLDINGS = [
    {
        "slug": "mstr",
        "name": "Strategy",
        "ticker": "MSTR",
        "dashboard_path": "/dashboard/mstr/",
        "thesis": (
            "High-beta Bitcoin treasury wrapper. Judge it in BTC terms: sats per "
            "share, BTC per diluted share, mNAV premium, financing quality, and "
            "whether capital markets activity grows BTC per share."
        ),
        "checklist": [
            "New BTC purchases and whether BTC per diluted share rises",
            "ATM/common issuance, convertibles, preferreds, debt, and credit-stack changes",
            "Financing priced attractively or dangerously versus mNAV / BTC NAV",
            "SEC filings, company press releases, and Michael Saylor / Strategy statements",
            "Governance, accounting, custody, or leverage changes",
            "Major analyst/governance critiques, index decisions, or institutional ownership changes",
        ],
    },
    {
        "slug": "metaplanet",
        "name": "Metaplanet",
        "ticker": "3350.T / MTPLF / DN3.F",
        "dashboard_path": "/dashboard/stocks/treasury/metaplanet/",
        "thesis": (
            "Japan Bitcoin treasury equity. The thesis improves when financing is "
            "accretive to BTC per share, mNAV expands for durable reasons, and "
            "governance stays aligned. The thesis weakens with dilutive issuance, "
            "loose warrants, insider selling, or large-holder reductions."
        ),
        "checklist": [
            "New common share issuance, moving-strike warrants, or convertibles priced near or below 1.0x mNAV",
            "EDINET large-shareholding changes, especially Capital Group / Capital Research reductions or increases",
            "Share buyback actually executed, not merely authorized, especially below 1.0x mNAV",
            "Compensation plan changes and whether performance conditions are real or weak",
            "Series 10 terms, lock-up waivers, strike changes, or loosening of existing rights",
            "Preferred-share financing or debt on good terms instead of common-equity dilution",
            "Analyst or governance critiques about dilution, mNAV, BTC Yield, warrants, or management incentives",
            "MSCI index inclusion/exclusion/decision updates and likely flow implications",
            "BTC purchases, BTC Yield, BTC per fully diluted share, and whether purchases are accretive",
        ],
    },
    {
        "slug": "asst",
        "name": "Asset Entities / Strive",
        "ticker": "ASST",
        "dashboard_path": "/dashboard/stocks/treasury/asst/",
        "thesis": (
            "Small, high-beta Bitcoin treasury wrapper. Upside depends on credible "
            "execution and market trust; downside comes from liquidity, dilution, "
            "governance, or failure to build a durable Bitcoin-per-share story."
        ),
        "checklist": [
            "SEC filings and company releases on Bitcoin treasury policy or purchases",
            "Share issuance, reverse splits, warrants, registration statements, and liquidity events",
            "Financing terms versus implied Bitcoin NAV and existing shareholders",
            "Strive-related governance, management, custody, or policy changes",
            "Audited filings, going-concern language, internal-control issues, and risk disclosures",
            "Institutional ownership changes or activist/governance critiques",
        ],
    },
    {
        "slug": "bitmine",
        "name": "BitMine Immersion",
        "ticker": "BMNR",
        "dashboard_path": "/dashboard/stocks/treasury/bitmine/",
        "thesis": (
            "Highest-risk treasury sleeve, linked to Ethereum treasury exposure. "
            "The thesis improves with credible ETH accumulation, staking or custody "
            "economics, and disciplined financing; it weakens with dilution, weak "
            "governance, or narrative-only announcements."
        ),
        "checklist": [
            "SEC filings and company releases on ETH treasury purchases and ETH per share",
            "Financing terms, issuance, warrants, convertibles, or shelf registrations",
            "Tom Lee / management commentary with concrete treasury-policy implications",
            "Custody, staking, validator, counterparty, or treasury-risk disclosures",
            "Governance critiques, insider transactions, institutional ownership, or audit issues",
            "Ethereum treasury-sector developments that directly affect BitMine's positioning",
        ],
    },
]

SYSTEM = """You are a disciplined equity research assistant for a private owner.

Today's date is {today}. Search the web for developments from the last {days}
days only. Monitor these holdings:

{holdings}

Rules:
- Search primary sources first for each company: company IR disclosures and press
  releases, metaplanet.jp IR disclosures for Metaplanet, SEC EDGAR, TSE timely
  disclosures, EDINET, and other exchange filings.
- Use reputable financial news only when no primary source is available.
- Label "primary source" only when the source is a filing, company release, company
  IR disclosure, exchange disclosure, EDGAR, EDINET, or TSE timely disclosure.
- Do not invent numbers. If a number is unavailable, use null or say unavailable.
- Skip items in ALREADY REPORTED unless there is a material update.
- Focus on management actions, financing, dilution, treasury purchases, custody,
  shareholder changes, strategy shifts, regulation, earnings, and capital markets.
- Do not report ordinary share-price moves as items. Put share price only in the
  company snapshot.
- Put sector-wide macro news once in the separate "sector" section, not repeated
  under every company.
- Assess whether each item is positive, negative, or neutral for the stock thesis.
- Cross-check figures across items. If two sources conflict on the same figure
  such as BTC holdings, share count, mNAV, financing size, strike price, or index
  date, say so in "source_conflicts" and in the relevant item.

Finish with ONE fenced ```json block and nothing after it, in this schema:
{{
  "reports": [
    {{
      "slug": "mstr|metaplanet|asst|bitmine",
      "snapshot": {{"holdings": string|null, "share_price": number|null,
                    "mnav": number|null, "as_of": "YYYY-MM-DD"|null}},
      "overall_verdict": "positive" | "negative" | "neutral",
      "email_summary": "one short sentence for an email preview",
      "bottom_line": "2 sentences max on the net effect for the thesis",
      "source_conflicts": ["short conflict note"],
      "updates": [
        {{
          "date": "YYYY-MM-DD",
          "headline": "max 12 words",
          "what_happened": "2-3 concrete sentences in your own words",
          "assessment": "positive" | "negative" | "neutral",
          "thesis_fit": "one sentence tying it to the holding thesis",
          "severity": "alert" | "digest",
          "confidence": "primary source" | "secondary only" | "unconfirmed",
          "source_url": "https://..."
        }}
      ]
    }}
  ],
  "sector": {{
    "bottom_line": "one sentence on relevant sector-wide macro news or empty string",
    "updates": [
      {{
        "date": "YYYY-MM-DD",
        "headline": "max 12 words",
        "what_happened": "2-3 concrete sentences",
        "assessment": "positive" | "negative" | "neutral",
        "severity": "alert" | "digest",
        "confidence": "primary source" | "secondary only" | "unconfirmed",
        "source_url": "https://..."
      }}
    ]
  }}
}}

Use "severity": "alert" for material thesis-changing positives or negatives.
Use "digest" for routine but relevant updates. Empty updates are fine.
"""


def holdings_prompt() -> str:
    chunks = []
    for holding in HOLDINGS:
        chunks.append(
            f"- {holding['slug']} / {holding['name']} / {holding['ticker']}\n"
            f"  Thesis: {holding['thesis']}\n"
            f"  Checklist: {'; '.join(holding['checklist'])}\n"
            f"  Dashboard: {BASE_URL}{holding['dashboard_path']}"
        )
    return "\n".join(chunks)


def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"seen": []}


def save_state(state: dict[str, Any]) -> None:
    state["seen"] = state.get("seen", [])[-500:]
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def item_id(slug: str, item: dict[str, Any]) -> str:
    key = "|".join([
        slug,
        str(item.get("source_url") or ""),
        str(item.get("headline") or "").lower(),
        str(item.get("date") or ""),
    ])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]


def parse_json(text: str) -> dict[str, Any]:
    blocks = re.findall(r"```json\s*(.*?)```", text, flags=re.S)
    raw = blocks[-1] if blocks else text[text.find("{"): text.rfind("}") + 1]
    data = json.loads(raw)
    data.setdefault("reports", [])
    data.setdefault("sector", {"bottom_line": "", "updates": []})
    return data


def normalize_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = snapshot or {}
    return {
        "holdings": snapshot.get("holdings"),
        "share_price": snapshot.get("share_price"),
        "mnav": snapshot.get("mnav"),
        "as_of": snapshot.get("as_of"),
    }


def ask_claude(already_reported: list[str]) -> dict[str, Any]:
    import anthropic

    client = anthropic.Anthropic()
    today = dt.date.today().isoformat()
    messages = [{
        "role": "user",
        "content": (
            "Run the holdings monitoring sweep now.\n\n"
            "ALREADY REPORTED (skip these unless materially updated):\n"
            + ("\n".join(f"- {item}" for item in already_reported[-120:]) or "- none")
        ),
    }]

    for _ in range(5):
        response = client.messages.create(
            model=MODEL,
            max_tokens=7000,
            system=SYSTEM.format(
                today=today,
                days=LOOKBACK_DAYS,
                holdings=holdings_prompt(),
            ),
            messages=messages,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": MAX_SEARCHES,
            }],
        )
        if response.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": response.content})

    text = "\n".join(block.text for block in response.content if block.type == "text")
    return parse_json(text)


def normalize_report(report: dict[str, Any]) -> dict[str, Any]:
    slugs = {holding["slug"]: holding for holding in HOLDINGS}
    slug = str(report.get("slug") or "").lower()
    holding = slugs.get(slug, {})
    return {
        "slug": slug,
        "name": holding.get("name", report.get("name", slug)),
        "ticker": holding.get("ticker", report.get("ticker", "")),
        "dashboard_url": f"{BASE_URL}{holding.get('dashboard_path', '')}",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "snapshot": normalize_snapshot(report.get("snapshot")),
        "overall_verdict": report.get("overall_verdict") or "neutral",
        "email_summary": report.get("email_summary") or "No material change.",
        "bottom_line": report.get("bottom_line") or "No material change to the thesis.",
        "source_conflicts": report.get("source_conflicts") or [],
        "updates": report.get("updates") or [],
    }


def write_reports(reports: list[dict[str, Any]], sector: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    latest = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "reports": reports,
        "sector": sector,
    }
    (REPORT_DIR / "latest.json").write_text(json.dumps(latest, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORT_DIR / "sector.json").write_text(json.dumps(sector, indent=2, ensure_ascii=False), encoding="utf-8")
    for report in reports:
        if report.get("slug"):
            (REPORT_DIR / f"{report['slug']}.json").write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )


def render_email(
    reports: list[dict[str, Any]],
    new_updates: list[tuple[dict[str, Any], dict[str, Any]]],
    sector: dict[str, Any],
    new_sector_updates: list[dict[str, Any]],
) -> tuple[str, str]:
    assessments = [update.get("assessment") for _, update in new_updates]
    assessments += [update.get("assessment") for update in new_sector_updates]
    positives = sum(assessment == "positive" for assessment in assessments)
    negatives = sum(assessment == "negative" for assessment in assessments)
    neutrals = len(assessments) - positives - negatives
    subject = f"Holdings monitor: {positives} positive / {negatives} negative / {neutrals} neutral"

    lines = [
        f"Holdings monitor - {dt.date.today():%d %b %Y}",
        "",
        "SHORT VERSION",
    ]
    for report in reports:
        report_updates = [update for item_report, update in new_updates if item_report["slug"] == report["slug"]]
        if report_updates:
            lines.append(f"- {report['name']}: {report.get('email_summary')}")
    if new_sector_updates:
        lines.append(f"- Sector: {sector.get('bottom_line') or 'Sector-wide update.'}")

    lines += ["", "READ MORE"]
    for report in reports:
        if any(existing["slug"] == report["slug"] for existing, _ in new_updates):
            lines.append(f"- {report['name']}: {report['dashboard_url']}")

    lines += ["", "DETAILED ASSESSMENT"]
    for report in reports:
        report_updates = [update for item_report, update in new_updates if item_report["slug"] == report["slug"]]
        if not report_updates:
            continue
        snapshot = report.get("snapshot") or {}
        lines += [
            "",
            f"{report['name']} ({report['ticker']})",
            "Snapshot: "
            f"holdings={snapshot.get('holdings')} | "
            f"share price={snapshot.get('share_price')} | "
            f"mNAV={snapshot.get('mnav')} | "
            f"as of={snapshot.get('as_of')}",
            f"Dashboard: {report['dashboard_url']}",
            f"Bottom line: {report.get('bottom_line')}",
        ]
        if report.get("source_conflicts"):
            lines.append("Source conflicts: " + "; ".join(report["source_conflicts"]))
        for update in report_updates:
            lines += [
                f"Update: {update.get('headline')} ({update.get('date')})",
                f"What happened: {update.get('what_happened')}",
                f"Assessment: {str(update.get('assessment')).upper()} - {update.get('thesis_fit')}",
                f"Confidence: {update.get('confidence')}",
                f"Source: {update.get('source_url')}",
                "",
            ]

    if new_sector_updates:
        lines += ["", "SECTOR"]
        if sector.get("bottom_line"):
            lines.append(f"Bottom line: {sector.get('bottom_line')}")
        for update in new_sector_updates:
            lines += [
                f"Update: {update.get('headline')} ({update.get('date')})",
                f"What happened: {update.get('what_happened')}",
                f"Assessment: {str(update.get('assessment')).upper()}",
                f"Confidence: {update.get('confidence')}",
                f"Source: {update.get('source_url')}",
                "",
            ]
    lines += ["", "Automated research summary. Verify sources before acting. Not investment advice."]
    return subject, "\n".join(lines)


def smtp_defaults(user: str) -> tuple[str, int, bool]:
    domain = user.split("@")[-1].lower()
    if "yahoo" in domain:
        return "smtp.mail.yahoo.com", 465, True
    if "gmail" in domain:
        return "smtp.gmail.com", 465, True
    if "outlook" in domain or "hotmail" in domain or "live" in domain:
        return "smtp.office365.com", 587, False
    return "smtp.gmail.com", 465, True


def send_email(subject: str, body: str) -> None:
    user = os.environ["SMTP_USER"]
    default_host, default_port, default_ssl = smtp_defaults(user)
    host = os.environ.get("SMTP_HOST", default_host)
    port = int(os.environ.get("SMTP_PORT", str(default_port)))
    use_ssl = os.environ.get("SMTP_SSL", "1" if default_ssl else "0") == "1"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = user
    message["To"] = os.environ.get("MAIL_TO", user)
    message.set_content(body)

    if use_ssl:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context()) as smtp:
            smtp.login(user, os.environ["SMTP_PASSWORD"])
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(user, os.environ["SMTP_PASSWORD"])
            smtp.send_message(message)


def load_sample() -> dict[str, Any]:
    return {
        "reports": [{
            "slug": "metaplanet",
            "snapshot": {
                "holdings": None,
                "share_price": None,
                "mnav": None,
                "as_of": dt.date.today().isoformat(),
            },
            "overall_verdict": "neutral",
            "email_summary": "Sample monitor run.",
            "bottom_line": "This is a dry-run sample so the dashboard panel can be tested.",
            "source_conflicts": [],
            "updates": [{
                "date": dt.date.today().isoformat(),
                "headline": "Sample monitoring item",
                "what_happened": "This sample item proves the monitor can render email and dashboard output.",
                "assessment": "neutral",
                "thesis_fit": "No thesis change because this is a sample.",
                "severity": "digest",
                "confidence": "unconfirmed",
                "source_url": f"{BASE_URL}/dashboard/stocks/treasury/metaplanet/",
            }],
        }],
        "sector": {
            "bottom_line": "No sector-wide sample update.",
            "updates": [],
        },
    }


def main() -> int:
    state = load_state()
    seen_ids = {entry.get("id") for entry in state.get("seen", [])}
    already_reported = [entry.get("label", "") for entry in state.get("seen", [])]

    data = load_sample() if os.environ.get("SAMPLE_DATA") else ask_claude(already_reported)
    reports = [normalize_report(report) for report in data.get("reports", []) if report.get("slug")]
    sector = data.get("sector") or {"bottom_line": "", "updates": []}
    sector.setdefault("updates", [])
    write_reports(reports, sector)

    new_updates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for report in reports:
        for update in report.get("updates", []):
            update_key = item_id(report["slug"], update)
            if update_key not in seen_ids:
                new_updates.append((report, update))
    new_sector_updates = []
    for update in sector.get("updates", []):
        update_key = item_id("sector", update)
        if update_key not in seen_ids:
            new_sector_updates.append(update)

    to_send = new_updates
    if to_send or new_sector_updates:
        subject, body = render_email(reports, to_send, sector, new_sector_updates)
        if os.environ.get("DRY_RUN"):
            print(subject)
            print()
            print(body)
        else:
            send_email(subject, body)
        for report, update in to_send:
            state.setdefault("seen", []).append({
                "id": item_id(report["slug"], update),
                "label": f"{report['slug']}: {update.get('headline')}",
                "date": update.get("date"),
            })
        for update in new_sector_updates:
            state.setdefault("seen", []).append({
                "id": item_id("sector", update),
                "label": f"sector: {update.get('headline')}",
                "date": update.get("date"),
            })
        save_state(state)
    else:
        print("No new holding updates. Reports were refreshed; no email sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
