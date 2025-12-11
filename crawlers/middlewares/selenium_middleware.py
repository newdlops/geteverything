import os
import time

from scrapy import signals
from scrapy.http import HtmlResponse
from scrapy.utils.python import to_bytes

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import logging

logging.getLogger("selenium").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.WARNING)


class SeleniumMiddleware(object):
    def __init__(self):
        self.driver = None

    @classmethod
    def from_crawler(cls, crawler):
        middleware = cls()
        crawler.signals.connect(middleware.spider_opened, signals.spider_opened)
        crawler.signals.connect(middleware.spider_closed, signals.spider_closed)
        return middleware

    def interceptor(self, request):
        # 모든 기본 헤더 삭제
        for h in list(request.headers.keys()):
            del request.headers[h]
        # 최소한의 헤더만 설정
        request.headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36'
        # Referer, Origin, Host 등 전부 없음

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
        # 스파이더 이름별로 프로필/캐시 디렉터리 분리
        base_dir = "/tmp/selenium"
        os.makedirs(base_dir, exist_ok=True)
    
        user_data_dir = os.path.join(base_dir, f"user-data-{spider.name}")
        data_path = os.path.join(base_dir, f"data-{spider.name}")
        cache_dir = os.path.join(base_dir, f"cache-{spider.name}")
    
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
        chrome_options.add_argument(f"--data-path={data_path}")
        chrome_options.add_argument(f"--disk-cache-dir={cache_dir}")
        
        # chrome_options.add_argument("--user-data-dir=/tmp/user-data")
        # chrome_options.add_argument("--data-path=/tmp/data")
        # chrome_options.add_argument("--disk-cache-dir=/tmp/cache")

        # 로컬에서 테스트할 경우에 아래 두 줄을 주석처리한 후 테스트 한다. '/opt/chrome', '/opt/chromedriver'는 이미지 상에 존재하는 폴더이므로 주석처리
        chrome_options.binary_location = '/bin/chromium' # 로컬에서는 주석처리한다.
        driver  = webdriver.Chrome(service=Service(executable_path="/bin/chromedriver", service_log_path=os.devnull), options=chrome_options) # 로컬에서는 주석처리
        # driver  = webdriver.Chrome() # 운영에서 주석처리 로컬에서는 살림
        driver.request_interceptor = self.interceptor
        self.driver = driver

    def spider_closed(self, spider):
        self.driver.close()

    def process_request( self, request, spider ):
        self.driver.get( request.url )
        print('드라이버 사용함')


        wait = WebDriverWait(self.driver, 30)
        # element = wait.until(EC.presence_of_element_located((By.TAG_NAME, "title")))
        # wait.until(
        #     lambda d: d.execute_script("return sessionStorage.getItem('PHPSESSID') !== null;")
        # )
        # for i in range(1,3):
        #     link = wait.until(
        #         EC.element_to_be_clickable((By.TAG_NAME, "a"))  # 또는 By.PARTIAL_LINK_TEXT, By.CSS_SELECTOR 등
        #     )
        #     link.click()
        #     element = wait.until(EC.presence_of_element_located((By.TAG_NAME, "title")))
        #     time.sleep(1)

        body = to_bytes( text=self.driver.page_source )
        # print(body)
        print('잘 긁어옴')
        return HtmlResponse( url=request.url, body=body, encoding='utf-8', request=request )
