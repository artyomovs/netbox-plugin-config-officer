# Generated by Django 3.1.3 on 2021-02-27 20:43

import django.contrib.postgres.fields
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('dcim', '0122_standardize_name_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='Service',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=200)),
                ('description', models.CharField(blank=True, max_length=255)),
            ],
            options={
                'ordering': ['-id'],
            },
        ),
        migrations.CreateModel(
            name='Template',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ('name', models.CharField(blank=True, max_length=512, null=True)),
                ('description', models.CharField(blank=True, max_length=512, null=True)),
                ('configuration', models.TextField(blank=True, null=True)),
            ],
            options={
                'ordering': ['-id'],
            },
        ),
        migrations.CreateModel(
            name='ServiceRule',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ('description', models.CharField(blank=True, max_length=512, null=True)),
                ('device_role', models.ManyToManyField(to='dcim.DeviceRole')),
                ('device_type', models.ManyToManyField(blank=True, to='dcim.DeviceType')),
                ('service', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='service_rules', to='config_officer.service')),
                ('template', models.ForeignKey(blank=True, on_delete=django.db.models.deletion.CASCADE, to='config_officer.template')),
            ],
        ),
        migrations.CreateModel(
            name='ServiceMapping',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ('device', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='dcim.device')),
                ('service', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='config_officer.service')),
            ],
        ),
        migrations.CreateModel(
            name='Compliance',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ('status', models.CharField(default='non-compliance', max_length=50)),
                ('notes', models.CharField(blank=True, default=None, max_length=512, null=True)),
                ('generated_config', models.TextField(blank=True, null=True)),
                ('diff', models.TextField(blank=True, null=True)),
                ('services', django.contrib.postgres.fields.ArrayField(base_field=models.CharField(blank=True, max_length=512, null=True), blank=True, default=list, null=True, size=None)),
                ('device', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='compliance', to='dcim.device')),
            ],
        ),
        migrations.CreateModel(
            name='Collection',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ('status', models.CharField(default='pending', max_length=255, null=True)),
                ('message', models.CharField(blank=True, max_length=512, null=True)),
                ('timestamp', models.DateTimeField(auto_now_add=True)),
                ('failed_reason', models.CharField(max_length=255, null=True)),
                ('device', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='dcim.device')),
            ],
            options={
                'ordering': ['timestamp'],
            },
        ),
    ]
