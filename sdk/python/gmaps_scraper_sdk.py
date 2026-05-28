"""
Google Maps Lead Scraper — Python SDK
======================================
Zero dependencies beyond `requests` (sync) or `httpx` (async).
Install: pip install requests httpx sseclient-py

Usage — sync:
    from gmaps_scraper_sdk import LeadScraperClient
    client = LeadScraperClient("http://localhost:8000")
    leads  = client.scrape("Dentists in Mathura", max_results=50)
    print(leads[0])

Usage — async job:
    job = client.create_job("Gyms in Delhi", max_results=200)
    results = client.wait_for_job(job["job_id"])

Usage — SSE live stream:
    for lead in client.stream_job("Restaurants in Agra", max_results=100):
        print(lead["name"], lead["phone"])
"""

import time
import json
import csv
import io
from typing import List, Dict, Optional, Iterator, Generator

try:
    import requests
except ImportError:
    raise ImportError("Run: pip install requests")


class LeadScraperError(Exception):
    pass


class LeadScraperClient:
    """
    Synchronous Python client for the Google Maps Lead Scraper API.

    Args:
        base_url: Your deployed API URL. e.g. "http://localhost:8000"
                  or "https://your-app.justrunmyapp.com"
        timeout:  Request timeout in seconds (default 600 for large scrapes)
        api_key:  Optional API key header (set on server via middleware if needed)
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: int = 600,
        api_key: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        if api_key:
            self.session.headers["X-API-Key"] = api_key

    # ── Core methods ──────────────────────────────────────────────────────────

    def scrape(
        self,
        query: str,
        max_results: int = 50,
        extract_details: bool = True,
    ) -> List[Dict]:
        """
        Synchronous scrape — blocks until all results are ready.

        Args:
            query:           e.g. "Dentists in Mathura"
            max_results:     How many leads to return (max 1000)
            extract_details: True = full data per place (slower but complete)
                             False = name/rating/url only (very fast)

        Returns:
            List of lead dicts with all fields.

        Example:
            client = LeadScraperClient("http://localhost:8000")
            leads = client.scrape("Dentists in Mathura", max_results=50)
            for lead in leads:
                print(f"{lead['name']} | {lead['phone']} | {lead['rating']}")
        """
        resp = self._post("/scrape", {
            "query": query,
            "max_results": max_results,
            "extract_details": extract_details,
        })
        return resp.get("data", [])

    def create_job(
        self,
        query: str,
        max_results: int = 100,
        extract_details: bool = True,
        webhook_url: Optional[str] = None,
    ) -> Dict:
        """
        Submit an async job. Returns immediately with a job_id.
        Use poll_job() or wait_for_job() to get results.

        Returns dict with keys: job_id, status, query, created_at
        """
        return self._post("/jobs", {
            "query": query,
            "max_results": max_results,
            "extract_details": extract_details,
            "webhook_url": webhook_url,
        })

    def poll_job(self, job_id: str) -> Dict:
        """Get current job status and progress (0-100%)."""
        return self._get(f"/jobs/{job_id}")

    def get_results(self, job_id: str) -> List[Dict]:
        """
        Get full results for a completed job.
        Raises LeadScraperError if job not yet done.
        """
        data = self._get(f"/jobs/{job_id}/results")
        return data.get("data", [])

    def wait_for_job(
        self,
        job_id: str,
        poll_interval: float = 3.0,
        verbose: bool = True,
    ) -> List[Dict]:
        """
        Poll until job is complete, then return results.

        Args:
            job_id:        From create_job()
            poll_interval: Seconds between status checks
            verbose:       Print progress to console

        Example:
            job = client.create_job("Gyms in Delhi", max_results=200)
            leads = client.wait_for_job(job["job_id"], verbose=True)
        """
        while True:
            status = self.poll_job(job_id)
            pct = status.get("progress", 0)
            st = status.get("status", "")
            count = status.get("results_so_far", 0)

            if verbose:
                print(f"  [{st.upper()}] {pct}% — {count} leads so far...")

            if st == "completed":
                if verbose:
                    print(f"  ✅ Done! {count} leads scraped in {status.get('execution_time')}")
                return self.get_results(job_id)

            if st == "failed":
                raise LeadScraperError(f"Job failed: {status.get('error')}")

            time.sleep(poll_interval)

    def stream_job(
        self,
        query: str,
        max_results: int = 100,
        extract_details: bool = True,
    ) -> Generator[Dict, None, None]:
        """
        Submit a job and yield each lead AS IT'S SCRAPED via SSE.
        No waiting — results come in real-time.

        Example:
            for lead in client.stream_job("Restaurants in Agra", max_results=100):
                print(f"Found: {lead['name']} — {lead['phone']}")
        """
        job = self.create_job(query, max_results, extract_details)
        job_id = job["job_id"]

        url = f"{self.base_url}/jobs/{job_id}/stream"
        with self.session.get(url, stream=True, timeout=self.timeout) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8") if isinstance(line, bytes) else line
                if line.startswith("data:"):
                    try:
                        event = json.loads(line[5:].strip())
                        etype = event.get("type")
                        if etype == "result":
                            yield event["lead"]
                        elif etype == "done":
                            break
                        elif etype == "error":
                            raise LeadScraperError(event.get("error", "Unknown error"))
                    except json.JSONDecodeError:
                        continue

    def list_jobs(self) -> List[Dict]:
        """List all jobs (queued, running, completed, failed)."""
        return self._get("/jobs")

    def delete_job(self, job_id: str) -> Dict:
        """Delete a job and its results."""
        resp = self.session.delete(f"{self.base_url}/jobs/{job_id}", timeout=30)
        resp.raise_for_status()
        return resp.json()

    def download_csv(self, job_id: str, filepath: str) -> str:
        """
        Download results as CSV file.

        Example:
            client.download_csv("abc-123", "dentists_mathura.csv")
        """
        resp = self.session.get(f"{self.base_url}/jobs/{job_id}/export?format=csv", timeout=60)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)
        print(f"✅ Saved to {filepath}")
        return filepath

    def download_excel(self, job_id: str, filepath: str) -> str:
        """
        Download results as Excel (.xlsx) file.

        Example:
            client.download_excel("abc-123", "dentists_mathura.xlsx")
        """
        resp = self.session.get(f"{self.base_url}/jobs/{job_id}/export?format=xlsx", timeout=60)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)
        print(f"✅ Saved to {filepath}")
        return filepath

    def health(self) -> Dict:
        """Check API health and browser pool status."""
        return self._get("/health")

    def metrics(self) -> Dict:
        """Get scraping statistics."""
        return self._get("/metrics")

    # ── Utilities ─────────────────────────────────────────────────────────────

    def leads_to_csv_string(self, leads: List[Dict]) -> str:
        """Convert a list of lead dicts to a CSV string (no file needed)."""
        if not leads:
            return ""
        fields = list(leads[0].keys())
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(leads)
        return buf.getvalue()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _post(self, path: str, payload: dict) -> dict:
        try:
            resp = self.session.post(
                f"{self.base_url}{path}",
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            try:
                detail = e.response.json().get("detail", str(e))
            except Exception:
                detail = str(e)
            raise LeadScraperError(f"HTTP {e.response.status_code}: {detail}")
        except requests.RequestException as e:
            raise LeadScraperError(f"Request failed: {e}")

    def _get(self, path: str) -> dict:
        try:
            resp = self.session.get(
                f"{self.base_url}{path}",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            try:
                detail = e.response.json().get("detail", str(e))
            except Exception:
                detail = str(e)
            raise LeadScraperError(f"HTTP {e.response.status_code}: {detail}")
        except requests.RequestException as e:
            raise LeadScraperError(f"Request failed: {e}")


# ── Quick CLI usage ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    query = sys.argv[2] if len(sys.argv) > 2 else "Dentists in Mathura"
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 20

    print(f"\n🔍 Scraping: '{query}' (max {count} results)")
    print(f"🌐 API: {base}\n")

    client = LeadScraperClient(base)

    print("📡 Checking health...")
    h = client.health()
    print(f"   Status: {h['status']} | Browsers: {h['browser_pool']['active']}/{h['browser_pool']['pool_size']}\n")

    print("🚀 Submitting async job...")
    job = client.create_job(query, max_results=count)
    print(f"   Job ID: {job['job_id']}\n")

    print("⏳ Waiting for results...")
    leads = client.wait_for_job(job["job_id"], verbose=True)

    print(f"\n📋 First 3 results:")
    for lead in leads[:3]:
        print(f"  • {lead.get('name')} | ⭐{lead.get('rating')} | 📞{lead.get('phone')} | 🌐{lead.get('website')}")

    out = f"leads_{query[:20].replace(' ','_')}.csv"
    client.download_csv(job["job_id"], out)
