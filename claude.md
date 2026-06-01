# MedSpa Location Crawler - Claude Code Instructions

## Project Purpose
A Python web crawler API that extracts location count and 
address data from med spa websites. Used as an HTTP API 
endpoint in Clay for the AscendIQ cold outbound campaign.

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

## Tech Stack
- Python 3.11+
- Flask for API endpoint
- BeautifulSoup4 for HTML parsing
- Requests for HTTP fetching
- Regex for address pattern matching
- Pytest for testing

## Response Format - Always Return This Exact Shape
{
  "success": true/false,
  "location_count": integer,
  "confidence": "high" / "medium" / "low",
  "source_page": "which page had the best data",
  "locations_found": ["address1", "address2"],
  "detection_method": "location_page/footer/nav/subpages",
  "error": null or "error message"
}

## Confidence Scoring Rules
- high: found a dedicated /locations or /contact page 
  with 2+ structured addresses
- medium: found addresses in footer or nav mentions 
  of multiple cities
- low: only found 1 address or inferred from city 
  slugs in URLs

## Priority Order for Crawling
1. Check sitemap.xml first
2. Look for location-pattern URLs in homepage nav/footer
3. Crawl homepage for address blocks
4. Check /locations, /contact, /find-us as fallbacks
5. Never go deeper than 2 levels from homepage

## Error Handling Rules
- Site blocked/403 → return location_count: null, 
  confidence: "blocked"
- Site down/timeout → return location_count: null, 
  confidence: "unreachable"  
- No addresses found → return location_count: 1, 
  confidence: "low" (assume single location)
- JS-only site → return location_count: null, 
  confidence: "js_rendered"

## Clay Integration
This API is called from Clay's HTTP API column.
Clay sends POST requests. Keep response under 10KB.
Response time must be under 30 seconds or Clay times out.

## Development Phases
Phase 1: Core crawler + address extractor
Phase 2: Flask API endpoint
Phase 3: Edge case handling
Phase 4: Testing suite
Phase 5: Railway deployment config