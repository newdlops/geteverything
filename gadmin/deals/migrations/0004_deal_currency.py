# Generated by Django 5.1 on 2024-11-10 08:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deals', '0003_alter_deal_crawled_at_alter_deal_create_at_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='deal',
            name='currency',
            field=models.CharField(blank=True, max_length=32, null=True, verbose_name='단위'),
        ),
    ]
