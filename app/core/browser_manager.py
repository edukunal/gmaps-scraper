"""
Async Browser Pool — production hardened.
Features: auto-restart, stealth injection, proxy support, fingerprint rotation.
"""
import asyncio
from typing import Optional, Dict, List
from contextlib import asynccontextmanager

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Playwright,
)

from app.config import settings
from app.utils.user_agents import browser_fingerprint
from app.core.logger import get_logger

log = get_logger("pool")

_STEALTH_SCRIPT = """
    // Mask webdriver
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // Realistic plugins
    Object.defineProperty(navigator, 'plugins', { get: () => [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
        { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
    ]});

    // Languages
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

    // Window chrome
    window.chrome = { runtime: {}, app: {}, csi: () => {}, loadTimes: () => {} };

    // Permissions
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        origQuery(parameters)
    );

    // Realistic screen dimensions
    Object.defineProperty(screen, 'availWidth', { get: () => window.innerWidth });
    Object.defineProperty(screen, 'availHeight', { get: () => window.innerHeight });

    // Canvas fingerprint noise (subtle)
    const toDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(...args) {
        const ctx = this.getContext('2d');
        if (ctx) {
            const imageData = ctx.getImageData(0, 0, this.width, this.height);
            for (let i = 0; i < imageData.data.length; i += 100) {
                imageData.data[i] ^= Math.floor(Math.random() * 3);
            }
            ctx.putImageData(imageData, 0, 0);
        }
        return toDataURL.apply(this, args);
    };
"""

_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-accelerated-2d-canvas",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-infobars",
    "--disable-notifications",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
    "--disable-features=TranslateUI,VizDisplayCompositor",
    "--disable-ipc-flooding-protection",
    "--no-first-run",
    "--no-zygote",
    "--ignore-certificate-errors",
    "--mute-audio",
    "--hide-scrollbars",
    "--disable-web-security",
    "--allow-running-insecure-content",
    "--lang=en-US",
]


class _BrowserSlot:
    __slots__ = ("index", "browser", "in_use", "req_count", "err_count")

    def __init__(self, index: int):
        self.index = index
        self.browser: Optional[Browser] = None
        self.in_use = False
        self.req_count = 0
        self.err_count = 0

    @property
    def healthy(self) -> bool:
        return (
            self.browser is not None
            and self.browser.is_connected()
            and self.req_count < 60
            and self.err_count < 5
        )

    def tick(self, success: bool) -> None:
        self.req_count += 1
        if not success:
            self.err_count += 1


class BrowserPoolManager:
    def __init__(self):
        self._pw: Optional[Playwright] = None
        self._slots: List[_BrowserSlot] = []
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(settings.MAX_CONCURRENT_SCRAPES)
        self._ready = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            log.info("Starting browser pool", size=settings.BROWSER_POOL_SIZE)
            self._pw = await async_playwright().start()
            self._slots = [_BrowserSlot(i) for i in range(settings.BROWSER_POOL_SIZE)]

            results = await asyncio.gather(
                *[self._launch(s) for s in self._slots],
                return_exceptions=True,
            )
            active = sum(1 for r in results if r is not True and not isinstance(r, Exception))
            active = sum(1 for s in self._slots if s.browser and s.browser.is_connected())
            log.info("Pool ready", active=active)
            self._ready = True

    async def shutdown(self) -> None:
        log.info("Shutting down pool")
        for slot in self._slots:
            await self._close_slot(slot)
        if self._pw:
            await self._pw.stop()
        self._ready = False

    # ── Browser management ────────────────────────────────────────────────────

    async def _launch(self, slot: _BrowserSlot) -> None:
        proxy = None
        if settings.PROXY_URL:
            proxy = {"server": settings.PROXY_URL}
            if settings.PROXY_USERNAME:
                proxy["username"] = settings.PROXY_USERNAME
                proxy["password"] = settings.PROXY_PASSWORD or ""

        try:
            slot.browser = await self._pw.chromium.launch(
                headless=settings.BROWSER_HEADLESS,
                proxy=proxy,
                args=_CHROMIUM_ARGS,
                timeout=30_000,
            )
            slot.req_count = 0
            slot.err_count = 0
            log.debug("Browser launched", idx=slot.index)
        except Exception as e:
            log.error("Launch failed", idx=slot.index, error=str(e))
            slot.browser = None

    async def _close_slot(self, slot: _BrowserSlot) -> None:
        try:
            if slot.browser:
                await slot.browser.close()
        except Exception:
            pass
        slot.browser = None

    async def _restart(self, slot: _BrowserSlot) -> None:
        log.info("Restarting browser", idx=slot.index)
        await self._close_slot(slot)
        await self._launch(slot)

    # ── Acquire context ───────────────────────────────────────────────────────

    @asynccontextmanager
    async def acquire_context(self):
        async with self._sem:
            slot = await self._pick_slot()
            if slot is None:
                raise RuntimeError("Browser pool exhausted — all slots busy or unhealthy")

            fp = browser_fingerprint()
            ctx: Optional[BrowserContext] = None
            success = False
            try:
                ctx = await slot.browser.new_context(
                    user_agent=fp["user_agent"],
                    viewport=fp["viewport"],
                    locale=fp["locale"],
                    timezone_id=fp["timezone_id"],
                    color_scheme="light",
                    device_scale_factor=fp["device_scale_factor"],
                    java_script_enabled=True,
                    bypass_csp=True,
                    ignore_https_errors=True,
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                        "DNT": "1",
                    },
                )
                await ctx.add_init_script(_STEALTH_SCRIPT)
                success = True
                yield ctx
            except Exception as e:
                log.error("Context error", idx=slot.index, error=str(e))
                raise
            finally:
                slot.in_use = False
                slot.tick(success)
                if ctx:
                    try:
                        await ctx.close()
                    except Exception:
                        pass
                # Schedule async restart if unhealthy (don't block current yield)
                if not slot.healthy:
                    asyncio.create_task(self._restart(slot))

    async def _pick_slot(self) -> Optional[_BrowserSlot]:
        """Wait up to 30s for a free healthy slot."""
        for _ in range(100):
            for slot in self._slots:
                if not slot.in_use:
                    if not slot.healthy:
                        await self._restart(slot)
                    if slot.browser and slot.browser.is_connected():
                        slot.in_use = True
                        return slot
            await asyncio.sleep(0.3)
        return None

    # ── Status ────────────────────────────────────────────────────────────────

    async def pool_status(self) -> Dict:
        return {
            "pool_size": len(self._slots),
            "active": sum(1 for s in self._slots if s.browser and s.browser.is_connected()),
            "in_use": sum(1 for s in self._slots if s.in_use),
            "instances": [
                {
                    "index": s.index,
                    "connected": bool(s.browser and s.browser.is_connected()),
                    "in_use": s.in_use,
                    "req_count": s.req_count,
                    "err_count": s.err_count,
                    "healthy": s.healthy,
                }
                for s in self._slots
            ],
        }


browser_pool = BrowserPoolManager()
