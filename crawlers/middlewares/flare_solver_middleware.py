import json
import requests
from scrapy.http import HtmlResponse

class FlareSolverrMiddleware:
    def __init__(self, flaresolverr_url):
        self.flaresolverr_url = flaresolverr_url
        self.cached_cookies = {} # 도메인별 쿠키 저장소

    @classmethod
    def from_crawler(cls, crawler):
        # settings.py에서 URL을 가져옴
        return cls(
            flaresolverr_url=crawler.settings.get('FLARESOLVERR_URL', 'http://localhost:8191/v1')
        )

    def process_request(self, request, spider):
        # 1. 메타 태그를 확인해 FlareSolverr를 탈지 말지 결정
        if not request.meta.get('use_flaresolverr', False):
            return None  # 일반 요청은 그냥 통과

        spider.logger.info(f"FlareSolverr로 요청 중: {request.url}")

        # 1. 이미 캐싱된 유효한 쿠키가 있으면 FlareSolverr를 건너뜀
        domain = request.url.split('/')[2]
        if domain in self.cached_cookies:
            # 기존 요청에 쿠키를 심어서 보냄 (일반 Scrapy 속도)
            request.cookies.update(self.cached_cookies[domain])
            return None # None을 반환하면 Scrapy 기본 다운로더가 처리함

        # 2. 쿠키가 없으면 FlareSolverr 호출
        spider.logger.info(f"⚡ 쿠키 획득을 위해 FlareSolverr 호출: {request.url}")

        payload = {
            "cmd": "request.get",
            "url": request.url,
            "maxTimeout": 60000,
        }

        try:
            resp = requests.post(self.flaresolverr_url, json=payload, headers={"Content-Type": "application/json"})
            data = resp.json()

            if data.get('status') == 'ok':
                solution = data.get('solution')

                # 3. [핵심] 쿠키 저장
                cookies_dict = {c['name']: c['value'] for c in solution['cookies']}
                self.cached_cookies[domain] = cookies_dict

                # 4. User-Agent도 맞춰줘야 안 튕김
                request.headers['User-Agent'] = solution['userAgent']

                # 첫 요청은 FlareSolverr가 가져온 결과를 그대로 반환
                return HtmlResponse(
                    url=request.url,
                    status=200,
                    body=solution['response'],
                    encoding='utf-8',
                    request=request
                )
        except Exception:
            return None
    #
    # def process_request(self, request, spider):
    #     # 1. 메타 태그를 확인해 FlareSolverr를 탈지 말지 결정
    #     if not request.meta.get('use_flaresolverr', False):
    #         return None  # 일반 요청은 그냥 통과
    #
    #     spider.logger.info(f"FlareSolverr로 요청 중: {request.url}")
    #
    #     # 2. FlareSolverr API 요청 페이로드 구성
    #     payload = {
    #         "cmd": "request.get",
    #         "url": request.url,
    #         "maxTimeout": 60000,
    #         # 세션이 필요하면 아래 주석 해제 (spider에서 session_id 관리 필요)
    #         # "session": request.meta.get('session_id')
    #     }
    #
    #     try:
    #         # 3. FlareSolverr 호출
    #         resp = requests.post(
    #             self.flaresolverr_url,
    #             headers={"Content-Type": "application/json"},
    #             json=payload,
    #             timeout=60000 # requests 자체 타임아웃은 넉넉하게
    #         )
    #
    #         resp_data = resp.json()
    #
    #         if resp_data.get('status') == 'ok':
    #             solution = resp_data.get('solution')
    #             html_source = solution['response']
    #
    #             # 4. Scrapy가 처리할 수 있는 Response 객체로 변환하여 반환
    #             # 이렇게 리턴하면 다운로더를 거치지 않고 바로 spider.parse로 갑니다.
    #             return HtmlResponse(
    #                 url=request.url,
    #                 status=200,
    #                 body=html_source,
    #                 encoding='utf-8',
    #                 request=request
    #             )
    #         else:
    #             spider.logger.error(f"FlareSolverr Error: {resp_data.get('message')}")
    #             # 에러 시 재시도 로직 등을 추가하거나 None을 반환해 일반 요청으로 넘길 수 있음
    #             return None
    #
    #     except Exception as e:
    #         spider.logger.error(f"FlareSolverr 연결 실패: {e}")
    #         return None
