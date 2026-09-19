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
        "watch": [
            "Bitcoin purchases and BTC per diluted share",
            "ATM/common issuance, convertibles, preferreds, credit stack changes",
            "mNAV premium or discount, analyst/institutional sentiment",
            "Management comments from Michael Saylor or Strategy filings",
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
        "watch": [
            "TSE timely disclosures and company IR",
            "BTC purchases, BTC Yield, mNAV, BTC per fully diluted share",
            "Large-holder filings, especially Capital Group / Capital Research",
            "Warrants, preferreds, debt, buybacks, compensation changes",
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
        "watch": [
            "Bitcoin treasury announcements and financing terms",
            "Share issuance, reverse splits, warrants, and liquidity events",
            "Strive-related governance or management changes",
            "Audited filings and risk disclosures",
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
        "watch": [
            "ETH treasury purchases and ETH per share",
            "Financing terms, issuance, warrants, or convertible securities",
            "Tom Lee / management commentary and SEC filings",
            "Custody, staking, and treasury-policy disclosures",
        ],
    },
]

SYSTEM = """You are a disciplined equity research assistant for a private owner.

Today's date is {today}. Search the web for developments from the last {days}
days only. Monitor these holdings:

{holdings}

Rules:
- Prefer primary sources: company IR, SEC/EDGAR, TSE timely disclosures, EDINET,
  official management statements, and exchange filings.
- Use reputable financial news only when no primary source is available.
- Do not invent numbers. If a number is unavailable, use null or say unavailable.
- Skip items in ALREADY REPORTED unless there is a material update.
- Focus on management actions, financing, dilution, treasury purchases, custody,
  shareholder changes, strategy shifts, regulation, earnings, and capital markets.
- Assess whether each item is positive, negative, or neutral for the stock thesis.
- Include a practical price-impact view: likely up, likely down, mixed/unclear,
  or no immediate effect, and explain why in one sentence.

Finish with ONE fenced ```json block and nothing after it, in this schema:
{{
  "reports": [
    {{
      "slug": "mstr|metaplanet|asst|bitmine",
      "snapshot": {{"market_price": number|null, "treasury_holdings": string|null,
                    "mnav": number|null, "as_of": "YYYY-MM-DD"|null}},
      "overall_verdict": "positive" | "negative" | "neutral",
      "email_summary": "one short sentence for an email preview",
      "bottom_line": "2 sentences max on the net effect for the thesis",
      "price_impact": "1-2 sentences on how the stock price may react",
      "updates": [
        {{
          "date": "YYYY-MM-DD",
          "headline": "max 12 words",
          "what_happened": "2-3 concrete sentences in your own words",
          "assessment": "positive" | "negative" | "neutral",
          "thesis_fit": "one sentence tying it to the holding thesis",
          "price_impact": "one sentence on likely price effect",
          "severity": "alert" | "digest",
          "confidence": "primary source" | "secondary only" | "unconfirmed",
          "source_url": "https://..."
        }}
      ]
    }}
  ]
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
            f"  Watch: {'; '.join(holding['watch'])}\n"
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
    return data


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
        "snapshot": report.get("snapshot") or {},
        "overall_verdict": report.get("overall_verdict") or "neutral",
        "email_summary": report.get("email_summary") or "No material change.",
        "bottom_line": report.get("bottom_line") or "No material change to the thesis.",
        "price_impact": report.get("price_impact") or "No clear immediate price impact.",
        "updates": report.get("updates") or [],
    }


def write_reports(reports: list[dict[str, Any]]) -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    latest = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "reports": reports,
    }
    (REPORT_DIR / "latest.json").write_text(json.dumps(latest, indent=2, ensure_ascii=False), encoding="utf-8")
    for report in reports:
        if report.get("slug"):
            (REPORT_DIR / f"{report['slug']}.json").write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )


def render_email(
    reports: list[dict[str, Any]],
    new_updates: list[tuple[dict[str, Any], dict[str, Any]]],
) -> tuple[str, str]:
    positives = sum(update.get("assessment") == "positive" for _, update in new_updates)
    negatives = sum(update.get("assessment") == "negative" for _, update in new_updates)
    neutrals = len(new_updates) - positives - negatives
    subject = f"Holdings monitor: {positives} positive / {negatives} negative / {neutrals} neutral"

    lines = [
        f"Holdings monitor - {dt.date.today():%d %b %Y}",
        "",
        "SHORT VERSION",
    ]
    for report, update in new_updates:
        lines.append(
            f"- {report['name']}: {update.get('headline')} "
            f"({update.get('assessment', 'neutral')}). {update.get('price_impact', '')}"
        )
    lines += ["", "READ MORE"]
    for report in reports:
        if any(existing["slug"] == report["slug"] for existing, _ in new_updates):
            lines.append(f"- {report['name']}: {report['dashboard_url']}")

    lines += ["", "DETAILED ASSESSMENT"]
    for report, update in new_updates:
        lines += [
            "",
            f"{report['name']} ({report['ticker']})",
            f"Dashboard: {report['dashboard_url']}",
            f"Bottom line: {report.get('bottom_line')}",
            f"Price impact: {report.get('price_impact')}",
            f"Update: {update.get('headline')} ({update.get('date')})",
            f"What happened: {update.get('what_happened')}",
            f"Assessment: {str(update.get('assessment')).upper()} - {update.get('thesis_fit')}",
            f"Confidence: {update.get('confidence')}",
            f"Source: {update.get('source_url')}",
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
                "market_price": None,
                "treasury_holdings": None,
                "mnav": None,
                "as_of": dt.date.today().isoformat(),
            },
            "overall_verdict": "neutral",
            "email_summary": "Sample monitor run.",
            "bottom_line": "This is a dry-run sample so the dashboard panel can be tested.",
            "price_impact": "No real price impact; this is sample data.",
            "updates": [{
                "date": dt.date.today().isoformat(),
                "headline": "Sample monitoring item",
                "what_happened": "This sample item proves the monitor can render email and dashboard output.",
                "assessment": "neutral",
                "thesis_fit": "No thesis change because this is a sample.",
                "price_impact": "No expected price reaction.",
                "severity": "digest",
                "confidence": "unconfirmed",
                "source_url": f"{BASE_URL}/dashboard/stocks/treasury/metaplanet/",
            }],
        }],
    }


def main() -> int:
    state = load_state()
    seen_ids = {entry.get("id") for entry in state.get("seen", [])}
    already_reported = [entry.get("label", "") for entry in state.get("seen", [])]

    data = load_sample() if os.environ.get("SAMPLE_DATA") else ask_claude(already_reported)
    reports = [normalize_report(report) for report in data.get("reports", []) if report.get("slug")]
    write_reports(reports)

    new_updates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for report in reports:
        for update in report.get("updates", []):
            update_key = item_id(report["slug"], update)
            if update_key not in seen_ids:
                new_updates.append((report, update))

    to_send = new_updates
    if to_send:
        subject, body = render_email(reports, to_send)
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
        save_state(state)
    else:
        print("No new holding updates. Reports were refreshed; no email sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
