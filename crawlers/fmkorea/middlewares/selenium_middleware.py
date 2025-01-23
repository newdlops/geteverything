
from scrapy import signals
from scrapy.http import HtmlResponse
from scrapy.utils.python import to_bytes

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC



class SeleniumMiddleware(object):
    @classmethod
    def from_crawler(cls, crawler):
        middleware = cls()
        crawler.signals.connect(middleware.spider_opened, signals.spider_opened)
        crawler.signals.connect(middleware.spider_closed, signals.spider_closed)
        return middleware

    def spider_opened(self, spider):
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-setuid-sandbox")
        chrome_options.add_argument("--single-process")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1280X1696")
        # chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument('--profile-directory=Default')
        chrome_options.add_argument("--user-data-dir=/tmp/user-data")
        chrome_options.add_argument("--data-path=/tmp/data")
        chrome_options.add_argument("--disk-cache-dir=/tmp/cache")
        chrome_options.binary_location = '/opt/chrome/chrome' # 로컬에서는 주석처리한다.
        driver  = webdriver.Chrome(service=Service("/opt/chromedriver"), options=chrome_options) # 로컬에서는 주석처리
        # driver  = webdriver.Chrome() # 운영에서 주석
        self.driver = driver

    def spider_closed(self, spider):
        self.driver.close()

    def process_request( self, request, spider ):
        self.driver.get( request.url )
        print('드라이버 사용함')
        wait = WebDriverWait(self.driver, 10)
        element = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "bd")))

        body = to_bytes( text=self.driver.page_source )
        # print(body)
        print('잘 긁어옴')
        return HtmlResponse( url=request.url, body=body, encoding='utf-8', request=request )
