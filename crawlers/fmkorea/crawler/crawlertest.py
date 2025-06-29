# 필요한 패키지 설치 (한 번만)
# pip install selenium webdriver-manager
import os
import time

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


def crawl_example():
    # 1. Chrome 옵션 설정 (헤드리스 모드)
    chrome_options = Options()
    chrome_options.add_argument("--headless")
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

# 로컬에서 테스트할 경우에 아래 두 줄을 주석처리한 후 테스트 한다. '/opt/chrome', '/opt/chromedriver'는 이미지 상에 존재하는 폴더이므로 주석처리
    chrome_options.binary_location = '/opt/chrome/chrome' # 로컬에서는 주석처리한다.
    driver  = webdriver.Chrome(service=Service(executable_path="/opt/chromedriver", service_log_path=os.devnull), options=chrome_options) # 로컬에서는 주석처리

    try:
        for i in range(1, 10):
            # 3. 타겟 URL 열기
            url = f'https://www.fmkorea.com/?mid=hotdeal&sort_index=pop&order_type=desc&listStyle=webzine&cpage=4&page={i}'
            driver.get(url)
            time.sleep(3)
            # 최대 재시도 횟수
            max_retries = 10
            attempt = 0
            wait = WebDriverWait(driver, 30)
            print(f"타겟 url : {url}")
            while '에펨코리아 보안 시스템' in driver.title and attempt < max_retries:
                print(f"[재시도 {attempt+1}/{max_retries}] 타이틀: {driver.title} → 수동 갱신 클릭")
                try:
                    reload_link = wait.until(EC.element_to_be_clickable(
                        (By.XPATH, "//a[contains(@href,'javascript:location.reload')]")
                    ))
                    time.sleep(3)
                    reload_link.click()
                    # 갱신 후 타이틀이 바뀔 때까지 짧게 대기
                    wait.until_not(EC.title_contains('에펨코리아 보안 시스템'))
                except TimeoutException:
                    print("    → 재시도 중 Timeout 발생, 잠시 대기 후 다시 시도")
                attempt += 1

            # 결과 확인
            if '에펨코리아 보안 시스템' in driver.title:
                print("⚠️ 최대 재시도 후에도 보안 시스템 페이지가 계속 보입니다.")
            else:
                print("✅ 보안 시스템 문구 사라짐, 최종 타이틀:", driver.title)

            # 페이지 소스 출력
            print("=== 최종 페이지 소스 ===")
            print(driver.page_source)

    finally:
        # 6. 드라이버 종료
        driver.quit()

if __name__ == '__main__':
    crawl_example()
