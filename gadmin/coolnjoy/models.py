from django.db import models

# Create your models here.
class CoolNJoyDeal(models.Model):
    title = models.CharField(max_length=1024)
