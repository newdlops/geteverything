# Generated by Django 5.1 on 2024-09-29 11:23

import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('coolnjoy', '0002_remove_coolnjoydeal_title_coolnjoydeal_a_link_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='coolnjoydeal',
            name='cool_n_joy_id',
            field=models.BigIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='coolnjoydeal',
            name='crawled_at',
            field=models.DateTimeField(default=datetime.datetime(2024, 9, 29, 11, 23, 26, 236027), verbose_name='수집일'),
        ),
        migrations.AlterField(
            model_name='coolnjoydeal',
            name='create_at',
            field=models.DateTimeField(default=datetime.datetime(2024, 9, 29, 11, 23, 26, 236013), verbose_name='생성일'),
        ),
    ]