import json
import requests
from scrapy.http import HtmlResponse
from scrapy.exceptions import IgnoreRequest
from urllib.parse import urlparse

class FlareSolverrMiddleware:
    def __init__(self, flaresolverr_url):
        self.flaresolverr_url = flaresolverr_url
        # 도메인별 쿠키와 User-Agent를 저장할 캐시
        self.cached_cookies = {}
        self.cached_user_agents = {}

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            flaresolverr_url=crawler.settings.get('FLARESOLVERR_URL', 'http://localhost:8191/v1')
        )

    def _get_domain(self, url):
        return urlparse(url).netloc

    def process_request(self, request, spider):
        # 1. FlareSolverr 사용 설정이 없으면 패스
        if not request.meta.get('use_flaresolverr', False):
            return None

        domain = self._get_domain(request.url)

        # 2. [핵심] 이미 유효한 쿠키가 캐시에 있는 경우 -> FlareSolverr 건너뛰기
        if domain in self.cached_cookies:
            # spider.logger.debug(f"⚡ [Cache Hit] FlareSolverr 생략: {request.url}")
            request.cookies = self.cached_cookies[domain]
            request.headers['User-Agent'] = self.cached_user_agents[domain]
            return None  # None을 반환하면 Scrapy 기본 다운로더가 작동 (빠름)

        # 3. 쿠키가 없으면 FlareSolverr 호출 (느림)
        spider.logger.info(f"🐢 [Cache Miss] FlareSolverr 호출 중: {request.url}")
        return self._call_flaresolverr(request, spider)

    def process_response(self, request, response, spider):
        # 1. FlareSolverr를 안 쓰는 요청은 패스
        if not request.meta.get('use_flaresolverr', False):
            return response

        # 2. 만약 쿠키를 썼는데도 403/503(Cloudflare 차단)이 떴다면? -> 쿠키 만료됨
        if response.status in [403, 503]:
            domain = self._get_domain(request.url)
            spider.logger.warning(f"🚫 [Blocked] 쿠키 만료 감지. 재발급 시도: {request.url}")

            # 캐시 삭제
            if domain in self.cached_cookies:
                del self.cached_cookies[domain]
                del self.cached_user_agents[domain]

            # FlareSolverr로 강제 재요청 (여기서 새 쿠키를 얻어옴)
            return self._call_flaresolverr(request, spider)

        return response

    def _call_flaresolverr(self, request, spider):
        """FlareSolverr API를 호출하고 결과를 Scrapy Response로 반환하며 쿠키를 캐싱함"""
        payload = {
            "cmd": "request.get",
            "url": request.url,
            "maxTimeout": 60000,
        }

        try:
            resp = requests.post(
                self.flaresolverr_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=70
            )
            data = resp.json()

            if data.get('status') == 'ok':
                solution = data.get('solution')
                domain = self._get_domain(request.url)

                # [중요] 새로 얻은 쿠키와 UA를 캐싱
                cookies_dict = {c['name']: c['value'] for c in solution['cookies']}
                self.cached_cookies[domain] = cookies_dict
                self.cached_user_agents[domain] = solution['userAgent']

                spider.logger.info(f"✅ [Solved] 새 쿠키 획득 성공 ({domain})")

                return HtmlResponse(
                    url=request.url,
                    status=200,
                    body=solution['response'],
                    encoding='utf-8',
                    request=request
                )
            else:
                spider.logger.error(f"FlareSolverr Error: {data.get('message')}")
                return None # 에러 시 일반 요청으로 넘기거나 재시도 로직 필요

        except Exception as e:
            spider.logger.error(f"FlareSolverr 연결 실패: {e}")
            return None
