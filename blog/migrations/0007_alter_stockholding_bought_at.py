from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0006_stockholding'),
    ]

    operations = [
        migrations.AlterField(
            model_name='stockholding',
            name='bought_at',
            field=models.DateTimeField(),
        ),
    ]
