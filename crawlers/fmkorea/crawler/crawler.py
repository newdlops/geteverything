from crawlers import django_setup
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from crawlers.fmkorea.spider import FmKoreaSpider

def crawl():
    settings = get_project_settings()
    settings.set('LOG_LEVEL', 'ERROR')
    process = CrawlerProcess(settings)

    # 스파이더를 실행합니다.
    process.crawl(FmKoreaSpider)
    process.start()

if __name__ == "__main__":
    crawl()
