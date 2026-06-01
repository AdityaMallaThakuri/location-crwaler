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
git clone https://github.com/AdityaMallaThakuri/location-crwaler.git
cd location-crwaler

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

## Deploy to Railway

### Prerequisites
- GitHub account (repo already pushed)
- Railway account: https://railway.app (sign up free with GitHub)
- Railway CLI (optional but faster): `npm install -g @railway/cli`

---

### Option A — Dashboard Deploy (no CLI needed)

1. Go to https://railway.app and sign in with GitHub
2. Click **"New Project"** → **"Deploy from GitHub repo"**
3. Select **`AdityaMallaThakuri/location-crwaler`**
4. Railway auto-detects `railway.json` and configures everything
5. Click **"Deploy"** — build takes ~60 seconds
6. Go to **Settings → Networking → Generate Domain** to get your public URL

---

### Option B — CLI Deploy (faster)

```bash
# Install Railway CLI
npm install -g @railway/cli

# Log in
railway login

# Link to a new project (run from inside the repo folder)
railway init

# Deploy
railway up

# Get your live URL
railway domain
```

---

### Verify the Deployment

Once deployed, test with your Railway URL:

```bash
# Replace with your actual Railway URL
export API_URL="https://your-app.up.railway.app"

# Health check
curl $API_URL/health
# Expected: {"status": "ok", "version": "1.0.0"}

# Test crawl
curl -X POST $API_URL/extract-locations \
  -H "Content-Type: application/json" \
  -d '{"website_url": "https://lashdolls.com", "company_name": "Lash Dolls"}'
```

---

## Clay HTTP API Column Configuration

In your Clay table, add an **HTTP API** column with these exact settings:

| Setting | Value |
|---|---|
| Method | `POST` |
| URL | `https://your-app.up.railway.app/extract-locations` |
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
├── Procfile           # Gunicorn start command
├── railway.json       # Railway deployment config
├── pytest.ini         # Pytest marker registration
├── conftest.py        # Pytest sys.path setup
└── .gitignore
```
