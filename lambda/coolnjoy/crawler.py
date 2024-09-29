import json

# import requests

import os
import django



os.environ['DJANGO_SETTINGS_MODULE'] = 'admin.settings'
django.setup()


from scrapy.crawler import CrawlerProcess
from spider import MySpider

from coolnjoy.models import CoolNJoyDeal


def crawl():
    process = CrawlerProcess(settings={
        "FEEDS": {
            "/tmp/output.json": {"format": "json"},
        },
    })

    # 스파이더를 실행합니다.
    process.crawl(MySpider)
    process.start()

    # 결과 파일을 읽고 반환합니다.
    with open('/tmp/output.json') as f:
        data = json.load(f)
