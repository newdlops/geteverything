# Generated by Django 5.1 on 2024-10-26 05:57

import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='PpomppuDeal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('url', models.CharField(blank=True, max_length=512, null=True, verbose_name='커뮤니티 글 링크')),
                ('subject', models.CharField(blank=True, max_length=1024, null=True, verbose_name='제목')),
                ('category', models.CharField(blank=True, max_length=32, null=True, verbose_name='구분')),
                ('price', models.CharField(blank=True, max_length=64, null=True, verbose_name='가격')),
                ('recommend_count', models.IntegerField(default=0, verbose_name='추천수')),
                ('create_at', models.DateTimeField(default=datetime.datetime(2024, 10, 26, 5, 57, 52, 274153), verbose_name='생성일')),
                ('crawled_at', models.DateTimeField(default=datetime.datetime(2024, 10, 26, 5, 57, 52, 274168), verbose_name='수집일')),
                ('content', models.CharField(blank=True, max_length=2048, null=True, verbose_name='내용')),
                ('a_link', models.CharField(blank=True, max_length=512, null=True, verbose_name='링크 주소1')),
                ('a_link2', models.CharField(blank=True, max_length=512, null=True, verbose_name='링크 주소2')),
                ('b_link', models.CharField(blank=True, max_length=512, null=True, verbose_name='링크 주소3')),
                ('img', models.CharField(blank=True, max_length=512, null=True, verbose_name='이미지 주소')),
                ('cool_n_joy_id', models.BigIntegerField(default=0)),
            ],
        ),
    ]
