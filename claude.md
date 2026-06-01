# MedSpa Location Crawler - Claude Code Instructions

## Project Purpose
A Python Flask web crawler API that extracts location 
count and address data from med spa websites. 
Deployed on Render free tier. Called from Clay's 
HTTP API column for the AscendIQ cold outbound campaign.

## What This Does
1. Accepts a website URL + company name via POST request
2. Crawls the website looking for location/contact pages
3. Extracts all physical addresses and location data
4. Returns structured JSON with location count + addresses

## Core Rules - Never Break These
- Never crawl more than 10 pages per domain per request
- Always respect robots.txt
- Always add 1-2 second delay between page requests
- Never store any data - stateless per request
- Always return valid JSON even on failure
- Timeout any single request after 10 seconds
- Timeout entire crawl after 30 seconds
- Always set CORS headers so Clay can reach it

## Tech Stack
- Python 3.11+
- Flask for API endpoint
- BeautifulSoup4 for HTML parsing
- Requests for HTTP fetching
- Regex for address pattern matching
- Gunicorn for production server
- Pytest for testing
- Render for deployment (free tier)

## Project Structure
medspa-location-crawler/
├── CLAUDE.md
├── SKILLS.md
├── README.md
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── crawler.py
│   ├── extractor.py
│   └── api.py
├── tests/
│   ├── __init__.py
│   └── test_crawler.py
├── requirements.txt
├── Procfile
├── render.yaml
└── .gitignore

## Response Format - Always Return This Exact Shape
{
  "success": true/false,
  "location_count": integer or null,
  "confidence": "high/medium/low/blocked/
                 unreachable/js_rendered",
  "source_page": "which page had the best data",
  "locations_found": ["address1", "address2"],
  "detection_method": "location_page/footer/
                        nav/subpages/fallback",
  "error": null or "error message string"
}

## Confidence Scoring Rules
- high: dedicated /locations or /contact page found
  with 2+ structured addresses
- medium: addresses found in footer or nav mentions
  of multiple cities
- low: only 1 address found or inferred from city slugs
- blocked: site returned 403/401/503
- unreachable: site timed out or DNS failed
- js_rendered: page body under 500 chars, likely JS app

## Priority Order for Crawling
1. Check /sitemap.xml first
2. Look for location-pattern URLs in homepage nav/footer
3. Crawl homepage for address blocks
4. Check /locations, /contact, /find-us as fallbacks
5. Never go deeper than 2 levels from homepage

## Error Handling Rules
- Site blocked/403 → confidence: "blocked", 
  location_count: null
- Site timeout → confidence: "unreachable", 
  location_count: null
- No addresses found → confidence: "low", 
  location_count: 1
- JS-only site → confidence: "js_rendered", 
  location_count: null

## Render Specific Config
- App runs on PORT environment variable
- Render sets PORT automatically
- Health check endpoint required at /health
- Render free tier spins down after 15 mins inactivity
- First request after spin-down takes 30-50 seconds
- Solution: Clay pings /health before running 
  the main enrichment table

## CORS Headers Required
Every response must include:
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: POST, GET, OPTIONS
Access-Control-Allow-Headers: Content-Type