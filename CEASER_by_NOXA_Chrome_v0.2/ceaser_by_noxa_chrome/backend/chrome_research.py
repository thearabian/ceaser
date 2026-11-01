"""Isolated Playwright/Chrome research transport for CEASER.

The search engine is a web page, NOT an API. Result parsing is necessarily
best-effort and may change when Google/Bing changes their markup. Browser
access is restricted to public HTTPS URLs and no login state is reused.
"""
from __future__ import annotations

import ipaddress
import os
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote_plus, urlparse

from playwright.async_api import async_playwright, Error as PlaywrightError

SEARCH_ENGINES = {'google', 'bing'}
ALLOWED_CHANNELS = {'chrome', 'chromium'}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_https(url: str) -> bool:
    """Cheap URL safety filter; prototype defense, not DNS-rebinding protection."""
    if not isinstance(url, str) or len(url) > 2048:
        return False
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or '').strip().rstrip('.').lower()
        port = parsed.port
        if parsed.scheme != 'https' or not host or port not in (None, 443):
            return False
        if parsed.username or parsed.password or host in {'localhost', 'localhost.localdomain'}:
            return False
        if host.endswith(('.local', '.localhost', '.internal', '.test', '.invalid')) or '.' not in host:
            return False
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return True
        return ip.is_global
    except (ValueError, TypeError):
        return False


def search_url(query: str, engine: str) -> str:
    if engine not in SEARCH_ENGINES:
        raise ValueError('CEASER_SEARCH_ENGINE must be google or bing')
    q = quote_plus(query)
    if engine == 'google':
        return f'https://www.google.com/search?q={q}&num=10&hl=en'
    return f'https://www.bing.com/search?q={q}&count=10'


def normalize_search_link(url: str) -> str | None:
    if not isinstance(url, str):
        return None
    p = urlparse(url)
    host = (p.hostname or '').lower()
    if host == 'www.google.com' and p.path == '/url':
        # Google sometimes presents a redirect wrapper rather than the source URL.
        url = (parse_qs(p.query).get('q') or [None])[0]
    if not url or not public_https(url):
        return None
    host = (urlparse(url).hostname or '').lower()
    if host in {'www.google.com', 'google.com', 'www.bing.com', 'bing.com'}:
        return None
    return url.split('#', 1)[0]


# Run on a loaded public search-results page; no external scripts required.
EXTRACT_SEARCH_RESULTS = r"""
(engine) => {
  const output = [];
  const seen = new Set();
  if (engine === 'bing') {
    for (const card of document.querySelectorAll('li.b_algo')) {
      const a = card.querySelector('h2 a[href]');
      if (!a) continue;
      const title = (a.innerText || a.textContent || '').trim();
      const snippet = (card.querySelector('.b_caption p')?.innerText ||
                       card.querySelector('.b_caption')?.innerText || '').trim();
      if (title && !seen.has(a.href)) {
        seen.add(a.href);
        output.push({title, url:a.href, snippet});
      }
    }
  } else {
    // Google changes these containers periodically. h3 inside a result link
    // is a better fallback than relying exclusively on a CSS class name.
    for (const h3 of document.querySelectorAll('main h3, #search h3, h3')) {
      const a = h3.closest('a[href]');
      if (!a) continue;
      const title = (h3.innerText || h3.textContent || '').trim();
      const card = h3.closest('div.MjjYud, div.g, div[data-hveid]') || a.parentElement?.parentElement?.parentElement;
      const text = (card?.querySelector('.VwiC3b, .yXK7lf, [data-sncf]')?.innerText ||
                    card?.innerText || '').trim();
      const snippet = text.replace(title, '').trim().slice(0, 900);
      if (title && !seen.has(a.href)) {
        seen.add(a.href);
        output.push({title, url:a.href, snippet});
      }
    }
  }
  return output.slice(0, 20);
}
"""

EXTRACT_ARTICLE = r"""() => {
 const root = document.querySelector('article, main, [role="main"]') || document.body;
 const clone = root.cloneNode(true);
 for (const node of clone.querySelectorAll('script, style, noscript, iframe, svg, nav, footer, header, aside, form')) node.remove();
 return {title: document.title || '', content: (clone.innerText || clone.textContent || '').replace(/\s+/g, ' ').trim()};
}"""


class ChromeResearchBrowser:
    """One isolated browser per investigation; closes even if research fails."""

    def __init__(self, channel: str | None = None, engine: str | None = None):
        self.channel = (channel or os.getenv('CEASER_BROWSER_CHANNEL', 'chrome')).lower().strip()
        self.engine = (engine or os.getenv('CEASER_SEARCH_ENGINE', 'google')).lower().strip()
        if self.channel not in ALLOWED_CHANNELS:
            raise ValueError('Browser channel must be chrome or chromium')
        if self.engine not in SEARCH_ENGINES:
            raise ValueError('Search engine must be google or bing')
        self.playwright = None
        self.browser = None
        self.context = None

    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        try:
            self.browser = await self.playwright.chromium.launch(channel=self.channel, headless=True)
            self.context = await self.browser.new_context(
                accept_downloads=False, ignore_https_errors=False, service_workers='block',
                locale='en-US', viewport={'width': 1360, 'height': 900},
            )
            await self.context.route('**/*', self._route)
            return self
        except Exception as exc:
            await self.__aexit__(None, None, None)
            raise RuntimeError(
                f'Could not start {self.channel} browser. Install Google Chrome or run '
                '`python -m playwright install chromium` and set '
                'CEASER_BROWSER_CHANNEL=chromium. Original error: '
                + str(exc)[:280]
            ) from exc

    async def __aexit__(self, exc_type, exc, tb):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def _route(self, route):
        req = route.request
        if req.resource_type in {'image', 'media', 'font', 'websocket'} or not public_https(req.url):
            await route.abort()
            return
        await route.continue_()

    async def search(self, query: str, count: int = 6) -> list[dict]:
        page = await self.context.new_page()
        try:
            response = await page.goto(search_url(query, self.engine), timeout=25000, wait_until='domcontentloaded')
            if response and response.status >= 400:
                raise RuntimeError(f'{self.engine.title()} search returned HTTP {response.status}')
            await page.wait_for_timeout(950)
            body = (await page.locator('body').inner_text(timeout=6000))[:5000].lower()
            if any(text in body for text in ('unusual traffic from your computer',
                                             'verify you are human', 'complete the captcha',
                                             'please solve the captcha', 'before you continue to google')):
                raise RuntimeError(f'{self.engine.title()} blocked automated searching (CAPTCHA/consent). No bypass attempted; try CEASER_SEARCH_ENGINE=bing or an official search API.')
            raw = await page.evaluate(EXTRACT_SEARCH_RESULTS, self.engine)
            results = []
            seen = set()
            for item in raw:
                url = normalize_search_link(item.get('url', ''))
                if not url or url in seen:
                    continue
                seen.add(url)
                title = re.sub(r'\s+', ' ', str(item.get('title', '')))[:230]
                snippet = re.sub(r'\s+', ' ', str(item.get('snippet', '')))[:950]
                results.append({'title': title, 'url': url, 'snippet': snippet,
                                'retrieved_at': utc(), 'query': query,
                                'search_engine': self.engine, 'content': '',
                                'content_status': 'not_fetched'})
                if len(results) >= count:
                    break
            if not results:
                raise RuntimeError(f'No usable {self.engine.title()} search results were found. The page may have changed markup or imposed restrictions.')
            return results
        except PlaywrightError as exc:
            raise RuntimeError(f'Chrome browser search failed: {str(exc)[:250]}') from exc
        finally:
            await page.close()

    async def read_source(self, source: dict, char_limit: int = 4500) -> dict:
        """Fetch a bounded public-page excerpt, not a verified complete document."""
        source = dict(source)
        url = source.get('url', '')
        if not public_https(url):
            source['content_status'] = 'blocked_url'
            return source
        page = await self.context.new_page()
        try:
            response = await page.goto(url, timeout=15000, wait_until='domcontentloaded')
            if response and response.status >= 400:
                raise RuntimeError(f'HTTP {response.status}')
            if not public_https(page.url):
                raise RuntimeError('Redirected to disallowed URL')
            data = await page.evaluate(EXTRACT_ARTICLE)
            content = re.sub(r'\s+', ' ', str(data.get('content', ''))).strip()[:char_limit]
            if len(content) < 140:
                source['content_status'] = 'insufficient_text'
            else:
                source['content'] = content
                source['content_status'] = 'page_excerpt'
                source['fetched_at'] = utc()
                source['page_title'] = str(data.get('title', ''))[:230]
        except (PlaywrightError, RuntimeError) as exc:
            source['content_status'] = 'fetch_failed'
            source['fetch_error'] = str(exc)[:180]
        finally:
            await page.close()
        return source
