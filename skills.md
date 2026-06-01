# Crawler Skills Reference

## Skill 1 - Finding Location Pages

### URL Pattern Matching
Check these paths in exact order by appending to base domain:
/locations
/location
/our-locations
/find-us
/find-a-location
/all-locations
/clinics
/our-clinics
/offices
/contact
/contacts
/visit-us
/stores
/branches
/about (fallback - sometimes has locations)

### Nav and Footer Link Text Matching
Scan all <a> tags on homepage for these strings
(case insensitive, partial match allowed):
"locations"
"find a location"
"our locations"
"find us"
"visit us"
"our clinics"
"contact us"
"near you"
"all locations"
"multiple locations"

### Sitemap Approach
GET /sitemap.xml first
Parse all <loc> entries
Filter URLs containing any location pattern words
Store as priority crawl list

---

## Skill 2 - Extracting Address Data

### US Address Regex Pattern
PRIMARY pattern - full address with zip:
\d{1,5}\s+[A-Za-z0-9\s,\.]+
(?:Ave|St|Rd|Blvd|Dr|Ln|Way|Ct|Pl|Pkwy|Hwy|
Suite|Ste|Floor|Fl)\.?
[\s,]+[A-Za-z\s]+,\s*[A-Z]{2}\s*\d{5}

SECONDARY pattern - city state zip only:
[A-Za-z\s]+,\s*[A-Z]{2}\s*\d{5}

### Phone Number Pattern
Use as secondary location signal:
\(?\d{3}\)?[\s\-\.]\d{3}[\s\-\.]\d{4}
Each unique phone number = likely 1 location

### Location Card Detection
Look for repeating HTML containers with these 
class/id patterns (partial match):
"location", "clinic", "office", "branch", 
"store", "address", "contact-info", 
"location-card", "find-us", "our-location"

Count repeating identical parent divs as locations.

### City List Pattern in Footer
Pipe or dash separated city list:
"Miami | Boca Raton | Fort Lauderdale"
"Miami - Boca Raton - Fort Lauderdale"
"Miami • Boca Raton • Fort Lauderdale"
Split by |, -, • and count city-like tokens.
City-like = Title Case word(s) not in 
common English vocabulary.

### Confidence Rules
3+ full addresses found         → high
2 full addresses found          → high
1 address + 2+ city mentions    → medium
Multiple phones + 1 address     → medium
1 address only                  → low
City list only, no addresses    → low

---

## Skill 3 - Handling Blocked Sites

### User Agent Rotation List
Rotate between these on each request:
UA1: Mozilla/5.0 (Windows NT 10.0; Win64; x64) 
     AppleWebKit/537.36 (KHTML, like Gecko) 
     Chrome/120.0.0.0 Safari/537.36
UA2: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) 
     AppleWebKit/537.36 (KHTML, like Gecko) 
     Chrome/120.0.0.0 Safari/537.36
UA3: Mozilla/5.0 (X11; Linux x86_64) 
     AppleWebKit/537.36 (KHTML, like Gecko) 
     Chrome/120.0.0.0 Safari/537.36

### Request Headers - Always Include
Accept: text/html,application/xhtml+xml,
        application/xml;q=0.9,*/*;q=0.8
Accept-Language: en-US,en;q=0.9
Accept-Encoding: gzip, deflate, br
Connection: keep-alive
Upgrade-Insecure-Requests: 1

### Response Code Handling
200 → process normally
301/302 → follow redirect, max 3 hops
403 → retry once with different user agent,
      then return confidence: "blocked"
429 → wait 5 seconds, retry once
503 → return confidence: "blocked"
timeout → return confidence: "unreachable"

---

## Skill 4 - Flask API Setup

### Endpoint Spec
POST /extract-locations
Content-Type: application/json

Request body:
{
  "website_url": "https://example.com",
  "company_name": "Infuzio"
}

Response: Always HTTP 200
Success/failure communicated in response body

### Health Check Endpoint
GET /health
Returns: 
{
  "status": "ok", 
  "version": "1.0.0"
}
Used by Render for uptime monitoring.
Used by Clay warmup ping before enrichment runs.

### CORS Handling
Handle OPTIONS preflight requests.
Return CORS headers on every response.
Required for Clay to reach the endpoint.

### Gunicorn Config for Render
workers: 2 (free tier is limited CPU)
timeout: 60 seconds
bind: 0.0.0.0:$PORT

---

## Skill 5 - Testing Approach

### Unit Test Cases
1. Site with dedicated /locations page
   Expected: confidence=high, count>=2
2. Site with footer addresses only
   Expected: confidence=medium, count>=1
3. JS-rendered site (body under 500 chars)
   Expected: confidence=js_rendered, count=null
4. Site returning 403
   Expected: confidence=blocked, count=null
5. Single location site
   Expected: confidence=low, count=1
6. Site with 5+ locations
   Expected: confidence=high, count>=5
7. Request timeout
   Expected: confidence=unreachable, count=null
8. Invalid URL input
   Expected: success=false, error message present
9. Missing company_name in request
   Expected: success=false, error message present
10. Empty website_url
    Expected: success=false, error message present

### What to Always Assert
- Response is valid JSON
- location_count is integer or null, never missing
- confidence is one of the 6 defined values
- locations_found is always a list, never null
- success is always boolean
- HTTP status is always 200

### Mock Strategy
Use responses library to mock HTTP calls.
Never make real HTTP requests in unit tests.
Create fixture HTML files for each test case.

---

## Skill 6 - Render Deployment

### Required Files
1. requirements.txt - all dependencies pinned
2. Procfile - gunicorn start command
3. render.yaml - Render service config
4. .gitignore - exclude cache and env files

### Procfile Content
web: gunicorn app.main:app 
     --workers 2 
     --bind 0.0.0.0:$PORT 
     --timeout 60 
     --log-level info

### render.yaml Content
services:
  - type: web
    name: medspa-location-crawler
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn app.main:app 
                  --workers 2 
                  --bind 0.0.0.0:$PORT 
                  --timeout 60
    healthCheckPath: /health
    envVars:
      - key: PYTHON_VERSION
        value: 3.11.0

### Warmup Strategy for Clay
Free tier spins down after 15 mins.
Before running any Clay enrichment table:
1. Add a dummy HTTP API column that hits /health
2. Wait for 200 response
3. Then run the actual extract-locations column
This prevents Clay timeouts on cold start.