# Generated by Django 5.1 on 2024-09-29 10:57

import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('coolnjoy', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='coolnjoydeal',
            name='title',
        ),
        migrations.AddField(
            model_name='coolnjoydeal',
            name='a_link',
            field=models.CharField(blank=True, max_length=512, null=True, verbose_name='링크 주소1'),
        ),
        migrations.AddField(
            model_name='coolnjoydeal',
            name='a_link2',
            field=models.CharField(blank=True, max_length=512, null=True, verbose_name='링크 주소2'),
        ),
        migrations.AddField(
            model_name='coolnjoydeal',
            name='b_link',
            field=models.CharField(blank=True, max_length=512, null=True, verbose_name='링크 주소3'),
        ),
        migrations.AddField(
            model_name='coolnjoydeal',
            name='category',
            field=models.CharField(blank=True, max_length=32, null=True, verbose_name='구분'),
        ),
        migrations.AddField(
            model_name='coolnjoydeal',
            name='content',
            field=models.CharField(blank=True, max_length=2048, null=True, verbose_name='내용'),
        ),
        migrations.AddField(
            model_name='coolnjoydeal',
            name='crawled_at',
            field=models.DateTimeField(default=datetime.datetime(2024, 9, 29, 10, 57, 4, 976419), verbose_name='수집일'),
        ),
        migrations.AddField(
            model_name='coolnjoydeal',
            name='create_at',
            field=models.DateTimeField(default=datetime.datetime(2024, 9, 29, 10, 57, 4, 976407), verbose_name='생성일'),
        ),
        migrations.AddField(
            model_name='coolnjoydeal',
            name='img',
            field=models.CharField(blank=True, max_length=512, null=True, verbose_name='이미지 주소'),
        ),
        migrations.AddField(
            model_name='coolnjoydeal',
            name='price',
            field=models.CharField(blank=True, max_length=64, null=True, verbose_name='가격'),
        ),
        migrations.AddField(
            model_name='coolnjoydeal',
            name='recommend_count',
            field=models.IntegerField(default=0, verbose_name='추천수'),
        ),
        migrations.AddField(
            model_name='coolnjoydeal',
            name='subject',
            field=models.CharField(blank=True, max_length=1024, null=True, verbose_name='제목'),
        ),
        migrations.AddField(
            model_name='coolnjoydeal',
            name='url',
            field=models.CharField(blank=True, max_length=512, null=True, verbose_name='커뮤니티 글 링크'),
        ),
    ]