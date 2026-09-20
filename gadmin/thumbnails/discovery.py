"""Rank evidence from the linked product page, excluding unrelated UI images."""
from dataclasses import dataclass
from io import BytesIO
import json
import re
import warnings
from urllib.parse import urlsplit

from parsel import Selector
from PIL import Image, ImageOps, UnidentifiedImageError

from .fetch import ThumbnailError, normalize_url


BAD_IMAGE = re.compile(r"(?:^|[/_.\s-])(logo|icon|sprite|banner|avatar|profile|placeholder|loading|no[_-]?image|spacer|badge|tracking)(?:[/_.\s-]|$)", re.I)
PRODUCT_IMAGE = re.compile(r"product|goods|item[_-]?(?:image|photo)|gallery|main[_-]?(?:image|photo)|prd|대표|상품", re.I)
PROMOTION = re.compile(r'첫\s*(?:구매|주문)|신규\s*(?:회원|가입)|쿠폰\s*(?:받기|다운로드|발급)|coupon|voucher', re.I)
Image.MAX_IMAGE_PIXELS = 8_000_000


@dataclass(frozen=True)
class Candidate:
    url: str
    score: int
    evidence: str


def tokens(value):
    return set(re.findall(r"[\w가-힣]{2,}", str(value).casefold()))


def image_values(value, depth=0):
    if depth > 8:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for child in value[:12]:
            yield from image_values(child, depth + 1)
    elif isinstance(value, dict):
        for key in ("contentUrl", "url", "@id"):
            if isinstance(value.get(key), str):
                yield value[key]
                break


def products(value, depth=0):
    if depth > 8:
        return
    if isinstance(value, list):
        for child in value[:30]:
            yield from products(child, depth + 1)
    elif isinstance(value, dict):
        types = value.get("@type", [])
        types = [types] if isinstance(types, str) else types
        types = types if isinstance(types, list) else []
        if any(str(kind).rsplit("/", 1)[-1] in ("Product", "ProductGroup") for kind in types or []):
            yield value
        # Do not descend into related products, recommendations or ItemList.
        for key in ("@graph", "mainEntity", "mainEntityOfPage"):
            yield from products(value.get(key), depth + 1)


def discover_images(html, page_url, subject):
    selector = Selector(text=html, type="html")
    title = tokens(subject)
    found = {}

    def add(value, score, evidence, context=""):
        url = normalize_url(value, page_url)
        if not url or BAD_IMAGE.search(url + " " + context) or url.lower().split("?", 1)[0].endswith(".svg"):
            return
        candidate = Candidate(url, score, evidence)
        if url not in found or found[url].score < score:
            found[url] = candidate

    for script in selector.css('script[type="application/ld+json"]::text').getall()[:20]:
        try:
            data = json.loads(script)
        except (ValueError, RecursionError):
            continue
        for product in products(data):
            overlap = len(title & tokens(product.get("name", "")))
            for value in image_values(product.get("image")):
                add(value, 110 + min(30, overlap * 5), "product_json_ld")
    for key, score in (("og:image:secure_url", 95), ("og:image", 94), ("twitter:image", 85), ("twitter:image:src", 84)):
        for value in selector.css(f'meta[property="{key}"]::attr(content),meta[name="{key}"]::attr(content)').getall()[:6]:
            add(value, score, "product_metadata")
    for value in selector.css('[itemprop="image"]::attr(content),[itemprop="image"]::attr(src)').getall()[:12]:
        add(value, 100, "product_microdata")
    for node in selector.css("img")[:200]:
        if node.xpath("ancestor::header|ancestor::footer|ancestor::nav|ancestor::aside"):
            continue
        context = " ".join(node.attrib.get(key, "") for key in ("alt", "id", "class"))
        context += " " + " ".join(node.xpath("../@class|../@id|../../@class|../../@id").getall())
        overlap = len(title & tokens(node.attrib.get("alt", "")))
        if BAD_IMAGE.search(context) or not (PRODUCT_IMAGE.search(context) or overlap):
            continue
        try:
            width = int(node.attrib.get("width", "0"))
            height = int(node.attrib.get("height", "0"))
        except ValueError:
            width = height = 0
        if (0 < width < 80) or (0 < height < 80):
            continue
        score = 50 + min(20, overlap * 5) + (10 if width >= 300 and height >= 300 else 0)
        for attribute in ("data-original", "data-src", "data-lazy-src", "src"):
            add(node.attrib.get(attribute, ""), score, "product_body", context)
        for part in node.attrib.get("srcset", "").split(",")[-4:]:
            add(part.strip().split(" ", 1)[0], score + 1, "product_body", context)
    return sorted(found.values(), key=lambda candidate: -candidate.score)[:8]


POST_BODIES = {
    'coolenjoy.net': 'div.view-content.fr-view, #bo_v_con',
    'fmkorea.com': '.rd_body article, .rd_body .xe_content',
    'ppomppu.co.kr': '.board-contents',
    'arca.live': '.article-content',
    'eomisae.co.kr': '.rd_body .xe_content, .xe_content[class*="document_"]',
}


def discover_post_images(html, page_url, subject=''):
    host = (urlsplit(page_url).hostname or '').lower()
    body = next((value for domain, value in POST_BODIES.items()
                 if host == domain or host.endswith('.' + domain)), '')
    if not body:
        return []
    selector = Selector(text=html, type='html')
    found = {}
    promotions = set()
    title = tokens(subject) - {'오늘의집', '네이버', '쿠팡', '마켓', 'g마켓', '11번가', '무료배송', '핫딜'}
    # Community metadata often points to the site's logo; only use article body images.
    for node in selector.css(body).css('img')[:40]:
        if node.xpath('ancestor::a[contains(@class,"advert")]|ancestor::*[contains(@class,"comment")]'):
            continue
        context = ' '.join(node.attrib.get(key, '') for key in ('class', 'id', 'alt'))
        if BAD_IMAGE.search(context):
            continue
        block = node.xpath('ancestor::*[self::p or self::figure][1]')
        caption = ' '.join(block.xpath('.//text()').getall())[:1000]
        nearby = ' '.join(block.xpath('preceding-sibling::p[normalize-space()][1]//text()|following-sibling::p[normalize-space()][1]//text()').getall())[:1000]
        score = 50 + min(60, 15 * len(title & tokens(context + ' ' + caption + ' ' + nearby)))
        for attribute in ('data-original', 'data-src', 'data-lazy-src', 'src'):
            url = normalize_url(node.attrib.get(attribute, ''), page_url)
            if url and not BAD_IMAGE.search(url) and not url.lower().split('?', 1)[0].endswith('.svg'):
                # The same coupon can occur both before and after the actual product photos.
                if PROMOTION.search(context + ' ' + caption):
                    promotions.add(url)
                if url not in found or score > found[url].score:
                    found[url] = Candidate(url, score, 'community_body_v2')
    return sorted((item for url, item in found.items() if url not in promotions), key=lambda item: -item.score)[:8]


def encode_thumbnail(raw, *, fallback=False):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as original:
                if original.format not in ("JPEG", "PNG", "WEBP", "GIF", "AVIF"):
                    raise ThumbnailError("unsupported_image")
                width, height = original.size
                minimum = 48 if fallback else 96
                if min(width, height) < minimum or max(width, height) / min(width, height) > 4:
                    raise ThumbnailError("unsuitable_dimensions")
                if width * height > Image.MAX_IMAGE_PIXELS:
                    raise ThumbnailError("image_too_large")
                original.draft("RGB", (480, 480))
                original.thumbnail((480, 480), Image.Resampling.LANCZOS, reducing_gap=2)
                resized = ImageOps.exif_transpose(original)
                if resized.mode in ("RGBA", "LA") or (resized.mode == "P" and "transparency" in resized.info):
                    alpha = resized.convert("RGBA")
                    result = Image.new("RGB", resized.size, "white")
                    result.paste(alpha, mask=alpha.getchannel("A"))
                else:
                    result = resized.convert("RGB")
                output = BytesIO()
                result.save(output, format="JPEG", quality=80, optimize=False)
                if output.tell() > 160 * 1024:
                    raise ThumbnailError("thumbnail_too_large")
                return output.getvalue(), result.size
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ThumbnailError("invalid_image") from exc
