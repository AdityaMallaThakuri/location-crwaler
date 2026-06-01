# MedSpa Location Crawler

A stateless HTTP API that crawls med spa websites and returns structured location data — address count, street addresses, and confidence score. Built for the AscendIQ cold outbound campaign; called from Clay's HTTP API column.

---

## What This Does

1. Accepts a `POST` request with a website URL and company name
2. Crawls up to 10 pages of the website (sitemap → nav links → common paths)
3. Extracts US street addresses using regex + HTML structure analysis
4. Returns a JSON object with location count, addresses found, and a confidence rating

Every response is HTTP 200 with a structured JSON body — errors are communicated inside the body so Clay never receives a non-200 status.

---

## Local Development Setup

**Requirements:** Python 3.11+

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/medspa-location-crawler.git
cd medspa-location-crawler

# 2. Create and activate a virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the development server
python app/main.py
# Server starts at http://localhost:5000
```

---

## Testing with curl

**Health check** (confirms the server is alive):
```bash
curl http://localhost:5000/health
# {"status": "ok", "version": "1.0.0"}
```

**Extract locations** (replace the URL with the target med spa):
```bash
curl -X POST http://localhost:5000/extract-locations \
  -H "Content-Type: application/json" \
  -d '{"website_url": "https://example-medspa.com", "company_name": "Example MedSpa"}'
```

**Expected response:**
```json
{
  "success": true,
  "location_count": 3,
  "confidence": "high",
  "source_page": "https://example-medspa.com/locations",
  "locations_found": [
    "123 Main St, Miami, FL 33101",
    "456 Ocean Blvd, Fort Lauderdale, FL 33301",
    "789 Brickell Ave, Miami, FL 33131"
  ],
  "detection_method": "location_page",
  "error": null
}
```

**Run the test suite:**
```bash
# Unit tests only (no network, fast)
pytest tests/test_crawler.py -m "not integration" -v

# All tests including live HTTP call
pytest tests/test_crawler.py -v
```

---

## Deploy to Render — Step by Step

### Prerequisites
- GitHub account
- Render account (free tier works): https://render.com

### Step 1 — Push to GitHub

```bash
# Inside the project directory
git init
git add .
git commit -m "Initial commit: MedSpa Location Crawler"

# Create a new GitHub repo (GitHub CLI)
gh repo create medspa-location-crawler --public --source=. --remote=origin --push

# OR manually via GitHub UI, then:
git remote add origin https://github.com/YOUR_USERNAME/medspa-location-crawler.git
git branch -M main
git push -u origin main
```

### Step 2 — Create a Render Web Service

**Option A — Blueprint (automatic, uses render.yaml):**
1. Go to https://dashboard.render.com
2. Click **New → Blueprint**
3. Connect your GitHub account and select the `medspa-location-crawler` repo
4. Render reads `render.yaml` and configures the service automatically
5. Click **Apply** — Render builds and deploys

**Option B — Manual setup:**
1. Go to https://dashboard.render.com
2. Click **New → Web Service**
3. Connect GitHub → select `medspa-location-crawler` repo
4. Fill in these exact settings:

| Field | Value |
|---|---|
| Name | `medspa-location-crawler` |
| Runtime | `Python 3` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app.main:app --workers 2 --bind 0.0.0.0:$PORT --timeout 60` |
| Instance Type | `Free` |

5. Under **Environment Variables**, add:
   - Key: `PYTHON_VERSION` / Value: `3.11.0`

6. Click **Create Web Service**

### Step 3 — Verify the Deployment

Once Render shows **Live**, test your endpoint:

```bash
# Replace with your actual Render URL
export API_URL="https://medspa-location-crawler.onrender.com"

# Health check
curl $API_URL/health

# Test crawl
curl -X POST $API_URL/extract-locations \
  -H "Content-Type: application/json" \
  -d '{"website_url": "https://example.com", "company_name": "Test"}'
```

---

## Clay HTTP API Column Configuration

In your Clay table, add an **HTTP API** column with these exact settings:

| Setting | Value |
|---|---|
| Method | `POST` |
| URL | `https://medspa-location-crawler.onrender.com/extract-locations` |
| Content-Type | `application/json` |
| Body | `{"website_url": "{{Website}}", "company_name": "{{Company Name}}"}` |

**Map response fields to Clay columns:**

| Clay Column | JSON Path |
|---|---|
| Location Count | `location_count` |
| Confidence | `confidence` |
| Addresses | `locations_found` |
| Source Page | `source_page` |
| Detection Method | `detection_method` |
| Crawl Error | `error` |

---

## Response Field Definitions

| Field | Type | Description |
|---|---|---|
| `success` | boolean | `true` if the crawl completed without a fatal error |
| `location_count` | integer or null | Total number of locations detected; `null` on blocked/unreachable/js_rendered |
| `confidence` | string | Reliability rating — see table below |
| `source_page` | string or null | URL of the page that yielded the most location data |
| `locations_found` | array | List of full US street addresses extracted |
| `detection_method` | string or null | How the data was found — `location_page`, `footer`, `nav`, `subpages` |
| `error` | string or null | Human-readable error description; `null` on success |

### Confidence Values

| Value | Meaning |
|---|---|
| `high` | Found a dedicated /locations or /contact page with 2+ full addresses |
| `medium` | Found 1 address + multiple city mentions, or multiple phones |
| `low` | Found only 1 address, or no signals — assume single location |
| `blocked` | Site returned 401, 403, or 503 — could not crawl |
| `unreachable` | DNS failure, connection timeout, or redirect loop |
| `js_rendered` | Page body has < 500 chars of text — likely a JavaScript SPA |

---

## Warmup Strategy for Clay

**The problem:** Render's free tier spins the service down after 15 minutes of inactivity. The first request after spin-down takes 30–50 seconds. Clay's HTTP API column has a hard timeout of 30 seconds — so a cold start **will fail** in Clay.

**The solution:** Ping `/health` before running the enrichment table to wake the service.

### How to Set It Up in Clay

1. **Add a warmup column** (run this manually before each enrichment session):
   - Add an HTTP API column
   - Method: `GET`
   - URL: `https://medspa-location-crawler.onrender.com/health`
   - Run it on a single test row and wait for a `{"status": "ok"}` response

2. **Wait ~5 seconds** after the health check succeeds

3. **Run your extract-locations column** — the service is now warm and will respond in 5–15 seconds

### Alternative: Keep-Alive with UptimeRobot (free)

1. Sign up at https://uptimerobot.com (free tier)
2. Add a new monitor:
   - Type: `HTTP(s)`
   - URL: `https://medspa-location-crawler.onrender.com/health`
   - Monitoring interval: `5 minutes`
3. UptimeRobot pings `/health` every 5 minutes, keeping the service warm — Clay will never hit a cold start

---

## Project Structure

```
medspa-location-crawler/
├── app/
│   ├── __init__.py
│   ├── main.py        # Flask app factory, CORS, gunicorn entry point
│   ├── crawler.py     # URL discovery, page fetching, robots.txt
│   ├── extractor.py   # Address regex, confidence scoring, deduplication
│   └── api.py         # POST /extract-locations route, rate limiting
├── tests/
│   ├── __init__.py
│   ├── test_crawler.py     # 22 pytest tests (unit + integration)
│   └── test_edge_cases.py  # Phase 3 edge case verification
├── CLAUDE.md          # Project rules and AI coding instructions
├── skills.md          # Pattern reference for crawler and extractor
├── requirements.txt   # Pinned dependencies
├── Procfile           # Gunicorn start command for Render
├── render.yaml        # Render Blueprint config
├── pytest.ini         # Pytest marker registration
├── conftest.py        # Pytest sys.path setup
└── .gitignore
```
