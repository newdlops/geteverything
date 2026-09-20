"""Conservative, site-scoped availability checks using already downloaded HTML."""
import os
import re
from urllib.parse import parse_qs, urlsplit

from scrapy import Request


SITES = {
    'arca': ('ARCA', 'arca', {'arca.live'}),
    'fmkorea': ('FMKOREA', 'fm', {'fmkorea.com', 'www.fmkorea.com'}),
    'ppomppu': ('PPOMPPU', 'ppompu', {'ppomppu.co.kr', 'www.ppomppu.co.kr'}),
    'eomisae': ('EOMISAE', 'eomisae', {'eomisae.co.kr', 'www.eomisae.co.kr'}),
    'coolnjoy': ('coolnjoy', 'coolnjoy', {'coolenjoy.net', 'www.coolenjoy.net'}),
}
TITLE_SELECTORS = {
    'arca': '.article-head .title-row > .title',
    'fmkorea': '.rd_hd h1.np_18px',
    'ppomppu': '#topTitle h1',
    'eomisae': '#D_ ._hd h2 a.pjax',
    'coolnjoy': '#bo_v_title',
}
END_TITLE = re.compile(r'[\[(【]\s*(?:종료|품절|판매종료|마감|판매완료)\s*[\])】]|(?:^|\]\s*|\|\s*)종료된\s*(?:행사|핫딜|상품)입니다\.?\s*$')


def post_key(site, url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in {'http', 'https'} or parsed.hostname not in SITES[site][2]
                or parsed.username or parsed.password or parsed.port not in {None, 80, 443}):
            return None
        query = parse_qs(parsed.query)
        if site == 'arca':
            match = re.fullmatch(r'/b/hotdeal/(\d+)/?', parsed.path)
        elif site == 'coolnjoy':
            match = re.fullmatch(r'/bbs/jirum/(\d+)/?', parsed.path)
        elif site == 'ppomppu':
            if parsed.path != '/zboard/view.php' or query.get('id') != ['ppomppu']:
                return None
            value = query.get('no', [''])[0]
            return value if value.isdigit() else None
        else:
            value = query.get('document_srl', [''])[0]
            if value.isdigit():
                return value
            match = re.fullmatch(r'/(?:fs/)?(\d+)/?', parsed.path)
        return match.group(1) if match else None
    except (ValueError, KeyError):
        return None


def observation(outcome, evidence):
    return {'outcome': outcome, 'evidence': evidence}


def detect_availability(site, response):
    requested = response.request.url if response.request else response.url
    key = post_key(site, requested)
    if not key or post_key(site, response.url) != key:
        return observation('unknown', 'redirect-or-unexpected-url')
    # Challenge/error pages can return 200 or 404. Check their page title first,
    # never scan comments or adjacent listing cards for termination keywords.
    title = ' '.join(response.css('title::text').getall()).strip().lower()
    if any(text in title for text in ('just a moment', 'access denied', '보안 시스템', '접근 제한', '로그인')):
        return observation('unknown', 'access-blocked')
    if response.status == 404:
        return observation('missing', 'http-404')
    if response.status == 410:
        return observation('deleted', 'http-410')
    if response.status != 200:
        return observation('unknown', 'http-' + str(response.status))
    heading = response.css(TITLE_SELECTORS[site])
    if not heading:
        selector = {'ppomppu': '.error2', 'coolnjoy': '#validation_check .cbg',
                    'fmkorea': '.message.error', 'eomisae': '.message.error', 'arca': '.error-message'}[site]
        message = ' '.join(response.css(selector).xpath('string()').getall())
        if re.search(r'(?:게시물|게시글|글)(?:이|은)?\s*(?:존재하지 않습니다|삭제되었습니다|삭제된 게시물입니다)', message):
            return observation('deleted', 'source-missing-message')
        return observation('unknown', 'detail-not-recognized')
    if site == 'arca' and response.css('.article-head .title.close-deal'):
        return observation('ended', 'arca-close-deal')
    if site == 'fmkorea':
        document = response.css('.rd[data-docsrl]::attr(data-docsrl)').get()
        if document and document != key:
            return observation('unknown', 'document-id-mismatch')
        if response.css('.rd_body > .hotdeal_var8Y_msg'):
            return observation('ended', 'fmkorea-ended-banner')
    if site == 'eomisae':
        category = ''.join(response.css('#D_ ._hd span[title=Category]::text').getall()).strip()
        if category in {'종료', '품절', '정보종료'}:
            return observation('ended', 'eomisae-ended-category')
    text = ' '.join(heading.xpath('string()').getall()).strip()
    if END_TITLE.search(text):
        return observation('ended', 'explicit-ended-title')
    return observation('active', 'recognized-deal-detail')


class AvailabilitySpiderMixin:
    availability_site = None

    def deal_request(self, url, data, meta=None, headers=None, status_only=False):
        if self.availability_site == 'fmkorea':
            # Preserve the working board entry point and comment-page parameter.
            # Direct index.php links currently return the site's security page.
            document = post_key('fmkorea', url)
            if document:
                url = ('https://www.fmkorea.com/?mid=hotdeal&sort_index=&order_type=desc'
                       f'&document_srl={document}&listStyle=webzine&cpage=1')
        request_meta = {**(meta or {}), 'handle_httpstatus_list': [404, 410],
                        'availability_status_only': status_only}
        return Request(url, callback=self.parse_deal, errback=self.availability_error,
                       cb_kwargs={'data': data}, meta=request_meta, headers=headers,
                       priority=-100 if status_only else 0)

    def status_item(self, data, result):
        return {'article_id': data['article_id'], '_availability': result, '_status_only': True}

    def parse_deal(self, response, data):
        result = detect_availability(self.availability_site, response)
        status_only = response.meta.get('availability_status_only', False)
        if status_only or result['outcome'] in {'ended', 'deleted', 'missing', 'unknown'}:
            yield self.status_item(data, result)
        if status_only or result['outcome'] in {'deleted', 'missing', 'unknown'}:
            return
        # A separate ended observation survives missing price/date fields or a
        # downstream DropItem. Complete new ended deals can still be imported.
        for item in self.detail_parse(response, data):
            yield {**dict(item), '_availability': result}

    def availability_error(self, failure):
        data = failure.request.cb_kwargs['data']
        response = getattr(failure.value, 'response', None)
        evidence = 'http-' + str(response.status) if response is not None else 'request-failed'
        yield self.status_item(data, observation('unknown', evidence))

    def availability_rechecks(self):
        from crawlers.availability_store import due_deals, record_observation
        try:
            limit = max(0, min(5, int(os.environ.get('CRAWLER_STATUS_RECHECK_LIMIT', '5'))))
        except ValueError:
            limit = 5
        if not limit:
            return
        community, prefix, _ = SITES[self.availability_site]
        for deal in due_deals(community, limit):
            url = deal['origin_url']
            if not post_key(self.availability_site, url) or not deal['article_id'].startswith(prefix):
                record_observation(deal['article_id'], observation('unknown', 'invalid-origin-url'))
                continue
            meta = self.request_meta(1) if hasattr(self, 'request_meta') else {'cookiejar': 1}
            if self.availability_site == 'arca':
                meta['use_flaresolverr'] = True
            headers = getattr(self, 'request_headers', None) or getattr(self, 'headers', None)
            yield self.deal_request(url, {'article_id': deal['article_id'][len(prefix):]},
                                    meta=meta, headers=headers, status_only=True)
