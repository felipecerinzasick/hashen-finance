from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0005_contact_date_posted'),
    ]

    operations = [
        migrations.CreateModel(
            name='StockHolding',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120)),
                ('ticker', models.CharField(max_length=20)),
                ('symbol', models.CharField(max_length=40)),
                ('shares', models.DecimalField(decimal_places=8, max_digits=18)),
                ('average_price', models.DecimalField(decimal_places=4, max_digits=18)),
                ('cost_currency', models.CharField(choices=[('CHF', 'CHF'), ('USD', 'USD'), ('EUR', 'EUR'), ('GBP', 'GBP')], default='USD', max_length=3)),
                ('bought_at', models.DateField()),
                ('fallback_value', models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ('fallback_currency', models.CharField(choices=[('CHF', 'CHF'), ('USD', 'USD'), ('EUR', 'EUR'), ('GBP', 'GBP')], default='USD', max_length=3)),
                ('category', models.CharField(blank=True, max_length=160)),
                ('why_own', models.TextField(blank=True)),
                ('target_price', models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ('target_currency', models.CharField(choices=[('CHF', 'CHF'), ('USD', 'USD'), ('EUR', 'EUR'), ('GBP', 'GBP')], default='USD', max_length=3)),
                ('target_date', models.DateField(blank=True, null=True)),
                ('target_note', models.TextField(blank=True)),
                ('active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ('ticker', 'bought_at', 'id'),
            },
        ),
    ]
