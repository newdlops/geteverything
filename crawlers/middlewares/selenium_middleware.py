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
            self.driver.set_window_size(1920, 1080)
            size = self.driver.get_window_size()
            width = size['width']
            height = size['height']

            print(f"[Debug] 현재 브라우저 크기: {width} x {height}")
            step_x = 80  # 가로 간격 (Cloudflare 박스 크기 고려)
            step_y = 80  # 세로 간격

            # 2. 탐색 영역 설정 (화면 중앙부 위주로 효율적 탐색)
            # 너무 외곽은 클릭해봤자 의미가 없으므로 제외합니다.
            start_x = width // 5      # 왼쪽 20% 지점부터
            end_x = width * 4 // 5    # 오른쪽 80% 지점까지
            start_y = height // 5     # 상단 20% 지점부터
            end_y = height * 3 // 5   # 하단 60% 지점까지 (보통 상단/중앙에 뜸)

            click_count = 0

            # 3. 이중 루프로 좌표 생성 및 JS 클릭 실행
            # y축(세로) 방향으로 내려오면서 x축(가로)을 훑는 방식
            for y in range(start_y, end_y, step_y):
                for x in range(start_x, end_x, step_x):
                    # 탐지 회피를 위한 약간의 랜덤 오차
                    rand_x = x + random.randint(-5, 5)
                    rand_y = y + random.randint(-5, 5)

                    # ActionChains 대신 빠르고 에러 없는 JS 클릭 사용
                    try:
                        self.driver.execute_script("""
                            var x = arguments[0];
                            var y = arguments[1];
                            
                            // 해당 좌표의 최상단 요소를 찾음
                            var el = document.elementFromPoint(x, y);
                            if(el) {
                                // 클릭 이벤트 생성 및 발송
                                var ev = new MouseEvent('click', {
                                    'view': window, 'bubbles': true, 'cancelable': true,
                                    'clientX': x, 'clientY': y
                                });
                                el.dispatchEvent(ev);
                            }
                        """, rand_x, rand_y)
                        click_count += 1
                        # 브라우저 부하 방지 및 사람처럼 보이기 위한 미세 딜레이
                        time.sleep(random.uniform(0.03, 0.07))
                    except:
                        pass # 개별 클릭 에러는 무시하고 계속 진행

            print(f"[Info] 그리드 스캔 완료. 총 {click_count}회 클릭 발사.")

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
