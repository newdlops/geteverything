# Generated by Django 5.1 on 2024-10-28 13:55

import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('coolnjoy', '0008_alter_coolnjoydeal_crawled_at_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='coolnjoydeal',
            name='crawled_at',
            field=models.DateTimeField(default=datetime.datetime(2024, 10, 28, 13, 55, 5, 80054), verbose_name='수집일'),
        ),
        migrations.AlterField(
            model_name='coolnjoydeal',
            name='create_at',
            field=models.DateTimeField(default=datetime.datetime(2024, 10, 28, 13, 55, 5, 80032), verbose_name='생성일'),
        ),
    ]