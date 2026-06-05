from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0005_alter_lead_options_alter_producto_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='lead',
            name='cantidad_solicitada',
            field=models.PositiveIntegerField(default=1),
        ),
    ]
