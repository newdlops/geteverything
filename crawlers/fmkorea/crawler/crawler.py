import os
import django

os.environ['DJANGO_SETTINGS_MODULE'] = 'admin.settings'
django.setup()


from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
if __name__ == 'crawler.crawler':
    from spider import FmKoreaSpider # noqa
else:
    from ..spider import FmKoreaSpider
def crawl():
    settings = get_project_settings()
    settings.set('LOG_LEVEL', 'ERROR')
    process = CrawlerProcess(settings)

    # 스파이더를 실행합니다.
    process.crawl(FmKoreaSpider)
    process.start()
