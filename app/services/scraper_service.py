import asyncio, time
from typing import List, Dict, AsyncIterator, Tuple
from app.config import settings
from app.core.browser_manager import browser_pool
from app.core.metrics import metrics
from app.core.logger import get_logger
from app.scrapers.google_maps_scraper import GoogleMapsScraper
from app.models.schemas import BusinessLead, ScrapeRequest, ScrapeResponse
from app.utils.helpers import deduplicate_results, clean_text, clean_url

log = get_logger("service")

class ScraperService:
    async def run_scrape(self, req: ScrapeRequest) -> ScrapeResponse:
        start = time.time()
        errors: List[str] = []
        leads: List[BusinessLead] = []
        max_results = min(req.max_results, settings.HARD_MAX_RESULTS)
        metrics.active_scrapes += 1
        try:
            async with browser_pool.acquire_context() as ctx:
                scraper = GoogleMapsScraper(ctx)
                raw = await scraper.scrape(req.query, max_results, req.extract_details)
            raw = deduplicate_results(raw, ["name","address"])
            for item in raw:
                try:
                    leads.append(BusinessLead(**self._norm(item)))
                except Exception as e:
                    errors.append(f"parse:{e}")
        except Exception as e:
            errors.append(str(e))
            log.error("Scrape error", error=str(e))
        finally:
            metrics.active_scrapes -= 1
        elapsed = round(time.time()-start,2)
        metrics.record_request(bool(leads) or not errors, len(leads), elapsed)
        log.info("Done", query=req.query, leads=len(leads), s=elapsed)
        return ScrapeResponse(
            success=True, query=req.query, total_results=len(leads),
            execution_time=f"{elapsed}s", data=leads, errors=errors,
            meta={"max_requested":max_results,"dedup":True,"details":req.extract_details},
        )

    async def run_scrape_streaming(
        self, req: ScrapeRequest
    ) -> AsyncIterator[Tuple[BusinessLead, int]]:
        max_results = min(req.max_results, settings.HARD_MAX_RESULTS)
        metrics.active_scrapes += 1
        seen = set()
        try:
            async with browser_pool.acquire_context() as ctx:
                scraper = GoogleMapsScraper(ctx)
                async for raw, pct in scraper.scrape_streaming(req.query, max_results, req.extract_details):
                    try:
                        norm = self._norm(raw)
                        key = (norm.get("name",""), norm.get("address",""))
                        if key in seen:
                            continue
                        seen.add(key)
                        lead = BusinessLead(**norm)
                        yield lead, pct
                        metrics.total_leads_scraped += 1
                    except Exception as e:
                        log.warning("Parse error", error=str(e))
        except Exception as e:
            log.error("Stream error", error=str(e))
        finally:
            metrics.active_scrapes -= 1

    def _norm(self, raw: Dict) -> Dict:
        out: Dict = {}
        for f in ["name","category","description","address","city","state","postal_code","phone","email","maps_url","place_id"]:
            v = raw.get(f); out[f] = clean_text(str(v)) if v else None
        out["website"] = clean_url(raw.get("website"))
        if not out["maps_url"]: out["maps_url"] = raw.get("maps_url")
        for f in ("latitude","longitude","rating"):
            v = raw.get(f)
            try: out[f] = float(v) if v is not None else None
            except: out[f] = None
        v = raw.get("reviews_count")
        try: out["reviews_count"] = int(str(v).replace(",","").replace(".","")) if v else None
        except: out["reviews_count"] = None
        out["is_open_now"] = raw.get("is_open_now")
        for f in ("opening_hours","images","services","amenities"):
            lst = raw.get(f)
            out[f] = [clean_text(str(x)) for x in lst if x] if isinstance(lst,list) else None
            if out[f] is not None and not out[f]: out[f] = None
        out["social_links"] = raw.get("social_links") if isinstance(raw.get("social_links"),dict) else None
        return out

scraper_service = ScraperService()
