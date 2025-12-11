import os
import time
from datetime import datetime

from scrapy import signals
from scrapy.http import HtmlResponse
from scrapy.utils.python import to_bytes

from selenium import webdriver
from selenium.common import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import undetected_chromedriver as uc
from selenium_stealth import stealth

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
        chrome_options = uc.ChromeOptions()
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
        # driver = uc.Chrome(service=Service(executable_path="/bin/chromedriver", service_log_path=os.devnull), options=chrome_options) # 로컬에서는 주석처리
        driver = uc.Chrome(
            options=chrome_options,
            driver_executable_path="/bin/chromedriver", # 경로가 확실하다면 지정, 아니면 생략하여 자동 다운로드 유도
            version_main=131 # (선택) 설치된 크롬 버전의 메이저 버전을 명시하면 더 안정적
        )
        # driver  = webdriver.Chrome() # 운영에서 주석처리 로컬에서는 살림

        stealth(driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True,
                )

        self.driver = driver

    def spider_closed(self, spider):
        self.driver.close()

    def _wait_cloudflare_done(self, timeout=20):
        wait = WebDriverWait(self.driver, timeout)

        def not_cloudflare_page(driver):
            src = driver.page_source.lower()
            # Cloudflare 대기 페이지의 흔한 텍스트를 기준으로 간단 체크
            if "just a moment" in src and "cloudflare" in src:
                return False
            return True

        wait.until(not_cloudflare_page)

    def process_request( self, request, spider ):
        self.driver.get( request.url )
        print(f"[Info : {datetime.now()}]{spider.name}이 드라이버 사용함")

        try:
            self._wait_cloudflare_done(timeout=20)
        except TimeoutException:
            self.driver.save_screenshot("/debug_error.png")
            spider.logger.warning(f"Cloudflare 대기 해제 안 됨 (20초 내): {request.url}")

        body = to_bytes( text=self.driver.page_source )
        print(f"[Info : {datetime.now()}]{spider.name}이 드라이버로 잘 긁어옴 사용함")
        return HtmlResponse( url=request.url, body=body, encoding='utf-8', request=request )
