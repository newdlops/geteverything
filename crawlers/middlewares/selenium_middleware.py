import os
import random
import shutil
import sys
import time
import uuid
from datetime import datetime
from urllib.parse import urlparse

from scrapy import signals
from scrapy.http import HtmlResponse
from scrapy.utils.python import to_bytes

from selenium import webdriver
from selenium.common import TimeoutException
from selenium.webdriver import ActionChains, Keys
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
        self._driver_proxy = None
        self._temp_driver_path = None
        self._cookiejars = {}
        self._active_cookiejar = None
        self._active_netloc = None
        self._settings = None

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
        # request.headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36'
        # Referer, Origin, Host 등 전부 없음

    def spider_opened(self, spider):
        # WebDriver는 첫 request에서 (proxy/cookiejar를 보고) 지연 생성합니다.
        self._settings = spider.crawler.settings
        os.makedirs("/tmp/selenium", exist_ok=True)

    def _normalize_proxy(self, proxy):
        if not proxy:
            return None
        if isinstance(proxy, bytes):
            proxy = proxy.decode("utf-8", errors="ignore")
        proxy = str(proxy).strip()
        if not proxy:
            return None
        if "://" not in proxy:
            proxy = f"http://{proxy}"
        return proxy

    def _url_parts(self, url: str):
        parsed = urlparse(url)
        return parsed.scheme or "http", parsed.netloc

    def _is_exec_file(self, path: str | None) -> bool:
        if not path:
            return False
        return os.path.isfile(path) and os.access(path, os.X_OK)

    def _resolve_chrome_binary(self) -> str | None:
        env_candidates = [
            os.environ.get("CHROME_BINARY"),
            os.environ.get("CHROME_BIN"),  # Dockerfile에서 사용
            os.environ.get("GOOGLE_CHROME_BIN"),
        ]
        candidates: list[str] = [p for p in env_candidates if p]

        if sys.platform.startswith("linux"):
            candidates += [
                "/bin/chromium",
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/opt/chrome/chrome",
            ]
            which_names = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")
        elif sys.platform == "darwin":
            candidates += [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
                "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
            ]
            which_names = ("google-chrome", "chromium", "chrome")
        else:
            which_names = ("chrome", "chromium", "google-chrome", "msedge")

        for name in which_names:
            found = shutil.which(name)
            if found:
                candidates.append(found)

        for path in candidates:
            if self._is_exec_file(path):
                return path
        return None

    def _resolve_chromedriver(self) -> str | None:
        env_candidates = [
            os.environ.get("CHROMEDRIVER_PATH"),
            os.environ.get("CHROMEDRIVER"),
        ]
        candidates: list[str] = [p for p in env_candidates if p]

        if sys.platform.startswith("linux"):
            candidates += [
                "/bin/chromedriver",
                "/usr/bin/chromedriver",
                "/opt/chromedriver",
                "/opt/chromedriver/chromedriver",
            ]
        elif sys.platform == "darwin":
            candidates += [
                "/opt/homebrew/bin/chromedriver",
                "/usr/local/bin/chromedriver",
            ]

        found = shutil.which("chromedriver")
        if found:
            candidates.append(found)

        for path in candidates:
            if self._is_exec_file(path):
                return path
        return None

    def _copy_chromedriver(self, spider):
        original_driver_path = self._resolve_chromedriver()
        if not original_driver_path:
            spider.logger.warning("chromedriver 경로를 찾지 못했습니다. (로컬 테스트면 설치/경로 설정 필요)")
            spider.logger.warning("CHROMEDRIVER_PATH 또는 PATH의 chromedriver를 확인하세요.")
            return None

        temp_driver_filename = f"chromedriver_{uuid.uuid4()}"
        temp_driver_path = os.path.join("/tmp", temp_driver_filename)

        try:
            shutil.copy2(original_driver_path, temp_driver_path)
            os.chmod(temp_driver_path, 0o755)  # 실행 권한 부여
            spider.logger.info(f"Driver copied to: {temp_driver_path}")
            return temp_driver_path
        except Exception as e:
            spider.logger.error(f"드라이버 복사 실패: {e}")
            raise

    def _destroy_driver(self, spider):
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
        self.driver = None
        self._driver_proxy = None
        self._active_cookiejar = None
        self._active_netloc = None

        if self._temp_driver_path:
            try:
                os.remove(self._temp_driver_path)
            except Exception:
                pass
            self._temp_driver_path = None

    def _create_driver(self, spider, proxy: str | None):
        self._temp_driver_path = self._copy_chromedriver(spider)

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

        if proxy:
            chrome_options.add_argument(f"--proxy-server={proxy}")

        # chrome_options.add_argument("--user-data-dir=/tmp/user-data")
        # chrome_options.add_argument("--data-path=/tmp/data")
        # chrome_options.add_argument("--disk-cache-dir=/tmp/cache")

        chrome_binary = self._resolve_chrome_binary()
        if chrome_binary:
            chrome_options.binary_location = chrome_binary
        else:
            spider.logger.warning("Chrome/Chromium 바이너리 경로를 찾지 못했습니다. (로컬 테스트면 설치/경로 설정 필요)")
            spider.logger.warning("CHROME_BIN 또는 CHROME_BINARY 환경변수로 지정할 수 있습니다.")

        uc_kwargs = {
            "options": chrome_options,
            "use_subprocess": True,
        }
        if self._temp_driver_path:
            uc_kwargs["driver_executable_path"] = self._temp_driver_path

        driver = uc.Chrome(**uc_kwargs)
        # driver  = webdriver.Chrome() # 운영에서 주석처리 로컬에서는 살림

        stealth(driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True,
                )


        page_load_timeout = spider.crawler.settings.getint("SELENIUM_PAGE_LOAD_TIMEOUT", 60)
        script_timeout = spider.crawler.settings.getint("SELENIUM_SCRIPT_TIMEOUT", 60)
        driver.set_page_load_timeout(page_load_timeout)
        driver.set_script_timeout(script_timeout)

        try:
            driver.execute_cdp_cmd("Network.enable", {})
        except Exception:
            pass

        # [핵심 수정] 브라우저가 켜진 직후, 강제로 크기를 주입합니다.
        # 이것이 없으면 VM에서 종종 800x600으로 시작해서 "Out of bounds" 에러가 납니다.
        driver.set_window_size(1920, 1080)
        try:
            driver.maximize_window()  # 한 번 더 확실하게
        except Exception:
            pass

        return driver

    def _ensure_driver(self, spider, proxy: str | None):
        proxy = self._normalize_proxy(proxy)
        if self.driver is not None and self._driver_proxy == proxy:
            return
        if self.driver is not None:
            spider.logger.info(f"Proxy changed -> restart Chrome: {self._driver_proxy} -> {proxy}")
        self._destroy_driver(spider)
        self.driver = self._create_driver(spider, proxy)
        self._driver_proxy = proxy

    def _clear_browser_cookies(self, spider):
        if self.driver is None:
            return
        try:
            self.driver.execute_cdp_cmd("Network.clearBrowserCookies", {})
            return
        except Exception:
            pass
        try:
            self.driver.delete_all_cookies()
        except Exception:
            pass

    def _set_cookies_for_url(self, spider, cookies, url: str):
        if self.driver is None or not cookies:
            return
        scheme, netloc = self._url_parts(url)
        if not netloc:
            return
        base_url = f"{scheme}://{netloc}/"

        for cookie in cookies:
            name = cookie.get("name")
            value = cookie.get("value")
            if not name or value is None:
                continue
            params = {"name": name, "value": value, "url": base_url}
            if cookie.get("path"):
                params["path"] = cookie["path"]
            if "secure" in cookie:
                params["secure"] = cookie["secure"]
            if "httpOnly" in cookie:
                params["httpOnly"] = cookie["httpOnly"]
            if cookie.get("sameSite"):
                params["sameSite"] = cookie["sameSite"]
            if "expiry" in cookie:
                params["expires"] = cookie["expiry"]
            try:
                self.driver.execute_cdp_cmd("Network.setCookie", params)
            except Exception:
                continue

    def _apply_cookiejar(self, spider, cookiejar_key: str, url: str):
        scheme, netloc = self._url_parts(url)
        if not netloc:
            return

        if cookiejar_key == self._active_cookiejar and netloc == self._active_netloc:
            return

        self._clear_browser_cookies(spider)
        cookies = self._cookiejars.get(cookiejar_key, {}).get(netloc, [])
        self._set_cookies_for_url(spider, cookies, url)

        self._active_cookiejar = cookiejar_key
        self._active_netloc = netloc

    def _persist_cookiejar(self, spider, cookiejar_key: str, url: str):
        if self.driver is None:
            return
        scheme, netloc = self._url_parts(url)
        if not netloc:
            return
        try:
            cookies = self.driver.get_cookies()
        except Exception:
            return
        self._cookiejars.setdefault(cookiejar_key, {})[netloc] = cookies

    def spider_closed(self, spider):
        self._destroy_driver(spider)

    def _wait_cloudflare_done(self, timeout=20):
        wait = WebDriverWait(self.driver, timeout, poll_frequency=0.25)

        def not_cloudflare_page(driver):
            # title 기반(빠름)으로 먼저 판단하고, 애매하면 HTML도 확인합니다.
            try:
                title = (driver.title or "").lower()
                if "just a moment" in title:
                    return False
            except Exception:
                pass

            src = (driver.page_source or "").lower()
            if "cf-chl" in src:
                return False
            if "just a moment" in src and "cloudflare" in src:
                return False
            if "challenge-platform" in src and ("turnstile" in src or "cloudflare" in src):
                return False
            return True

        wait.until(not_cloudflare_page)

    def _is_cloudflare_challenge_page(self) -> bool:
        if self.driver is None:
            return False

        try:
            title = (self.driver.title or "").lower()
            if "just a moment" in title:
                return True
            if "cloudflare" in title and ("attention required" in title or "access denied" in title):
                return True
        except Exception:
            pass

        try:
            src = (self.driver.page_source or "").lower()
        except Exception:
            return False

        if "cf-chl" in src:
            return True
        if "just a moment" in src and "cloudflare" in src:
            return True
        if "challenge-platform" in src and ("turnstile" in src or "cloudflare" in src):
            return True
        return False

    def _handle_cloudflare_challenge(self):
        if not self._is_cloudflare_challenge_page():
            print("[Info] Cloudflare challenge not detected")
            return

        timeout_seconds = 6
        pre_delay_seconds = 0.5
        tab_attempts = 3
        tab_pause_seconds = 0.15
        space_pause_seconds = 0.2

        if self._settings is not None:
            timeout_seconds = self._settings.getint("SELENIUM_CLOUDFLARE_TIMEOUT", timeout_seconds)
            pre_delay_seconds = self._settings.getfloat("SELENIUM_CLOUDFLARE_PRE_DELAY", pre_delay_seconds)
            tab_attempts = self._settings.getint("SELENIUM_CLOUDFLARE_TAB_ATTEMPTS", tab_attempts)
            tab_pause_seconds = self._settings.getfloat("SELENIUM_CLOUDFLARE_TAB_PAUSE", tab_pause_seconds)
            space_pause_seconds = self._settings.getfloat("SELENIUM_CLOUDFLARE_SPACE_PAUSE", space_pause_seconds)

        start = time.monotonic()
        print("[Info] Cloudflare challenge detected: quick solve attempt")
        if pre_delay_seconds > 0:
            time.sleep(pre_delay_seconds)

        # 1. 포커스 강제 이동 (Shadow DOM 뚫기)
        try:
            # 체크박스 요소를 찾아서 JS로 'focus' 상태만 만듭니다 (클릭 X)
            # 클릭은 Selenium의 물리 키보드 입력으로 처리합니다.
            focused = self.driver.execute_script("""
                let target = document.querySelector('input[type=checkbox]');
                if (!target) {
                    // Shadow DOM 탐색
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
                if (target) {
                    target.focus(); // [핵심] 마우스 대신 포커스만 줌
                    return true;
                }
                return false;
            """)
            if focused:
                # 2. 물리적 키보드 'Space' 입력 발송
                ActionChains(self.driver).send_keys(Keys.SPACE).perform()
                time.sleep(space_pause_seconds)
                print("[Info] Space 키 입력 완료")

        except Exception as e:
            print(f"[Warning] 키보드 접근 실패: {e}")

        # 3. 만약 JS 포커스가 실패했다면? -> 맹목적 Tab 연타
        # Turnstile은 보통 페이지의 첫 번째나 두 번째 'Tab' 위치에 있습니다.
        print("[Info] fallback: Tab+Space attempts")
        try:
            # 화면 빈 곳 클릭해서 포커스 초기화 (실패해도 무시)
            try:
                ActionChains(self.driver).move_by_offset(10, 10).click().perform()
            except Exception:
                pass

            # Tab을 몇 번 누르면서 매번 Space를 눌러봄
            for _ in range(max(0, tab_attempts)):
                ActionChains(self.driver).send_keys(Keys.TAB).pause(tab_pause_seconds).send_keys(Keys.SPACE).pause(space_pause_seconds).perform()
                if not self._is_cloudflare_challenge_page():
                    break

        except Exception as e:
            print(f"[Error] Tab 연타 실패: {e}")

        remaining = max(0.0, float(timeout_seconds) - (time.monotonic() - start))
        if remaining > 0:
            self._wait_cloudflare_done(timeout=remaining)
        elif self._is_cloudflare_challenge_page():
            raise TimeoutException(f"Cloudflare challenge not cleared within {timeout_seconds}s")

    def solver_init(self, request):
        if request.meta.get('bypass_cloudflare', False):
            import requests

            payload = {
                "cmd": "request.get",
                "url": request.url,
                "maxTimeout": 60000
            }
            fs_resp = requests.post("http://localhost:8191/v1", json=payload).json()

            if fs_resp.get('status') == 'ok':
                cookies = fs_resp['solution']['cookies']
                user_agent = fs_resp['solution']['userAgent']

                # 2. 로컬 Selenium 드라이버 설정
                # 중요: 쿠키를 세팅하기 위해선 해당 도메인에 먼저 진입하거나 CDP를 써야 함
                # 여기서는 CDP(Chrome DevTools Protocol)로 설정하는 게 가장 깔끔함
                self.driver.execute_cdp_cmd('Network.setUserAgentOverride', {"userAgent": user_agent})

                # 도메인 진입 전 404 페이지 등으로 이동하거나,
                # 바로 get 후 쿠키 심고 refresh 하는 방법 사용
                self.driver.get(request.url)

                for cookie in cookies:
                    # Selenium add_cookie는 domain 등 엄격하게 체크하므로 필요한 필드만 정제
                    cookie_dict = {
                        'name': cookie['name'],
                        'value': cookie['value'],
                        # 'domain': cookie['domain'] # 상황에 따라 제외 필요할 수 있음
                    }
                    try:
                        self.driver.add_cookie(cookie_dict)
                    except:
                        pass

                # 3. 쿠키 장착 후 새로고침 (이제 뚫립니다)
                self.driver.refresh()

    def process_request( self, request, spider ):
        proxy = request.meta.get("proxy")
        self.solver_init(request)
        cookiejar_key = str(request.meta.get("cookiejar", 0))

        self._ensure_driver(spider, proxy)
        self._apply_cookiejar(spider, cookiejar_key, request.url)

        try:
            self.driver.get(request.url)
        except TimeoutException:
            screenshot_path = f"/tmp/selenium_timeout_{spider.name}_{uuid.uuid4()}.png"
            try:
                self.driver.save_screenshot(screenshot_path)
            except Exception:
                pass
            spider.logger.warning(f"page load timeout: {request.url} (screenshot={screenshot_path})")
        print(f"[Info : {datetime.now()}]{spider.name}이 드라이버 사용함 (proxy={self._driver_proxy}, cookiejar={cookiejar_key})")

        try:
            self._handle_cloudflare_challenge()
        except TimeoutException:
            screenshot_path = f"/tmp/selenium_cloudflare_timeout_{spider.name}_{uuid.uuid4()}.png"
            try:
                self.driver.save_screenshot(screenshot_path)
            except Exception:
                pass
            cf_timeout = 6
            if self._settings is not None:
                cf_timeout = self._settings.getint("SELENIUM_CLOUDFLARE_TIMEOUT", cf_timeout)
            spider.logger.warning(f"Cloudflare 대기 해제 안 됨 ({cf_timeout}초 내): {request.url} (screenshot={screenshot_path})")

        self._persist_cookiejar(spider, cookiejar_key, self.driver.current_url or request.url)
        body = to_bytes( text=self.driver.page_source )
        print(f"[Info : {datetime.now()}]{spider.name}이 드라이버로 잘 긁어옴 사용함")
        return HtmlResponse( url=request.url, body=body, encoding='utf-8', request=request )
