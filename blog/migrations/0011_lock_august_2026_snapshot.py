from decimal import Decimal
from datetime import date

from django.db import migrations


def lock_august_2026_snapshot(apps, schema_editor):
    PortfolioSnapshot = apps.get_model('blog', 'PortfolioSnapshot')
    august_date = date(2026, 8, 31)
    september_date = date(2026, 9, 30)

    existing_august = PortfolioSnapshot.objects.filter(snapshot_date=august_date).first()
    existing_september = PortfolioSnapshot.objects.filter(snapshot_date=september_date).first()
    bitcoin_amount = (
        getattr(existing_august, 'bitcoin_amount', None)
        or getattr(existing_september, 'bitcoin_amount', None)
        or Decimal('0.42082719')
    )

    august_snapshot, _created = PortfolioSnapshot.objects.update_or_create(
        snapshot_date=august_date,
        defaults={
            'cash_chf': Decimal('9825'),
            'bitcoin_chf': Decimal('26424'),
            'stocks_chf': Decimal('25039'),
            'bitcoin_amount': bitcoin_amount,
            'locked': True,
            'notes': 'Confirmed 31.08.2026 month-end close.',
        }
    )
    PortfolioSnapshot.objects.update_or_create(
        snapshot_date=september_date,
        defaults={
            'cash_chf': august_snapshot.cash_chf,
            'bitcoin_chf': august_snapshot.bitcoin_chf,
            'stocks_chf': august_snapshot.stocks_chf,
            'bitcoin_amount': august_snapshot.bitcoin_amount,
            'locked': False,
            'notes': 'Seeded from the confirmed 31.08.2026 close.',
        }
    )


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0010_stockquotesnapshot'),
    ]

    operations = [
        migrations.RunPython(lock_august_2026_snapshot, migrations.RunPython.noop),
    ]
