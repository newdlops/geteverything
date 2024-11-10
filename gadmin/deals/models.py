from datetime import datetime
from django.db import models


class Deal(models.Model):
    article_id = models.CharField(verbose_name='글아이디', default=0)
    community_name = models.CharField(max_length=64, verbose_name='커뮤니티명', default='')
    origin_url = models.URLField(max_length=512, verbose_name='원글주소', blank=True, null=True)
    shop_url_1 = models.URLField(max_length=512, verbose_name='쇼핑몰 링크1', blank=True, null=True)
    shop_url_2 = models.URLField(max_length=512, verbose_name='쇼핑몰 링크2', blank=True, null=True)
    shop_name = models.CharField(max_length=64, verbose_name='쇼핑몰이름', blank=True, null=True)
    thumbnail = models.URLField(max_length=512, verbose_name='썸네일', blank=True, null=True)
    subject = models.CharField(max_length=512, verbose_name='제목', blank=True, null=True)
    category = models.CharField(max_length=32, verbose_name='카테고리', blank=True, null=True)
    price = models.IntegerField(verbose_name='가격', default=0)
    currency = models.CharField(max_length=32, verbose_name='단위', blank=True, null=True)
    delivery_price = models.IntegerField(verbose_name='배송료', default=0)
    recommend_count = models.IntegerField(verbose_name='추천수', default=0)
    dislike_count = models.IntegerField(verbose_name='비추수', default=0)
    view_count = models.IntegerField(verbose_name='조회수', default=0)
    create_at = models.DateTimeField(auto_now_add=True, verbose_name='원글 작성일')
    update_at = models.DateTimeField(auto_now=True, verbose_name='업데이트일시')
    crawled_at = models.DateTimeField(default=datetime.now, verbose_name='크롤링 수집일')
    is_end = models.BooleanField(verbose_name='종료여부', default=False)

    class Meta:
        db_table='deals'
