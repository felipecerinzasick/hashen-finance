"""Read the JSON written by monitoring/monitor.py for the dashboard pages.

Kept free of Django model imports so it can be exercised outside the app.
"""
import datetime
import json
from pathlib import Path

VERDICT_CLASSES = {
    'positive': 'gain',
    'negative': 'loss',
}

COMPANY_SLUGS = ('mstr', 'metaplanet', 'asst', 'bitmine')


def reports_dir(base_dir):
    return Path(base_dir) / 'monitoring' / 'reports'


def format_timestamp(value):
    """Turn the monitor's ISO timestamp into '9 Nov 2026, 10:58 UTC'."""
    if not value:
        return None
    text = str(value).replace('Z', '+00:00')
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return str(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(datetime.timezone.utc)
    return '%d %s UTC' % (parsed.day, parsed.strftime('%b %Y, %H:%M'))


def decorate(entry):
    """Add the derived fields the monitoring panel template expects."""
    if not isinstance(entry.get('snapshot'), dict):
        entry['snapshot'] = {}
    for key in ('holdings', 'share_price', 'mnav', 'as_of'):
        entry['snapshot'].setdefault(key, None)
    entry.setdefault('source_conflicts', [])
    entry['updates'] = [update for update in entry.get('updates') or [] if isinstance(update, dict)]
    entry['has_updates'] = bool(entry['updates'])
    entry['verdict_class'] = VERDICT_CLASSES.get(entry.get('overall_verdict'), '')
    entry['generated_label'] = format_timestamp(entry.get('generated_at'))
    for update in entry['updates']:
        update['assessment_class'] = VERDICT_CLASSES.get(update.get('assessment'), '')
    return entry


def load_history(slug, base_dir, exclude_generated_at=None):
    """Earlier assessments for one holding, newest first, without the live one."""
    path = reports_dir(base_dir) / 'history' / ('%s.json' % slug)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return []
    entries = []
    for entry in data.get('entries', []):
        if not isinstance(entry, dict) or not entry.get('generated_at'):
            continue
        if exclude_generated_at and entry['generated_at'] == exclude_generated_at:
            continue
        entries.append(decorate(dict(entry)))
    entries.sort(key=lambda item: str(item.get('generated_at')), reverse=True)
    return entries


def load_monitoring_report(slug, base_dir):
    path = reports_dir(base_dir) / ('%s.json' % slug)
    try:
        report = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(report, dict):
        return None
    decorate(report)
    report['history'] = load_history(slug, base_dir, report.get('generated_at'))
    report['history_count'] = len(report['history'])
    return report
