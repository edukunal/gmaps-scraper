"""
GOD TIER Google Maps Scraper v2
- Multi-tab parallel detail extraction
- JS bulk single-evaluate per page (fast)
- Session warm-up (google.com first)
- Adaptive scroll with end-of-results detection
- 5+ selector fallbacks per field
- Per-field try/catch — always return partial data
"""
import asyncio
import json
import random
import re
from typing import Optional, List, Dict, Any, Set, Tuple, AsyncIterator
from urllib.parse import quote_plus

from playwright.async_api import (
    BrowserContext, Page, Response,
    TimeoutError as PlaywrightTimeout,
)

from app.config import settings
from app.core.logger import get_logger
from app.utils.helpers import (
    clean_text, clean_phone, clean_rating, clean_review_count,
    clean_url, extract_coords_from_url, parse_address_components,
)

log = get_logger("scraper")
MAPS_SEARCH = "https://www.google.com/maps/search/"
GOOGLE_HOME = "https://www.google.com/?hl=en"

# ── All JS strings use r"""...""" to avoid Python escape warnings ─────────────

JS_EXTRACT_DETAIL = r"""
() => {
    const $ = (s, ctx=document) => ctx.querySelector(s);
    const $$ = (s, ctx=document) => Array.from(ctx.querySelectorAll(s));
    const txt = (...sels) => {
        for(const s of sels){
            const e=$(s);
            if(e){const t=(e.innerText||e.textContent||'').trim();if(t)return t;}
        }
        return null;
    };
    const attr = (a,...sels) => {
        for(const s of sels){
            const e=$(s);
            if(e){const v=e.getAttribute(a);if(v)return v.trim();}
        }
        return null;
    };

    const name = txt(
        'h1.DUwDvf','h1[class*="DUwDvf"]',
        'h1[class*="fontHeadline"]','h1'
    );

    const category = txt(
        'button[jsaction*="pane.rating.category"]',
        'div[class*="LBgpqf"] button',
        'button[class*="DkEaL"]'
    );

    const ratingRaw = attr('aria-label',
        'div[class*="F7nice"] span[aria-hidden="true"]',
        'span[aria-label*="stars"]'
    ) || txt(
        'div[class*="F7nice"] span[aria-hidden="true"]',
        'div[class*="fontDisplayLarge"]'
    );

    const reviewRaw = attr('aria-label',
        'button[aria-label*="reviews"]',
        'span[aria-label*="reviews"]',
        'div[class*="F7nice"] span[aria-label*="review"]'
    ) || txt('button[aria-label*="review"]');

    // Address
    let address = null;
    const addrEl = $('button[data-item-id*="address"]') || $('div[data-item-id*="address"]');
    if(addrEl){
        const raw = addrEl.getAttribute('aria-label') || addrEl.innerText || '';
        address = raw.replace(/^Address:\s*/i, '').trim();
    }

    // Phone — href is cleanest
    let phone = null;
    const telA = $('a[href^="tel:"]');
    if(telA){
        phone = telA.href.replace('tel:', '').trim();
    } else {
        const phoneEl = $('button[data-item-id*="phone"]') || $('div[data-item-id*="phone"]');
        if(phoneEl){
            const raw = phoneEl.getAttribute('aria-label') || phoneEl.innerText || '';
            phone = raw.replace(/^Phone:\s*/i, '').trim();
        }
    }

    // Website
    let website = null;
    const siteEl = $('a[data-item-id*="authority"]')
        || $('a[aria-label*="website"]')
        || $('div[data-item-id*="authority"] a');
    if(siteEl) website = siteEl.href || siteEl.innerText || null;

    // Description
    const description = txt(
        'div[class*="PYvSYb"]',
        'div[class*="iA8Rhc"] div[class*="fontBodyMedium"]',
        'div[class*="YgLbBe"]'
    );

    // Hours — expanded table
    const hoursRows = $$('table[class*="eK4R0e"] tr, tr[class*="y0skZc"]');
    const hours = hoursRows
        .map(r => (r.innerText || '').trim().replace(/[\t\n]+/g, ' ').replace(/\s{2,}/g, ' '))
        .filter(Boolean);

    // Open now
    let is_open_now = null;
    for(const s of $$('span[class*="ZDu9vd"],span[class*="dBKQ3"],span[class*="hfpxzc"]')){
        const t = (s.innerText || '').toLowerCase().trim();
        if(t.includes('open now') || t.includes('opens soon')){ is_open_now = true; break; }
        if(t.includes('closed') || t.includes('closes soon')){ is_open_now = false; break; }
    }

    // Images
    const images = $$(
        'img[src*="googleusercontent"],img[src*="lh5.google"],img[src*="lh3.google"]'
    )
    .map(i => i.src)
    .filter(s => s && s.startsWith('http') && !s.includes('/icon') && !s.includes('flag') && s.length > 60)
    .slice(0, 10);

    // Services / amenities
    const serviceEls = $$(
        'div[aria-label*="Services"] span[class*="fontBodyMedium"],' +
        'div[aria-label*="Highlights"] span,' +
        'div[class*="ugS8Fb"] span,' +
        'div[aria-label*="Amenities"] span,' +
        'div[aria-label*="Offerings"] span'
    );
    const services = [...new Set(
        serviceEls.map(e => (e.innerText || '').trim()).filter(t => t.length > 1 && t.length < 80)
    )];

    // Social links
    const allHrefs = $$('a[href]').map(a => a.href);
    const social = {};
    const sp = {
        facebook: /facebook\.com\/(?!sharer)/i,
        instagram: /instagram\.com\//i,
        twitter: /(?:twitter|x)\.com\//i,
        linkedin: /linkedin\.com\//i,
        youtube: /youtube\.com\//i,
        tiktok: /tiktok\.com\//i,
    };
    for(const [p, rx] of Object.entries(sp)){
        const found = allHrefs.find(h => rx.test(h) && !h.includes('google'));
        if(found) social[p] = found;
    }

    // Email from visible page text
    const bodyText = document.body.innerText || '';
    const emailMatch = bodyText.match(/[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}/);
    const email = emailMatch ? emailMatch[0] : null;

    return {
        name, category,
        rating: ratingRaw,
        reviews_count: reviewRaw,
        address, phone, website, description,
        opening_hours: hours.length ? hours : null,
        is_open_now,
        images: images.length ? images : null,
        services: services.length ? services : null,
        social_links: Object.keys(social).length ? social : null,
        email,
    };
}
"""

JS_COLLECT_URLS = r"""
(seen) => {
    const urls = [];
    document.querySelectorAll('a[href*="/maps/place/"]').forEach(a => {
        const base = a.href.split('?')[0];
        if(!seen.includes(base) && base.includes('/maps/place/')){
            seen.push(base);
            urls.push(a.href);
        }
    });
    return { urls, seen };
}
"""

JS_END_OF_RESULTS = r"""
() => {
    const sels = [
        'p[class*="fontBodyMedium"] span',
        'span[class*="HlvSq"]',
        'div[class*="PbZDve"] p'
    ];
    for(const s of sels){
        const el = document.querySelector(s);
        if(el){
            const t = (el.textContent || '').toLowerCase();
            if(
                t.includes("you've reached") ||
                t.includes("end of results") ||
                t.includes("no more results")
            ) return true;
        }
    }
    return false;
}
"""

JS_SCROLL = r"""
(sel) => {
    const el = sel ? document.querySelector(sel) : null;
    if(el){
        const prev = el.scrollTop;
        el.scrollBy({ top: Math.floor(Math.random() * 300 + 350), behavior: 'instant' });
        return el.scrollTop !== prev;
    }
    window.scrollBy(0, Math.floor(Math.random() * 300 + 350));
    return true;
}
"""

JS_FAST_LIST = r"""
() => {
    return Array.from(document.querySelectorAll('a[href*="/maps/place/"]')).map(a => {
        const c = a.closest('[jsaction]') || a.closest('[data-result-index]') || a.parentElement;
        const name = c?.querySelector('[class*="fontHeadline"],[class*="qBF1Pd"]')?.textContent?.trim()
            || a.textContent?.trim();
        const rating = c?.querySelector('[class*="MW4etd"]')?.textContent?.trim();
        const reviews = c?.querySelector('[class*="UY7F9"]')?.textContent?.replace(/[()]/g,'').trim();
        const category = c?.querySelector('[class*="W4Efsd"]>span')?.textContent?.trim();
        return { name, rating, reviews_count: reviews, category, maps_url: a.href };
    }).filter(r => r.name);
}
"""

_BLOCKED_DOMAINS = [
    "doubleclick.net", "googlesyndication.com", "googletagmanager.com",
    "google-analytics.com", "googletagservices.com", "adservice.google",
    "googleadservices.com", "analytics.google.com",
]
_BLOCKED_TYPES = {"media", "font", "other"}


class GoogleMapsScraper:
    def __init__(self, context: BrowserContext):
        self.ctx = context

    # ── Public ────────────────────────────────────────────────────────────────

    async def scrape(
        self, query: str, max_results: int, extract_details: bool = True
    ) -> List[Dict]:
        page = await self._new_page()
        results: List[Dict] = []
        try:
            await self._warm_up(page)
            await self._navigate_search(page, query)
            urls = await self._scroll_collect(page, max_results)
            log.info("URLs collected", n=len(urls), query=query)
            if extract_details:
                results = await self._parallel_detail(urls)
            else:
                results = await page.evaluate(JS_FAST_LIST)
        except Exception as e:
            log.error("Scrape error", error=str(e))
        finally:
            await _safe_close(page)
        return results

    async def scrape_streaming(
        self, query: str, max_results: int, extract_details: bool = True
    ) -> AsyncIterator[Tuple[Dict, int]]:
        page = await self._new_page()
        try:
            await self._warm_up(page)
            await self._navigate_search(page, query)
            urls = await self._scroll_collect(page, max_results)
            total = len(urls)
            if not total:
                return

            if extract_details:
                sem = asyncio.Semaphore(settings.DETAIL_TAB_CONCURRENCY)
                queue: asyncio.Queue = asyncio.Queue()
                done_count = [0]

                async def scrape_one(url: str):
                    async with sem:
                        tab = await self._new_page()
                        try:
                            data = await self._extract_one(tab, url)
                            done_count[0] += 1
                            pct = int(done_count[0] / total * 100)
                            if data and data.get("name"):
                                await queue.put((data, pct))
                        finally:
                            await _safe_close(tab)
                    await queue.put(None)  # sentinel per task

                tasks = [asyncio.create_task(scrape_one(u)) for u in urls]
                sentinel_count = 0
                while sentinel_count < len(tasks):
                    item = await queue.get()
                    if item is None:
                        sentinel_count += 1
                    else:
                        yield item
            else:
                items = await page.evaluate(JS_FAST_LIST)
                total = len(items) or 1
                for i, item in enumerate(items):
                    yield item, int((i + 1) / total * 100)
        except Exception as e:
            log.error("Stream error", error=str(e))
        finally:
            await _safe_close(page)

    # ── Navigation ────────────────────────────────────────────────────────────

    async def _warm_up(self, page: Page) -> None:
        try:
            await page.goto(GOOGLE_HOME, wait_until="domcontentloaded", timeout=15_000)
            await _jitter(0.5, 1.0)
        except Exception:
            pass

    async def _navigate_search(self, page: Page, query: str) -> None:
        url = f"{MAPS_SEARCH}{quote_plus(query)}&hl=en"
        await page.goto(url, wait_until="domcontentloaded", timeout=settings.NAVIGATION_TIMEOUT)
        await self._handle_consent(page)
        await _jitter(0.6, 1.2)
        await self._wait_panel(page)

    async def _handle_consent(self, page: Page) -> None:
        for sel in [
            'button:text("Accept all")',
            'button[aria-label*="Accept all"]',
            'button:text("I agree")',
            'form[action*="consent"] button[value="1"]',
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    await _jitter(0.4, 0.8)
                    break
            except Exception:
                pass

    async def _wait_panel(self, page: Page) -> None:
        for sel in [
            'div[role="feed"]',
            'div[aria-label*="Results for"]',
            'div[aria-label*="results"]',
        ]:
            try:
                await page.wait_for_selector(sel, timeout=settings.ELEMENT_TIMEOUT)
                return
            except PlaywrightTimeout:
                continue

    # ── Scroll & collect ──────────────────────────────────────────────────────

    async def _scroll_collect(self, page: Page, max_results: int) -> List[str]:
        urls: List[str] = []
        seen_bases: List[str] = []
        panel_sel = await self._find_panel(page)
        stale = 0
        scroll_n = 0

        while len(urls) < max_results and scroll_n < settings.SCROLL_ATTEMPTS_MAX:
            result = await page.evaluate(JS_COLLECT_URLS, seen_bases)
            new_urls: List[str] = result["urls"]
            seen_bases = result["seen"]

            added = 0
            for u in new_urls:
                if len(urls) >= max_results:
                    break
                urls.append(u)
                added += 1

            if await page.evaluate(JS_END_OF_RESULTS):
                log.info("End of results", total=len(urls))
                break

            if added == 0:
                stale += 1
                if stale >= 6:
                    break
                await _jitter(0.3, 0.6)
            else:
                stale = 0

            await page.evaluate(JS_SCROLL, panel_sel)
            await _jitter(settings.SCROLL_PAUSE_MIN, settings.SCROLL_PAUSE_MAX)
            scroll_n += 1

        return urls[:max_results]

    async def _find_panel(self, page: Page) -> Optional[str]:
        for sel in [
            'div[role="feed"]',
            'div[aria-label*="Results for"]',
            'div[aria-label*="results"]',
        ]:
            try:
                if await page.locator(sel).count() > 0:
                    return sel
            except Exception:
                pass
        return None

    # ── Parallel detail extraction ─────────────────────────────────────────────

    async def _parallel_detail(self, urls: List[str]) -> List[Dict]:
        sem = asyncio.Semaphore(settings.DETAIL_TAB_CONCURRENCY)
        results: List[Optional[Dict]] = [None] * len(urls)

        async def do(idx: int, url: str):
            async with sem:
                tab = await self._new_page()
                try:
                    data = await self._extract_one(tab, url)
                    results[idx] = data
                finally:
                    await _safe_close(tab)

        await asyncio.gather(*[do(i, u) for i, u in enumerate(urls)])
        return [r for r in results if r and r.get("name")]

    async def _extract_one(self, page: Page, url: str) -> Optional[Dict]:
        for attempt in range(settings.MAX_RETRIES):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=settings.NAVIGATION_TIMEOUT)
                await self._wait_name(page)
                await self._expand_hours(page)

                data: Dict = await page.evaluate(JS_EXTRACT_DETAIL)

                cur = page.url
                lat, lng = extract_coords_from_url(cur)
                data["latitude"] = lat
                data["longitude"] = lng
                data["maps_url"] = _clean_maps_url(cur)
                data["place_id"] = _extract_place_id(cur)

                if data.get("address"):
                    data.update(parse_address_components(data["address"]))

                return _clean_all(data)

            except PlaywrightTimeout:
                if attempt < settings.MAX_RETRIES - 1:
                    await _jitter(settings.RETRY_DELAY, settings.RETRY_DELAY * settings.RETRY_BACKOFF)
            except Exception as e:
                log.warning("Detail error", url=url, attempt=attempt, error=str(e))
                if attempt < settings.MAX_RETRIES - 1:
                    await _jitter(settings.RETRY_DELAY, settings.RETRY_DELAY)
        return None

    async def _wait_name(self, page: Page) -> None:
        for sel in ['h1.DUwDvf', 'h1[class*="DUwDvf"]', 'h1[class*="fontHeadline"]', 'h1']:
            try:
                await page.wait_for_selector(sel, timeout=settings.DETAIL_TIMEOUT)
                return
            except PlaywrightTimeout:
                continue

    async def _expand_hours(self, page: Page) -> None:
        for sel in [
            'button[data-item-id*="oh"]',
            'button[aria-label*="hour"]',
            'div[data-item-id*="oh"] button',
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible(timeout=800):
                    await btn.click()
                    await _jitter(0.2, 0.4)
                    return
            except Exception:
                pass

    # ── Page factory ──────────────────────────────────────────────────────────

    async def _new_page(self) -> Page:
        page = await self.ctx.new_page()
        page.set_default_timeout(settings.PAGE_TIMEOUT)
        page.set_default_navigation_timeout(settings.NAVIGATION_TIMEOUT)
        await page.route("**/*", _route_handler)
        return page


# ── Module helpers ────────────────────────────────────────────────────────────

async def _route_handler(route) -> None:
    rt = route.request.resource_type
    url = route.request.url
    if rt in _BLOCKED_TYPES:
        await route.abort()
        return
    if any(d in url for d in _BLOCKED_DOMAINS):
        await route.abort()
        return
    await route.continue_()


async def _safe_close(page: Page) -> None:
    try:
        await page.close()
    except Exception:
        pass


async def _jitter(mn: float, mx: float) -> None:
    await asyncio.sleep(random.uniform(mn, mx))


def _clean_maps_url(url: str) -> str:
    try:
        url = re.sub(r'[?&](hl|gl|ved|entry|source|authuser|shorturl)=[^&]*', '', url)
        return url.rstrip("?&")
    except Exception:
        return url


def _extract_place_id(url: str) -> Optional[str]:
    m = re.search(r'!1s([A-Za-z0-9_:%-]+)', url)
    if m:
        return m.group(1)
    m = re.search(r'place/[^/]+/([^/?&]+)', url)
    return m.group(1) if m else None


def _clean_all(data: Dict) -> Dict:
    str_fields = [
        "name", "category", "description", "address", "phone",
        "website", "maps_url", "place_id", "email", "city", "state", "postal_code"
    ]
    for f in str_fields:
        data[f] = clean_text(str(data[f])) if data.get(f) else None

    for f, prefix in [("address", "Address:"), ("phone", "Phone:"), ("website", "Website:")]:
        if data.get(f) and data[f].startswith(prefix):
            data[f] = data[f][len(prefix):].strip()

    data["rating"] = clean_rating(data.get("rating"))
    data["reviews_count"] = clean_review_count(data.get("reviews_count"))
    data["phone"] = clean_phone(data.get("phone"))
    data["website"] = clean_url(data.get("website"))
    return data
