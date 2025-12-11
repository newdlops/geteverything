from crawlers import django_setup
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from crawlers.coolnjoy.spider import CoolNJoySpider

def crawl():
    process = CrawlerProcess(get_project_settings())

    # 스파이더를 실행합니다.
    process.crawl(CoolNJoySpider)
    process.start()

if __name__ == "__main__":
    crawl()
