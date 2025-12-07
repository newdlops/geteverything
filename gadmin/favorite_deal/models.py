from django.db import models
from django.db.models import Manager
from deals.models import Deal
from user.models import User


class FavoriteDeal(models.Model):
    deal = models.ForeignKey(Deal, on_delete=models.DO_NOTHING)
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING)
    create_at = models.DateTimeField(auto_now_add=True, verbose_name='크롤링 일자')
    update_at = models.DateTimeField(auto_now=True, verbose_name='업데이트일시')

    objects = Manager()

    class Meta:
        db_table='favorite_deals'
