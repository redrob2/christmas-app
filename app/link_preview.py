"""Read a product link and suggest wishlist fields (name, price, photo, color, size).

Order of attempts:
  1. Fetch the page ourselves and read the product data stores publish for
     Google / link previews (JSON-LD "Product", Open Graph tags, <title>).
  2. If the name or price is still missing, ask Gemini to read the page text.
  3. If the store blocked us (bot check, 403...), ask Gemini to fetch the page
     itself (its "URL context" tool) - Google's servers are blocked less often.

Everything here is a *suggestion*; the user reviews it before saving.

Safety: the server fetches URLs that users type, so every connection is checked
at connect time (including after redirects) and refused unless the address is a
public internet address - never 192.168.x, 10.x, localhost, link-local, etc.
That stops the feature being used to reach the Unraid UI or other home devices.
"""
import ipaddress
import json
import re
import socket
from html import unescape
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urljoin, urlparse

import requests
from flask import current_app
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError
from urllib3.util import connection as urllib3_connection

from app.utils import parse_money

PAGE_LIMIT = 2 * 1024 * 1024      # read at most 2 MB of a page
IMAGE_LIMIT = 8 * 1024 * 1024     # and 8 MB of a picture
TIMEOUT = (4, 8)                  # connect, read (seconds)
BROWSER_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/130.0 Safari/537.36'),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}
BLOCK_MARKERS = ('robot check', 'captcha', 'are you a human', 'robot or human', 'access denied',
                 'verify you are human', 'pardon our interruption', 'press & hold', 'unusual traffic',
                 'just a moment', 'attention required')


class LinkError(Exception):
    """Shown to the user as-is"""


# ---------------------------------------------------------------------------
# Safe fetching
# ---------------------------------------------------------------------------

def _is_public(ip):
    ip = ipaddress.ip_address(ip)
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _public_addresses(host, port):
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise LinkError("That website couldn't be found - check the link.")
    addresses = [info[4][0] for info in infos]
    if not addresses or not all(_is_public(a) for a in addresses):
        raise LinkError("That link points to a private or local address, so it can't be read.")
    return addresses


class _SafeConnectionMixin:
    """Resolve the host ourselves and only connect to public IPs. Runs for every
    connection, so redirects to a private address are refused too."""

    def _new_conn(self):
        try:
            addresses = _public_addresses(self._dns_host, self.port)
        except LinkError as e:
            raise NewConnectionError(self, str(e))
        last_error = None
        for address in addresses:
            try:
                return urllib3_connection.create_connection(
                    (address, self.port), self.timeout,
                    source_address=self.source_address, socket_options=self.socket_options)
            except OSError as e:
                last_error = e
        raise NewConnectionError(self, f"Could not connect: {last_error}")


class _SafeHTTPConnection(_SafeConnectionMixin, HTTPConnection):
    pass


class _SafeHTTPSConnection(_SafeConnectionMixin, HTTPSConnection):
    pass


class _SafeHTTPPool(HTTPConnectionPool):
    ConnectionCls = _SafeHTTPConnection


class _SafeHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _SafeHTTPSConnection


class _SafeAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {'http': _SafeHTTPPool, 'https': _SafeHTTPSPool}


def _session():
    session = requests.Session()
    session.trust_env = False          # ignore any proxy settings in the environment
    session.max_redirects = 5
    adapter = _SafeAdapter()
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.headers.update(BROWSER_HEADERS)
    return session


def check_url(url):
    """Basic shape checks before any network traffic"""
    parsed = urlparse(url or '')
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise LinkError('Please paste a full web link starting with http:// or https://')
    if parsed.port not in (None, 80, 443):
        raise LinkError('Only normal web links (ports 80/443) can be read.')
    _public_addresses(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
    return parsed


def _fetch(url, limit, accept_prefixes):
    """GET with all the limits applied. Returns (final_url, content_type, bytes, status)."""
    check_url(url)
    try:
        with _session().get(url, timeout=TIMEOUT, stream=True) as r:
            ctype = (r.headers.get('Content-Type') or '').split(';')[0].strip().lower()
            if r.status_code < 400 and not ctype.startswith(accept_prefixes):
                raise LinkError("That link isn't a web page or picture.")
            body = bytearray()
            for chunk in r.iter_content(64 * 1024):
                body.extend(chunk)
                if len(body) > limit:
                    break
            # requests assumes Latin-1 when no charset is sent; real pages are nearly always UTF-8
            declared = 'charset=' in (r.headers.get('Content-Type') or '').lower()
            encoding = (r.encoding if declared else None) or 'utf-8'
            return r.url, ctype, bytes(body[:limit]), r.status_code, encoding
    except LinkError:
        raise
    except requests.exceptions.ConnectionError as e:
        if 'private or local address' in str(e):
            raise LinkError("That link points to a private or local address, so it can't be read.")
        raise LinkError("Couldn't connect to that website.")
    except requests.exceptions.Timeout:
        raise LinkError('That website took too long to answer.')
    except requests.exceptions.TooManyRedirects:
        raise LinkError('That link redirects too many times.')
    except requests.exceptions.RequestException:
        raise LinkError("Couldn't read that link.")


def download_image(url):
    """Fetch a picture from the web for an item. Returns (bytes, ext) or raises LinkError."""
    from PIL import Image
    _, _, data, status, _ = _fetch(url, IMAGE_LIMIT, ('image/',))
    if status >= 400 or not data:
        raise LinkError("Couldn't download the picture from that link.")
    try:
        with Image.open(BytesIO(data)) as img:
            fmt = (img.format or '').lower()
            img.verify()
    except Exception:
        raise LinkError("The picture from that link isn't a valid image.")
    ext = {'jpeg': 'jpg', 'png': 'png', 'gif': 'gif', 'webp': 'webp'}.get(fmt)
    if not ext:
        raise LinkError("The picture from that link isn't a supported image type.")
    return data, ext


# ---------------------------------------------------------------------------
# Parsing product data out of the HTML
# ---------------------------------------------------------------------------

class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.json_ld = []
        self.title = ''
        self.canonical = None
        self.text = []
        self.images = []          # (score, url) candidates from <img> tags
        self._in = None
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or '') for k, v in attrs}
        if tag == 'meta':
            key = (a.get('property') or a.get('name') or a.get('itemprop') or '').lower()
            if key and a.get('content') and key not in self.meta:
                self.meta[key] = a['content'].strip()
        elif tag == 'link' and 'canonical' in a.get('rel', '').lower() and a.get('href'):
            self.canonical = a['href']
        elif tag == 'link' and a.get('rel', '').lower() == 'image_src' and a.get('href'):
            self.images.append((90, a['href']))
        elif tag == 'img':
            self._add_image(a)
        elif tag == 'script' and 'ld+json' in a.get('type', '').lower():
            self._in, self._buffer = 'ld', []
        elif tag in ('script', 'style', 'noscript', 'svg'):
            self._in = 'skip'
        elif tag == 'title' and not self.title:
            self._in, self._buffer = 'title', []

    def _add_image(self, a):
        """Score <img> tags so the main product photo wins over logos and icons"""
        # Amazon: main photo carries a hi-res link and a {url: [w, h]} map of sizes
        if a.get('data-old-hires'):
            self.images.append((100, a['data-old-hires']))
        if a.get('data-a-dynamic-image'):
            try:
                sizes = json.loads(a['data-a-dynamic-image'])
                best = max(sizes.items(), key=lambda kv: kv[1][0] * kv[1][1])[0]
                self.images.append((95, best))
            except (ValueError, TypeError, IndexError):
                pass
        src = a.get('data-src') or a.get('src') or ''
        if not src or src.startswith('data:') or len(self.images) > 60:
            return
        hint = ' '.join([a.get('id', ''), a.get('class', ''), a.get('itemprop', ''), a.get('alt', '')]).lower()
        if any(bad in hint or bad in src.lower() for bad in ('logo', 'icon', 'sprite', 'avatar', 'badge', 'pixel', 'tracking')):
            return
        score = 10
        if a.get('itemprop') == 'image' or any(k in hint for k in ('landingimage', 'product', 'main', 'hero', 'primary', 'gallery')):
            score = 60
        try:
            if int(a.get('width') or 0) >= 300:
                score += 10
        except ValueError:
            pass
        self.images.append((score, src))

    def handle_endtag(self, tag):
        if self._in == 'ld' and tag == 'script':
            self.json_ld.append(''.join(self._buffer))
            self._in = None
        elif self._in == 'title' and tag == 'title':
            self.title = ' '.join(''.join(self._buffer).split())
            self._in = None
        elif self._in == 'skip' and tag in ('script', 'style', 'noscript', 'svg'):
            self._in = None

    def handle_data(self, data):
        if self._in in ('ld', 'title'):
            self._buffer.append(data)
        elif self._in is None:
            text = data.strip()
            if text:
                self.text.append(text)


def _walk_json_ld(node):
    """Yield every dict in a JSON-LD blob (handles @graph, lists, nesting)"""
    if isinstance(node, list):
        for item in node:
            yield from _walk_json_ld(item)
    elif isinstance(node, dict):
        yield node
        for key in ('@graph', 'mainEntity', 'itemListElement'):
            if key in node:
                yield from _walk_json_ld(node[key])


def _is_product(node):
    types = node.get('@type', [])
    types = types if isinstance(types, list) else [types]
    return any(str(t).lower() in ('product', 'productgroup') for t in types)


def _first(value):
    while isinstance(value, list):
        value = value[0] if value else None
    return value


def _image_from(value):
    value = _first(value)
    if isinstance(value, dict):
        value = value.get('url') or value.get('contentUrl')
    return value if isinstance(value, str) else None


def _price_from_offers(offers):
    for offer in (offers if isinstance(offers, list) else [offers]):
        if not isinstance(offer, dict):
            continue
        for key in ('price', 'lowPrice', 'highPrice'):
            price = parse_money(str(offer.get(key) or ''))
            if price:
                return price
        spec = offer.get('priceSpecification')
        if spec:
            price = _price_from_offers(spec)
            if price:
                return price
        if offer.get('offers'):
            price = _price_from_offers(offer['offers'])
            if price:
                return price
    return None


def _clean_name(name, site):
    """'Cozy Throw Blanket - Threshold™ : Target' -> 'Cozy Throw Blanket - Threshold™'"""
    if not name:
        return None
    name = ' '.join(unescape(name).split())
    # "Amazon.com: Apple AirPods..." -> "Apple AirPods..."
    prefix, colon, rest = name.partition(': ')
    if colon and site and site.split('.')[0] in prefix.lower().replace(' ', '') and len(rest) > 3:
        name = rest
    for sep in (' | ', ' : ', ' – ', ' - '):
        if sep in name:
            head, _, tail = name.rpartition(sep)
            if site and site.split('.')[0] in tail.lower().replace(' ', '') and len(head) > 3:
                name = head
    # Marketplace titles run on ("... Laptop with M2 Pro chip with 12-core CPU and ...");
    # keep the part before the first natural break so it reads like a list entry
    if len(name) > 80:
        cuts = [name.find(sep) for sep in (': ', ' | ', ', ', ' - ', ' with ', ' (') if name.find(sep) >= 15]
        if cuts:
            name = name[:min(cuts)].rstrip(' ,:-')
    return name[:200] or None


AMAZON_PRICE_BLOCKS = ('corePriceDisplay_desktop_feature_div', 'corePrice_feature_div', 'corePrice_desktop',
                       'apex_desktop', 'priceToPay')


def _amazon_price(html):
    """Amazon shows the price in its own markup: <span class="a-offscreen">$198.64</span>
    inside the 'core price' block (the first a-offscreen elsewhere can be another product)"""
    for block in AMAZON_PRICE_BLOCKS:
        start = html.find(block)
        if start == -1:
            continue
        window = html[start:start + 8000]
        # "$198.64" in a screen-reader span (class a-offscreen or aok-offscreen)...
        match = re.search(r'class="a?o?k?-?offscreen">\s*\$\s*([\d,]+(?:\.\d{2})?)\s*<', window)
        if match:
            return parse_money(match.group(1))
        # ...or the visible dollars + cents pieces
        match = re.search(r'a-price-whole">([\d,]+)<span class="a-price-decimal">\.</span></span>'
                          r'<span class="a-price-fraction">(\d{2})<', window)
        if match:
            return parse_money(f'{match.group(1)}.{match.group(2)}')
    return None


def parse_product(html, page_url):
    parser = _PageParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    site = (urlparse(page_url).hostname or '').removeprefix('www.')
    fields = {}

    for blob in parser.json_ld:
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        for node in _walk_json_ld(data):
            if not _is_product(node):
                continue
            fields.setdefault('name', node.get('name'))
            fields.setdefault('image_url', _image_from(node.get('image')))
            fields.setdefault('price', _price_from_offers(node.get('offers')))
            if isinstance(node.get('color'), str):
                fields.setdefault('color', node['color'])
            if isinstance(node.get('size'), str):
                fields.setdefault('size', node['size'])
        if fields.get('name'):
            break

    meta = parser.meta
    if not fields.get('name'):
        fields['name'] = meta.get('og:title') or meta.get('twitter:title') or parser.title
    if not fields.get('image_url'):
        fields['image_url'] = meta.get('og:image') or meta.get('og:image:secure_url') or meta.get('twitter:image')
    if not fields.get('image_url'):
        best = max(parser.images, key=lambda c: c[0], default=None)
        if best and best[0] >= 60:          # only confident picks (product/main photo)
            fields['image_url'] = best[1]
    if not fields.get('price'):
        fields['price'] = parse_money(meta.get('product:price:amount') or meta.get('og:price:amount')
                                      or meta.get('price') or '')
    if not fields.get('price'):
        fields['price'] = _amazon_price(html)

    fields['name'] = _clean_name(fields.get('name'), site)
    if fields.get('image_url'):
        fields['image_url'] = urljoin(page_url, unescape(fields['image_url']))
        if urlparse(fields['image_url']).scheme not in ('http', 'https'):
            fields['image_url'] = None
    canonical = parser.canonical or meta.get('og:url')
    if canonical:
        canonical = urljoin(page_url, canonical)
        if urlparse(canonical).scheme in ('http', 'https'):
            fields['canonical_url'] = canonical

    title = (parser.title or '').lower()
    blocked = any(marker in title for marker in BLOCK_MARKERS)
    text = ' '.join(parser.text)[:15000]
    # likely product photos, best first, for the AI fallback to choose from
    seen, candidates = set(), []
    for _, src in sorted(parser.images, key=lambda c: -c[0]):
        src = urljoin(page_url, src)
        if src not in seen and urlparse(src).scheme in ('http', 'https'):
            seen.add(src)
            candidates.append(src)
    fields = {k: v for k, v in fields.items() if v}
    fields['_image_candidates'] = candidates[:8]
    return fields, blocked, text


# ---------------------------------------------------------------------------
# Gemini fallbacks
# ---------------------------------------------------------------------------

AI_INSTRUCTIONS = (
    'You extract product details for a family gift wishlist. Reply with ONLY a JSON object with these keys: '
    '"name" (short, clear product name a person would write on a list - drop store names, SKUs and '
    'marketing filler; keep the brand), "price" (current selling price as a plain number, not a crossed-out '
    '"was" price; null if unsure), "color" and "size" (only if the link or page clearly selects one, else null), '
    '"image_url" (main product photo URL if present, else null). Never guess - use null when unsure.')


_last_ai_error = {'status': None}


def _gemini(payload, timeout=25):
    """POST to Gemini; returns the JSON or None (reason kept in _last_ai_error)"""
    _last_ai_error['status'] = None
    key = current_app.config.get('GEMINI_API_KEY')
    if not key:
        _last_ai_error['status'] = 'no-key'
        return None
    model = current_app.config['GEMINI_TEXT_MODEL']
    try:
        r = requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
                          headers={'x-goog-api-key': key, 'Content-Type': 'application/json'},
                          json=payload, timeout=timeout)
        if r.status_code != 200:
            _last_ai_error['status'] = r.status_code
            print(f"[link-preview] Gemini HTTP {r.status_code}: {r.text[:300]}", flush=True)
            return None
        return r.json()
    except requests.exceptions.RequestException as e:
        _last_ai_error['status'] = 'network'
        print(f"[link-preview] Gemini error: {e}", flush=True)
        return None


def ai_unavailable_message():
    status = _last_ai_error['status']
    if status == 'no-key':
        return 'Reading pictures needs a Gemini API key (GEMINI_API_KEY in .env).'
    if status in (402, 429):
        return 'The AI service is out of credit or busy right now (check the Gemini account).'
    return "The AI service couldn't be reached right now."


def _json_from_response(result):
    try:
        parts = result['candidates'][0]['content']['parts']
        text = ''.join(p.get('text', '') for p in parts)
    except (KeyError, IndexError, TypeError):
        return {}
    match = re.search(r'\{.*\}', text, re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return {}
    out = {}
    if isinstance(data.get('name'), str) and data['name'].strip():
        out['name'] = data['name'].strip()[:200]
    price = parse_money(str(data.get('price') or ''))
    if price:
        out['price'] = price
    for key in ('color', 'size'):
        if isinstance(data.get(key), str) and data[key].strip() and data[key].lower() != 'null':
            out[key] = data[key].strip()[:50]
    image = data.get('image_url')
    if isinstance(image, str) and urlparse(image).scheme in ('http', 'https'):
        out['image_url'] = image
    return out


def ai_from_text(url, page_text, image_candidates=()):
    """Gemini reads text we already downloaded (plus the page's likely product photos,
    since pictures aren't part of the text)"""
    images = '\n'.join(image_candidates) or 'none found'
    result = _gemini({
        'contents': [{'parts': [{'text': (
            f'{AI_INSTRUCTIONS}\nFor "image_url" pick the main product photo from the candidate image URLs '
            f'below (copy it exactly), or null if none is the product.\n\nProduct link: {url}\n\n'
            f'Candidate image URLs:\n{images}\n\nPage text:\n{page_text}')}]}],
        'generationConfig': {'temperature': 0, 'responseMimeType': 'application/json'},
    })
    return _json_from_response(result) if result else {}


def ai_fetch_or_search(url):
    """For pages that block us: Gemini fetches the page itself (URL context) and/or
    looks the product up on Google (search grounding). Answers are only trusted when
    Google reports it actually read the page or actually found search results -
    otherwise the model could just be guessing from the words in the URL.
    Returns (fields, method) where method is 'ai-fetch' or 'ai-search'."""
    result = _gemini({
        'contents': [{'parts': [{'text': (
            f'{AI_INSTRUCTIONS}\n\nRead this product page: {url}\n'
            'If the page cannot be opened, use Google Search to find this exact product '
            '(same store item / model) and use the listing details you find.')}]}],
        'tools': [{'urlContext': {}}, {'googleSearch': {}}],
        'generationConfig': {'temperature': 0},
    }, timeout=35)
    if not result:
        return {}, None
    try:
        candidate = result['candidates'][0]
    except (KeyError, IndexError, TypeError):
        return {}, None
    statuses = [m.get('urlRetrievalStatus')
                for m in (candidate.get('urlContextMetadata') or {}).get('urlMetadata', [])]
    sources = [c.get('web', {}).get('uri')
               for c in (candidate.get('groundingMetadata') or {}).get('groundingChunks', [])]
    if 'URL_RETRIEVAL_STATUS_SUCCESS' in statuses:
        method = 'ai-fetch'
    elif any(sources):
        method = 'ai-search'
    else:
        print(f"[link-preview] Gemini found nothing reliable for {url}: {statuses}", flush=True)
        return {}, None
    fields = _json_from_response(result)
    if method == 'ai-search':
        fields.pop('image_url', None)   # a search result's picture may be a different item
    return fields, method


SCREENSHOT_PROMPT = (
    'This is a screenshot or photo someone wants to add to a family gift wishlist. '
    'Reply with ONLY a JSON object: "is_product" (true if a specific product is shown), '
    '"name" (short clear product name with brand, no store name or filler), '
    '"price" (current selling price as a number if visible, not a crossed-out price; else null), '
    '"color" and "size" (only if clearly selected or shown, else null), '
    '"product_box" ([ymin, xmin, ymax, xmax] of the main product photo, scaled 0-1000; '
    'null if there is no separate product photo). Never guess - use null when unsure.')


def read_screenshot(data):
    """Read a product screenshot (or photo): suggest name/price/color/size and crop the
    product picture out of it. Returns {'fields': {...}, 'cropped': jpeg bytes or None}."""
    import base64
    from PIL import Image, ImageOps

    try:
        img = Image.open(BytesIO(data))
        img = ImageOps.exif_transpose(img).convert('RGB')
    except Exception:
        raise LinkError("That file isn't a picture we can read.")

    small = img.copy()
    small.thumbnail((1600, 1600))
    buf = BytesIO()
    small.save(buf, 'JPEG', quality=85)
    result = _gemini({
        'contents': [{'parts': [
            {'text': SCREENSHOT_PROMPT},
            {'inline_data': {'mime_type': 'image/jpeg', 'data': base64.b64encode(buf.getvalue()).decode()}},
        ]}],
        'generationConfig': {'temperature': 0, 'responseMimeType': 'application/json'},
    }, timeout=40)
    if not result:
        raise LinkError(ai_unavailable_message())

    try:
        text = ''.join(p.get('text', '') for p in result['candidates'][0]['content']['parts'])
        raw = json.loads(re.search(r'\{.*\}', text, re.S).group(0))
    except Exception:
        raise LinkError("Couldn't make sense of that picture - please fill it in below.")
    if raw.get('is_product') is False:
        raise LinkError("Didn't spot a product in that picture - please fill it in below.")
    fields = _json_from_response(result)
    fields.pop('image_url', None)

    cropped = None
    box = raw.get('product_box')
    if isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
        ymin, xmin, ymax, xmax = [max(0, min(1000, v)) / 1000 for v in box]
        width, height = img.size
        area = (xmax - xmin) * (ymax - ymin)
        if xmax > xmin and ymax > ymin and 0.03 <= area <= 0.92:   # skip tiny or whole-screen boxes
            pad_x, pad_y = (xmax - xmin) * 0.04, (ymax - ymin) * 0.04
            crop = img.crop((int(max(0, xmin - pad_x) * width), int(max(0, ymin - pad_y) * height),
                             int(min(1, xmax + pad_x) * width), int(min(1, ymax + pad_y) * height)))
            crop.thumbnail((1200, 1200))
            out = BytesIO()
            crop.save(out, 'JPEG', quality=88)
            cropped = out.getvalue()

    if not fields and not cropped:
        raise LinkError("Couldn't read any details from that picture - please fill it in below.")
    return {'fields': fields, 'cropped': cropped}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def preview(url):
    """Returns {'fields': {...}, 'method': 'store'|'ai'|'store+ai'|'ai-fetch'|'ai-search', 'site': ...}.
    Raises LinkError with a friendly message when nothing could be read."""
    parsed = check_url(url)
    site = (parsed.hostname or '').removeprefix('www.')
    fields, blocked, text, method = {}, False, '', 'store'

    try:
        final_url, ctype, body, status, encoding = _fetch(url, PAGE_LIMIT, ('text/html', 'application/xhtml'))
        if status in (401, 403, 405, 429, 503):
            blocked = True
        elif status >= 400:
            raise LinkError("That page doesn't seem to exist (the store returned an error).")
        else:
            fields, blocked, text = parse_product(body.decode(encoding, errors='replace'), final_url)
    except LinkError as e:
        # real answers about the link itself go straight back to the person
        if any(text in str(e) for text in ('private or local', 'full web link', "isn't a web page",
                                            "doesn't seem to exist", "couldn't be found")):
            raise
        blocked = True

    candidates = fields.pop('_image_candidates', [])
    if not blocked and (not fields.get('name') or not fields.get('price') or not fields.get('image_url')):
        ai = ai_from_text(url, text, candidates) if text else {}
        # only accept a picture the page really contains
        if ai.get('image_url') and ai['image_url'] not in candidates:
            ai.pop('image_url')
        if ai:
            method = 'ai' if not fields else 'store+ai'
            for key, value in ai.items():
                fields.setdefault(key, value)

    # Blocked, or the page had nothing useful: let Google read it or search for it
    if blocked or not (fields.get('name') or fields.get('price')):
        if blocked:
            fields = {}
        ai, ai_method = ai_fetch_or_search(url)
        if ai:
            fields, method = ai, ai_method

    if not fields.get('name') and not fields.get('price'):
        if blocked:
            raise LinkError(f"{site} didn't let us read that page - please fill it in below.")
        raise LinkError("Couldn't find product details on that page - please fill it in below.")
    return {'fields': fields, 'method': method, 'site': site}


def register_cli(app):
    import click

    @app.cli.command('check-link')
    @click.argument('url')
    def check_link_command(url):
        """Try the link reader on a URL from this server (for troubleshooting)."""
        try:
            result = preview(url)
        except LinkError as e:
            click.echo(f"Could not read it: {e}")
            return
        click.echo(f"Read {result['site']} using: {result['method']}")
        for key, value in result['fields'].items():
            click.echo(f"  {key:14} {value}")
