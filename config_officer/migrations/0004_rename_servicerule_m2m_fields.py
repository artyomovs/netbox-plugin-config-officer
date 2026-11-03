# Renames the many-to-many fields to plural names; the join tables are renamed, no data is lost.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("config_officer", "0003_collectschedule_webhook_secret_and_more"),
    ]

    operations = [
        migrations.RenameField(model_name="servicerule", old_name="device_role", new_name="device_roles"),
        migrations.RenameField(model_name="servicerule", old_name="device_type", new_name="device_types"),
    ]
