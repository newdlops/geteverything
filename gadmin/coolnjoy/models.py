from datetime import datetime
from django.db import models


class CoolNJoyDeal(models.Model):
    url = models.CharField(max_length=512, verbose_name='커뮤니티 글 링크', blank=True, null=True)
    subject = models.CharField(max_length=1024, verbose_name='제목', blank=True, null=True)
    category = models.CharField(max_length=32, verbose_name='구분', blank=True, null=True)
    price = models.CharField(max_length=64, verbose_name='가격', blank=True, null=True)
    recommend_count = models.IntegerField(verbose_name='추천수', default=0)
    create_at = models.DateTimeField(default=datetime.now(), verbose_name='생성일')
    crawled_at = models.DateTimeField(default=datetime.now(), verbose_name='수집일')

    content = models.CharField(max_length=2048, verbose_name='내용',blank=True, null=True)
    a_link = models.CharField(max_length=512, verbose_name='링크 주소1',blank=True, null=True)
    a_link2 = models.CharField(max_length=512, verbose_name='링크 주소2',blank=True, null=True)
    b_link = models.CharField(max_length=512, verbose_name='링크 주소3',blank=True, null=True)
    img = models.CharField(max_length=512, verbose_name='이미지 주소',blank=True, null=True)
    cool_n_joy_id = models.BigIntegerField(default=0)
