import re

import scrapy
import os
import django
import datetime

from zoneinfo import ZoneInfo
from scrapy import Request
from w3lib.html import remove_tags, replace_escape_chars

if __name__ == 'spider':
  from item import CoolNJoyItem
  from item_pipeline import CoolNJoyPipeline
else:
  from .item import CoolNJoyItem
  from .item_pipeline import CoolNJoyPipeline


os.environ['DJANGO_SETTINGS_MODULE'] = 'admin.settings'
django.setup()

class CoolNJoySpider(scrapy.Spider):
  name = "cool_n_joy_spider"
  custom_settings = {
    'DOWNLOAD_DELAY': 2,
    'ITEM_PIPELINES': {
      CoolNJoyPipeline: 300,
    }
  }


  # 수집할 웹사이트의 URL을 지정합니다.
  start_urls = [
    'https://coolenjoy.net/bbs/jirum?page=1',
    'https://coolenjoy.net/bbs/jirum?page=2',
    'https://coolenjoy.net/bbs/jirum?page=3',
                ]

  def start_requests(self):
    total_page = 5

    headers = {
      "accept": "*/*",
      "accept-encoding": "gzip, deflate, br, zstd",
      "accept-language": "ko,en-US;q=0.9,en;q=0.8,ja;q=0.7,ko-KR;q=0.6,la;q=0.5,ru;q=0.4",
      "cache-control": "no-cache",
      "connection": "keep-alive",
      # "cookie": "PHPSESSID=b7un8jufmlc1va57stec638fvt; 2a0d2363701f23f8a75028924a3af643=MTgzLjk2LjE1MS4xMDY%3D; _ga=GA1.1.1679366502.1729782091; e1192aefb64683cc97abb83c71057733=amlydW0%3D; _ga_DWVWYQG87R=GS1.1.1729788022.2.1.1729788114.0.0.0",
      "host": "coolenjoy.net",
      "pragma": "no-cache",
      "referer": "https://coolenjoy.net/bbs/jirum",
      "sec-ch-ua-mobile": "?0",
      "sec-ch-ua-platform": "macOS",
      "sec-fetch-dest": "empty",
      "sec-fetch-mode": "cors",
      "sec-fetch-site": "same-origin",
      "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
      "x-requested-with": "XMLHttpRequest",
    }

    for i in range(1, total_page+1):
        yield scrapy.Request(
            f"https://coolenjoy.net/bbs/jirum?page={i}",
            callback=self.parse,
            headers=headers,
            meta={'cookiejar': i}
        )

  def parse(self, response):
    for li in response.css('li.d-md-table-row'):
      origin_url = li.css('a.na-subject::attr(href)').get().strip()
      article_id = re.search(r'jirum\/(.*?)\?', origin_url).group(1)
      subject = li.css('a.na-subject').xpath('string()').get().strip()
      category = ( category := li.css('#abcd::text').get()) and category.strip()
      # reply_count = li.css() TODO: 원글 댓글수
      price = li.css('font::text').get().strip()
      recommend_count = li.css('.rank-icon_vote::text').get().strip()
      # view_count = int(replace_escape_chars(remove_tags(li.css('div:has(i.fa-eye).float-left').get())).replace('조회',''))
      data = {
        'origin_url': origin_url, 'article_id': article_id,
        'subject': subject, 'category': category, 'price': price, 'recommend_count': recommend_count
      }
      yield Request(url=origin_url, callback=self.detail_parse, cb_kwargs=dict(data=data), meta={'cookiejar': response.meta['cookiejar']})

  def detail_parse(self, response, data):
    # content = response.css('div.view-content.fr-view::text').getall()
    # a_link = (a_link := response.css('div.view-content.fr-view a::attr(href)').get()) and a_link.strip()
    # a_link2 = (a_link2 := response.css('div.view-content.fr-view a::text').get()) and a_link2.strip()
    shop_url_1 = (shop_url_1 := response.css('.pl-3 a::text').get()) and shop_url_1.strip()
    thumbnail = (img := response.css('div.view-content.fr-view img::attr(href)').get()) and img.strip()
    write_at = (create_at := response.css('time.f-xs::text').get()) and create_at.strip()
    view_count = int(replace_escape_chars(remove_tags(response.css('li:has(i.fa-eye).pr-3').get()).replace(',','')).replace('조회',''))
    input_format = '%Y.%m.%d %H:%M'
    utc = ZoneInfo('UTC')
    create_time = datetime.datetime.strptime(write_at, input_format)

    yield CoolNJoyItem(dict(**data, shop_url_1=shop_url_1, thumbnail=thumbnail, write_at=create_time, view_count=view_count))
