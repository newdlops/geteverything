import os
import random
import time
from datetime import datetime

from scrapy import signals
from scrapy.http import HtmlResponse
from scrapy.utils.python import to_bytes

from selenium import webdriver
from selenium.common import TimeoutException
from selenium.webdriver import ActionChains
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
            use_subprocess=True,
        )
        # driver  = webdriver.Chrome() # 운영에서 주석처리 로컬에서는 살림

        # stealth(driver,
        #         languages=["en-US", "en"],
        #         vendor="Google Inc.",
        #         platform="Win32",
        #         webgl_vendor="Intel Inc.",
        #         renderer="Intel Iris OpenGL Engine",
        #         fix_hairline=True,
        #         )


        self.driver = driver
        # [핵심 수정] 브라우저가 켜진 직후, 강제로 크기를 주입합니다.
        # 이것이 없으면 VM에서 종종 800x600으로 시작해서 "Out of bounds" 에러가 납니다.
        self.driver.set_window_size(1920, 1080)
        self.driver.maximize_window() # 한 번 더 확실하게

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

    def _handle_cloudflare_challenge(self):
        print("[Info] Cloudflare 우회 시도 시작...")

        # -------------------------------------------------------
        # 1단계: Shadow DOM 내부의 체크박스 찾기 (최신 Cloudflare 대응)
        # -------------------------------------------------------
        try:
            print("[Info] 1단계: Shadow DOM 탐색 시도")
            # 자바스크립트로 Shadow DOM 내부의 input 요소 찾아서 클릭
            self.driver.execute_script("""
                let target = document.querySelector('input[type=checkbox]');
                if (!target) {
                    // Shadow DOM 안에 숨어있는 경우 (Deep Search)
                    function findInShadow(root) {
                        let el = root.querySelector('input[type=checkbox]');
                        if (el) return el;
                        let walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, null, false);
                        while(node = walker.nextNode()) {
                            if (node.shadowRoot) {
                                let found = findInShadow(node.shadowRoot);
                                if (found) return found;
                            }
                        }
                        return null;
                    }
                    target = findInShadow(document.body);
                }
                if (target) target.click();
            """)
            time.sleep(3)
        except Exception as e:
            print(f"[Warning] 1단계 실패: {e}")

        # -------------------------------------------------------
        # 2단계: iframe이 있다면 무조건 진입 (이름 필터링 제거)
        # -------------------------------------------------------
        try:
            # 이름 따지지 않고 모든 iframe을 뒤져봅니다.
            frames = self.driver.find_elements(By.TAG_NAME, "iframe")
            print(f"[Info] 발견된 iframe 개수: {len(frames)}")

            for i, frame in enumerate(frames):
                try:
                    # iframe 위치와 크기 확인 (너무 작거나 안 보이는건 패스)
                    if frame.size['width'] > 0 and frame.size['height'] > 0:
                        print(f"[Info] iframe[{i}] 진입 시도...")
                        self.driver.switch_to.frame(frame)

                        # 체크박스 찾기 시도
                        checkbox = self.driver.find_elements(By.XPATH, "//input[@type='checkbox']")
                        if checkbox:
                            print(f"[Info] iframe[{i}] 에서 체크박스 발견! 클릭!")
                            ActionChains(self.driver).move_to_element(checkbox[0]).click().perform()
                            self.driver.switch_to.default_content()
                            time.sleep(3)
                            return # 성공했으면 종료

                        self.driver.switch_to.default_content() # 복귀
                except:
                    self.driver.switch_to.default_content()
        except Exception as e:
            print(f"[Warning] 2단계 실패: {e}")

        # -------------------------------------------------------
        # 3단계: 동적 좌표 계산 클릭 (수정됨)
        # -------------------------------------------------------
        print("[Info] 3단계: 화면 중앙 클릭 시도 (Dynamic Center Click)")
        try:
            # 현재 브라우저의 실제 크기를 가져옵니다.
            size = self.driver.get_window_size()
            width = size['width']
            height = size['height']

            print(f"[Debug] 현재 브라우저 크기: {width} x {height}")

            if width < 100 or height < 100:
                print("[Error] 브라우저 창이 너무 작습니다! 강제 리사이즈 시도.")
                self.driver.set_window_size(1920, 1080)
                width = 1920
                height = 1080

            # 정중앙 좌표 계산
            center_x = width // 2
            center_y = height // 2

            # Cloudflare 박스는 보통 정중앙보다 살짝 위(약 100px)에 위치함
            target_y = center_y - 50

            action = ActionChains(self.driver)

            # [중요] move_by_offset은 '현재 마우스 위치' 기준이므로
            # 먼저 (0,0)으로 보내고 이동하거나, 요소가 없으니 body 기준으로 이동해야 함.
            # 가장 안전한 방법: reset_actions() 후 move_to_element_with_offset 사용

            # body 태그 찾기 (기준점)
            body = self.driver.find_element(By.TAG_NAME, "body")

            # body의 왼쪽 위(0,0)를 기준으로 중앙으로 이동
            action.move_to_element_with_offset(body, center_x, target_y).click().perform()
            print(f"[Info] 클릭 실행 좌표: ({center_x}, {target_y})")

            time.sleep(1)

            # 혹시 모르니 약간 아래도 한번 더 클릭 (더블 탭 전략)
            action.move_to_element_with_offset(body, center_x, target_y + 60).click().perform()

        except Exception as e:
            print(f"[Error] 3단계 실패: {e}")

        time.sleep(5) # 클릭 후 통과 대기

    def process_request( self, request, spider ):
        self.driver.get( request.url )
        print(f"[Info : {datetime.now()}]{spider.name}이 드라이버 사용함")

        try:
            self._handle_cloudflare_challenge()
            # self._wait_cloudflare_done(timeout=20)
        except TimeoutException:
            self.driver.save_screenshot("/var/task/logs/debug_error.png")
            spider.logger.warning(f"Cloudflare 대기 해제 안 됨 (20초 내): {request.url}")

        body = to_bytes( text=self.driver.page_source )
        print(f"[Info : {datetime.now()}]{spider.name}이 드라이버로 잘 긁어옴 사용함")
        return HtmlResponse( url=request.url, body=body, encoding='utf-8', request=request )
