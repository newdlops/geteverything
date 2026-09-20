"""Keep complete product and image URLs instead of shortened link labels."""
from html import unescape
from urllib.parse import urljoin, urlsplit


def absolute_url(value, base):
    if not isinstance(value, str) or not value.strip():
        return ''
    try:
        url = urljoin(base, unescape(value).strip())
        parsed = urlsplit(url)
        return url if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username else ''
    except ValueError:
        return ''


def product_link(response, selector):
    for anchor in response.css(selector):
        href = anchor.attrib.get('href', '').strip()
        displayed = ''
        texts = anchor.xpath('.//text()').getall() + [anchor.xpath('string()').get('')]
        for text in texts:
            text = text.strip()
            if (text.startswith(('http://', 'https://', '//')) and '...' not in text
                    and '…' not in text and not any(char.isspace() for char in text)):
                displayed = absolute_url(text, response.url)
                if displayed:
                    break
        linked = absolute_url(href, response.url) if href and not href.startswith(('#', 'javascript:')) else ''
        community_host = urlsplit(response.url).hostname.removeprefix('www.')
        # Some communities wrap external links in an intermediate, cookie-dependent page.
        if (displayed and urlsplit(displayed).hostname.removeprefix('www.') != community_host
                and (not linked or urlsplit(linked).hostname.removeprefix('www.') == community_host)):
            return displayed
        if href and not href.startswith(('#', 'javascript:')):
            if linked:
                return linked
        if displayed:
            return displayed
    return ''
