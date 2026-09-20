"""Reuse one browser per spider/domain and release documents between requests."""
import hashlib
from urllib.parse import urlparse

import requests
from scrapy import signals
from scrapy.http import HtmlResponse


class FlareSolverrMiddleware:
    def __init__(self, flaresolverr_url, stats=None):
        self.flaresolverr_url = flaresolverr_url
        self.stats = stats
        self.cached_cookies = {}
        self.cached_user_agents = {}
        self.sessions = {}
        self.http_failures = {}
        self.client = requests.Session()
        self.client.trust_env = False

    @classmethod
    def from_crawler(cls, crawler):
        middleware = cls(crawler.settings.get('FLARESOLVERR_URL', 'http://localhost:8191/v1'), crawler.stats)
        crawler.signals.connect(middleware.spider_closed, signal=signals.spider_closed)
        return middleware

    def count(self, key):
        if self.stats is not None:
            self.stats.inc_value('flare/' + key)

    def _get_domain(self, url):
        return urlparse(url).netloc

    def process_request(self, request, spider):
        if not request.meta.get('use_flaresolverr', False):
            return None
        request.meta.pop('_flare_browser_response', None)
        domain = self._get_domain(request.url)
        if domain in self.cached_cookies and self.http_failures.get(domain, 0) < 2:
            # Run before Scrapy's CookiesMiddleware (700), which builds the header.
            request.cookies = self.cached_cookies[domain]
            request.headers['User-Agent'] = self.cached_user_agents[domain]
            self.count('http_attempts')
            return None
        return self._call_flaresolverr(request, spider)

    def process_response(self, request, response, spider):
        if not request.meta.get('use_flaresolverr', False) or request.meta.get('_flare_browser_response'):
            return response
        domain = self._get_domain(request.url)
        if response.status in (403, 503):
            # Some sites bind clearance to the browser. Do not repeat failed HTTP
            # attempts indefinitely when the reusable browser still works.
            self.http_failures[domain] = self.http_failures.get(domain, 0) + 1
            self.count('http_blocked')
            return self._call_flaresolverr(request, spider)
        if 200 <= response.status < 300:
            self.count('http_success')
        return response

    def _api(self, payload, timeout):
        response = self.client.post(self.flaresolverr_url, json=payload, timeout=(3, timeout))
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get('status') != 'ok':
            raise ValueError('FlareSolverr did not return a successful result')
        return data

    def _session(self, domain, spider):
        if domain not in self.sessions:
            # Stable names reclaim the same session after a process crash.
            key = hashlib.sha256((spider.name + ':' + domain).encode()).hexdigest()[:20]
            self.sessions[domain] = 'geteverything-' + key
        return self.sessions[domain]

    def _destroy(self, domain, spider):
        session = self.sessions.pop(domain, None)
        if session is None:
            return
        try:
            self._api({'cmd': 'sessions.destroy', 'session': session}, 10)
            self.count('sessions_closed')
        except (requests.RequestException, ValueError):
            spider.logger.warning('Could not close the managed FlareSolverr session')

    def _park(self, domain, session, spider):
        try:
            # Keep cookies while stopping page timers, advertising and media.
            self._api({'cmd': 'request.get', 'url': 'about:blank', 'session': session, 'maxTimeout': 5000}, 10)
            self.count('documents_released')
        except (requests.RequestException, ValueError):
            self._destroy(domain, spider)

    def _call_flaresolverr(self, request, spider):
        domain = self._get_domain(request.url)
        session = self._session(domain, spider)
        request.meta['_flare_browser_response'] = True
        request.meta.setdefault('max_retry_times', 1)
        self.count('browser_requests')
        try:
            data = self._api({'cmd': 'request.get', 'url': request.url, 'session': session,
                              'session_ttl_minutes': 10, 'maxTimeout': 60000}, 70)
            solution = data.get('solution') or {}
            body = solution.get('response')
            if not isinstance(body, str) or not body.strip():
                raise ValueError('Missing browser document')
            status = int(solution.get('status', 502))
            if 200 <= status < 300 and solution.get('userAgent'):
                self.cached_cookies[domain] = {c['name']: c['value'] for c in solution.get('cookies', [])}
                self.cached_user_agents[domain] = solution['userAgent']
                self.count('browser_success')
            return HtmlResponse(url=solution.get('url') or request.url, status=status, body=body,
                                encoding='utf-8', request=request)
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            self.count('browser_errors')
            spider.logger.warning('FlareSolverr request failed (%s)', type(exc).__name__)
            self._destroy(domain, spider)
            return HtmlResponse(url=request.url, status=503, body=b'', request=request)
        finally:
            if domain in self.sessions:
                self._park(domain, session, spider)

    def spider_closed(self, spider, reason=None):
        for domain in list(self.sessions):
            self._destroy(domain, spider)
        self.client.close()
