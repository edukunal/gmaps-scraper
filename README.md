# 🗺️ Google Maps Lead Scraper API — God Tier v2.0

Production-grade async lead scraping backend.  
**FastAPI + Playwright + Multi-tab Parallel Extraction + SSE Streaming + CSV/Excel Export**

---

## 📁 Full Folder Structure

```
gmaps-scraper/
├── app/
│   ├── main.py                          ← FastAPI app + lifespan startup
│   ├── config.py                        ← All settings via env vars
│   ├── api/
│   │   └── routes.py                    ← All HTTP endpoints
│   ├── core/
│   │   ├── browser_manager.py           ← Async browser pool (auto-restart, stealth)
│   │   ├── job_manager.py               ← Async job queue + SSE push + webhooks
│   │   ├── logger.py                    ← structlog JSON logging
│   │   └── metrics.py                   ← In-memory stats
│   ├── scrapers/
│   │   └── google_maps_scraper.py       ← Core scraper (multi-tab parallel)
│   ├── services/
│   │   └── scraper_service.py           ← Orchestration + streaming + dedup
│   ├── models/
│   │   └── schemas.py                   ← Pydantic v2 models
│   ├── middleware/
│   │   └── logging_middleware.py        ← Request timing + IDs
│   └── utils/
│       ├── helpers.py                   ← Cleaning / parsing
│       ├── user_agents.py               ← Fingerprint rotation
│       └── export.py                    ← CSV + Excel export
├── sdk/
│   ├── python/
│   │   └── gmaps_scraper_sdk.py         ← Python SDK (sync + stream + download)
│   └── javascript/
│       └── gmaps-scraper-sdk.js         ← JS SDK (Node.js + browser)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## 🚀 COMPLETE BEGINNER GUIDE — How to Deploy & Use

### Step 1 — What You Need

You need one of these to run the API:
- A computer with Docker installed, OR
- A cloud host like **JustRunMyApp**, Railway, Render, or Fly.io

You will get a **URL** after deployment. That URL IS your API.  
Example URL: `https://my-scraper.justrunmyapp.com`

---

### Step 2 — Deploy on JustRunMyApp (Easiest)

1. **Download this project** (extract the ZIP)
2. **Upload to GitHub:**
   - Go to github.com → New Repository → Upload all files
3. **Go to JustRunMyApp** → Connect your GitHub repo
4. **Set these settings:**
   - Build Command: *(leave blank — Dockerfile handles it)*
   - Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - RAM: **minimum 2.5 GB** (Chromium needs memory)
5. **Add Environment Variables** in dashboard:
   ```
   BROWSER_POOL_SIZE=2
   MAX_CONCURRENT_SCRAPES=2
   BROWSER_HEADLESS=true
   ```
6. Click **Deploy**
7. Wait ~3 minutes (Playwright downloads Chromium)
8. Your API URL appears in dashboard → **That's it!**

✅ Visit `https://your-url/docs` to see your API working.

---

### Step 3 — Deploy with Docker (Local / VPS)

```bash
# 1. Download and extract the project
cd gmaps-scraper

# 2. Copy env file
cp .env.example .env

# 3. Build and start
docker compose up --build

# 4. Your API is live at:
#    http://localhost:8000
#    Open: http://localhost:8000/docs
```

---

### Step 4 — How to Send Requests (3 Ways)

---

#### WAY 1: Browser UI (Zero Code)

Open: `http://your-url/docs`

This is a full interactive UI. Click any endpoint → fill the form → click Execute.  
You'll see the response directly in the browser.

---

#### WAY 2: Python (Recommended for Beginners)

**Setup (one time):**
```bash
pip install requests
```

**Copy `sdk/python/gmaps_scraper_sdk.py` to your project, then:**

```python
from gmaps_scraper_sdk import LeadScraperClient

# 🔑 Replace with YOUR deployed URL
client = LeadScraperClient("http://localhost:8000")

# ─── EXAMPLE 1: Simple scrape (waits for all results) ─────────────────
leads = client.scrape("Dentists in Mathura", max_results=50)

for lead in leads:
    print(f"Name:    {lead['name']}")
    print(f"Phone:   {lead['phone']}")
    print(f"Rating:  {lead['rating']}")
    print(f"Address: {lead['address']}")
    print(f"Website: {lead['website']}")
    print("---")


# ─── EXAMPLE 2: Async job (for large scrapes) ──────────────────────────
job = client.create_job("Gyms in Delhi", max_results=200)
print(f"Job started: {job['job_id']}")

# Come back later and check:
results = client.wait_for_job(job["job_id"], verbose=True)
# Output:
#   [RUNNING] 23% — 46 leads so far...
#   [RUNNING] 67% — 134 leads so far...
#   ✅ Done! 200 leads in 143.2s


# ─── EXAMPLE 3: Live stream (see each lead as it's found) ─────────────
for lead in client.stream_job("Restaurants in Agra", max_results=100):
    print(f"Found: {lead['name']} | {lead['phone']}")
# Each line prints instantly as that place is scraped


# ─── EXAMPLE 4: Download as CSV ────────────────────────────────────────
job = client.create_job("Lawyers in Mumbai", max_results=500)
results = client.wait_for_job(job["job_id"])
client.download_csv(job["job_id"], "lawyers_mumbai.csv")
# ✅ Saved to lawyers_mumbai.csv


# ─── EXAMPLE 5: Download as Excel ─────────────────────────────────────
client.download_excel(job["job_id"], "lawyers_mumbai.xlsx")
# ✅ Saved to lawyers_mumbai.xlsx
```

**Run it:**
```bash
python my_script.py
```

---

#### WAY 3: JavaScript / Node.js

**Setup:**
```bash
# Node.js 18+ — no npm install needed, uses built-in fetch
```

**Copy `sdk/javascript/gmaps-scraper-sdk.js` to your project, then:**

```javascript
const { LeadScraperClient } = require("./gmaps-scraper-sdk.js");

const client = new LeadScraperClient("http://localhost:8000");

// Simple scrape
const leads = await client.scrape("Dentists in Mathura", { maxResults: 50 });
leads.forEach(l => console.log(l.name, l.phone));

// Live stream
await client.streamJob("Gyms in Delhi", { maxResults: 100 },
  (lead) => console.log("Found:", lead.name, lead.phone),
  (done) => console.log("Total:", done.total)
);

// Download CSV
await client.downloadCsv(jobId, "leads.csv");
```

---

#### WAY 4: Raw HTTP (curl / Postman / any language)

```bash
# ── Sync scrape ────────────────────────────────────────────────────────
curl -X POST "http://localhost:8000/scrape" \
  -H "Content-Type: application/json" \
  -d '{"query": "Dentists in Mathura", "max_results": 50}'

# ── Submit async job ──────────────────────────────────────────────────
curl -X POST "http://localhost:8000/jobs" \
  -H "Content-Type: application/json" \
  -d '{"query": "Gyms in Delhi", "max_results": 200}'
# Returns: {"job_id": "abc-123-...", "status": "queued"}

# ── Check job status ──────────────────────────────────────────────────
curl "http://localhost:8000/jobs/abc-123-.../status"
# Returns: {"status": "running", "progress": 45, "results_so_far": 90}

# ── Get results when done ─────────────────────────────────────────────
curl "http://localhost:8000/jobs/abc-123-.../results"

# ── Download CSV ──────────────────────────────────────────────────────
curl "http://localhost:8000/jobs/abc-123-.../export?format=csv" -o leads.csv

# ── Download Excel ────────────────────────────────────────────────────
curl "http://localhost:8000/jobs/abc-123-.../export?format=xlsx" -o leads.xlsx

# ── Health check ──────────────────────────────────────────────────────
curl "http://localhost:8000/health"
```

---

## 📋 All API Endpoints

| Method | Endpoint | What it does |
|--------|----------|-------------|
| `POST` | `/scrape` | Sync scrape — waits and returns all results |
| `POST` | `/jobs` | Submit async job — returns job_id immediately |
| `GET`  | `/jobs` | List all jobs |
| `GET`  | `/jobs/{id}` | Check job status + progress % |
| `GET`  | `/jobs/{id}/results` | Get full results when done |
| `GET`  | `/jobs/{id}/stream` | SSE live stream of leads as scraped |
| `GET`  | `/jobs/{id}/export?format=csv` | Download CSV |
| `GET`  | `/jobs/{id}/export?format=xlsx` | Download Excel |
| `DELETE` | `/jobs/{id}` | Delete job |
| `GET`  | `/health` | API + browser pool health |
| `GET`  | `/metrics` | Scraping statistics |
| `GET`  | `/docs` | Interactive Swagger UI |

---

## 📦 Example Response

```json
{
  "success": true,
  "query": "Dentists in Mathura",
  "total_results": 42,
  "execution_time": "87.3s",
  "data": [
    {
      "name": "Dr. Sharma Dental Clinic",
      "category": "Dentist",
      "rating": 4.5,
      "reviews_count": 128,
      "address": "MG Road, Mathura, Uttar Pradesh 281001",
      "city": "Mathura",
      "state": "Uttar Pradesh",
      "postal_code": "281001",
      "phone": "+91 98765 43210",
      "email": "sharma@dentalclinic.com",
      "website": "https://sharmadentalclinic.com",
      "maps_url": "https://www.google.com/maps/place/...",
      "place_id": "ChIJ...",
      "latitude": 27.4924,
      "longitude": 77.6737,
      "opening_hours": [
        "Monday: 9:00 AM – 7:00 PM",
        "Tuesday: 9:00 AM – 7:00 PM",
        "Wednesday: 9:00 AM – 7:00 PM"
      ],
      "is_open_now": true,
      "description": "Multi-specialty dental clinic with 15 years experience.",
      "images": ["https://lh5.googleusercontent.com/..."],
      "services": ["Root Canal", "Teeth Whitening", "Braces"],
      "social_links": {
        "facebook": "https://facebook.com/sharmadentalclinic",
        "instagram": "https://instagram.com/sharmadentalclinic"
      },
      "data_quality_score": 0.9,
      "scraped_at": "2025-05-28T10:30:00Z"
    }
  ]
}
```

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8000` | Server port (auto-set by JustRunMyApp) |
| `BROWSER_POOL_SIZE` | `3` | Number of Chrome instances |
| `DETAIL_TAB_CONCURRENCY` | `5` | Parallel tabs per scrape job |
| `MAX_CONCURRENT_SCRAPES` | `3` | Max parallel scrape jobs |
| `BROWSER_HEADLESS` | `true` | Run Chrome headless |
| `DEBUG` | `false` | Verbose logging |
| `PROXY_URL` | *(blank)* | Proxy server URL |
| `PROXY_USERNAME` | *(blank)* | Proxy auth |
| `PROXY_PASSWORD` | *(blank)* | Proxy auth |

---

## 🏎️ Performance Guide

| Setting | Small VPS (1GB) | Medium (2GB) | Large (4GB+) |
|---------|----------------|--------------|--------------|
| `BROWSER_POOL_SIZE` | 1 | 2 | 4 |
| `DETAIL_TAB_CONCURRENCY` | 2 | 4 | 8 |
| `MAX_CONCURRENT_SCRAPES` | 1 | 2 | 4 |
| Leads/min (approx) | ~15 | ~40 | ~80+ |

**Speed Tips:**
- Use `extract_details: false` for **10x faster** list-only scraping (name/rating/URL only)
- Use async jobs (`POST /jobs`) for anything over 50 results
- Use `POST /jobs` with `webhookUrl` to get notified when done instead of polling

---

## 🔧 Architecture — What Makes It God Tier

| Feature | Implementation |
|---------|---------------|
| **Multi-tab parallel** | N Playwright tabs scrape simultaneously per job |
| **JS bulk extraction** | Single `page.evaluate()` grabs ALL fields — 5x faster than locator chains |
| **Session warm-up** | Visits google.com first — looks like a real human |
| **Stealth injection** | Hides webdriver, fakes plugins, canvas noise, realistic screen |
| **Adaptive scroll** | MutationObserver-based end detection + 6-stale-round abort |
| **Auto-restart pool** | Browser slots restart after 60 requests or 5 errors — zero downtime |
| **SSE streaming** | Leads pushed to client in real-time via Server-Sent Events |
| **Webhook support** | POST results to your URL when job completes |
| **Deduplication** | By (name, address) before any data returned |
| **Pydantic v2 models** | Strict types + auto quality score per lead |
| **CSV + Excel export** | Styled Excel with blue headers, auto column widths |
| **Resource blocking** | Fonts/media/ad networks killed — pages load 40% faster |
| **Selector self-healing** | 5+ fallback selectors per field — survives DOM changes |

---

## ⚖️ Legal Note

Scraping public business data is used by many tools (n8n, Apollo, etc.) but Google's ToS technically prohibits automated access. For fully compliant commercial use, consider [Google Places API](https://developers.google.com/maps/documentation/places/web-service) ($0.017/request). Use this tool responsibly.
