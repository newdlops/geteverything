from datetime import datetime
from django.db import models


class PpomppuDeal(models.Model):
    article_id = models.BigIntegerField()

    origin_url = models.URLField(max_length=512, verbose_name='원글주소')
    shop_url_1 = models.URLField(max_length=512, verbose_name='쇼핑몰 링크')

    thumbnail = models.URLField(max_length=512, verbose_name='썸네일', blank=True, null=True)

    subject = models.CharField(max_length=512, verbose_name='제목', blank=True, null=True)
    content = models.CharField(max_length=2048, verbose_name='본문내용',blank=True, null=True)
    category = models.CharField(max_length=32, verbose_name='구분', blank=True, null=True)

    price = models.IntegerField(verbose_name='가격', default=0)

    recommend_count = models.IntegerField(verbose_name='추천수', default=0)
    view_count = models.IntegerField(verbose_name='조회수', default=0)


    create_at = models.DateTimeField(default=datetime.now(), verbose_name='원글 작성일')
    update_at = models.DateTimeField(default=datetime.now(), verbose_name='업데이트일시')
    crawled_at = models.DateTimeField(default=datetime.now(), verbose_name='크롤링 수집일')



