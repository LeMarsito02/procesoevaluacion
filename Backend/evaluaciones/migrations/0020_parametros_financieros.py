from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('evaluaciones', '0019_medicion_rendimiento'),
    ]

    operations = [
        migrations.AddField(
            model_name='proceso',
            name='parametros_financieros',
            field=models.JSONField(blank=True, null=True),
        ),
    ]
