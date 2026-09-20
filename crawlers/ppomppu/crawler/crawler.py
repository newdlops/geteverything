from crawlers import django_setup
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from crawlers.ppomppu.spider import PpomppuSpider

def crawl():
    print('뽐뿌 실행')
    process = CrawlerProcess(get_project_settings())

    # 스파이더를 실행합니다.
    crawler = process.create_crawler(PpomppuSpider)
    process.crawl(crawler)
    process.start()
    if not crawler.stats.get_value('item_scraped_count', 0):
        raise RuntimeError('Ppomppu crawl finished without successfully processed items')

if __name__ == "__main__":
    crawl()
