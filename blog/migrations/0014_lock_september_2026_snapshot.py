from decimal import Decimal
from datetime import date

from django.db import migrations


def lock_september_2026_snapshot(apps, schema_editor):
    PortfolioSnapshot = apps.get_model('blog', 'PortfolioSnapshot')
    PortfolioSnapshot.objects.update_or_create(
        snapshot_date=date(2026, 9, 30),
        defaults={
            'cash_chf': Decimal('12597.54'),
            'bitcoin_chf': Decimal('28760.00'),
            'stocks_chf': Decimal('26590.02'),
            'bitcoin_amount': Decimal('0.40968000'),
            'locked': True,
            'notes': 'Confirmed 30.09.2026 month-end close.',
        }
    )


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0013_auto_20261003_0916'),
    ]

    operations = [
        migrations.RunPython(lock_september_2026_snapshot, migrations.RunPython.noop),
    ]
