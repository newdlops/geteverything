from crawlers import django_setup
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from crawlers.eomisae.spider import EomisaeSpider # noqa

def crawl():
    print('어미새 실행')
    process = CrawlerProcess(get_project_settings())

    # 스파이더를 실행합니다.
    process.crawl(EomisaeSpider)
    process.start()

if __name__ == "__main__":
    crawl()
