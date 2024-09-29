import scrapy
import os
import django

from coolnjoy.models import CoolNJoyDeal

os.environ['DJANGO_SETTINGS_MODULE'] = 'admin.settings'
django.setup()

class MySpider(scrapy.Spider):
  name = "my_spider"

  # 수집할 웹사이트의 URL을 지정합니다.
  start_urls = ['https://www.fmkorea.com/index.php?mid=hotdeal&category=1196844726']

  def parse(self, response):
    for quote in response.css('h3.title'):
      title = CoolNJoyDeal(title=quote.css('a::text').get())
      title.save()
      yield {
        'text': quote.css('a::text').get(),
      }
