import json

# import requests

import os
import django

os.environ['DJANGO_SETTINGS_MODULE'] = 'admin.settings'
django.setup()


from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from spider import CoolNJoySpider

def crawl():
    process = CrawlerProcess(get_project_settings())

    # 스파이더를 실행합니다.
    process.crawl(CoolNJoySpider)
    process.start()
