# Crawler Skills Reference

## Skill 1 - Finding Location Pages

Priority patterns to check in this exact order:

### URL Pattern Matching
MUST CHECK these paths by appending to base domain:
/locations
/location  
/our-locations
/find-us
/find-a-location
/clinics
/our-clinics
/offices
/contact
/contacts
/visit-us
/stores
/branches

### Nav/Footer Link Text Matching
Scan all <a> tags on homepage for these text patterns 
(case insensitive):
"locations"
"find a location"
"our locations" 
"find us"
"visit us"
"our clinics"
"contact us"
"near you"
"all locations"

### Sitemap Approach
GET /sitemap.xml first
Parse all <loc> entries
Filter for any URL containing location pattern words
Prioritize those URLs

---

## Skill 2 - Extracting Address Data

### US Address Regex Pattern
Use this pattern to find street addresses:
\d{1,5}\s+[A-Za-z0-9\s,\.]+(?:Ave|St|Rd|Blvd|Dr|Ln|Way|Ct|Pl|Pkwy|Hwy|Suite|Ste)\.?[\s,]+[A-Za-z\s]+,\s*[A-Z]{2}\s*\d{5}

### Phone Number Pattern (each unique = likely 1 location)
\(?\d{3}\)?[\s\-]\d{3}[\s\-]\d{4}

### Location Card Detection
Look for repeating HTML structures with these class names:
"location", "clinic", "office", "branch", "store", 
"address", "contact-info", "location-card", "find-us"

Count repeating identical parent containers as locations.

### City Mention Pattern
Footer often has pipe-separated city list:
"Miami | Boca Raton | Fort Lauderdale"
Split by | or / or • and count city-like tokens.

### Confidence Rules
3+ full addresses found → high confidence
2 full addresses found → high confidence  
1 address + multiple city mentions → medium confidence
1 address only → low confidence
Phone count > 1 but no addresses → medium confidence

---

## Skill 3 - Handling Blocked Sites

### User Agent Rotation
Rotate between these on each request:
- Mozilla/5.0 (Windows NT 10.0; Win64; x64) 
  AppleWebKit/537.36
- Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) 
  AppleWebKit/537.36
- Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36

### Request Headers to Always Include
{
  "Accept": "text/html,application/xhtml+xml",
  "Accept-Language": "en-US,en;q=0.9",
  "Accept-Encoding": "gzip, deflate, br",
  "Connection": "keep-alive",
  "Upgrade-Insecure-Requests": "1"
}

### Delay Rules
Between page requests: random 1-2 seconds
After a 429 response: wait 5 seconds then retry once
After a 403 response: stop crawling that domain

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

Response: Always 200 status even on errors
(Clay handles errors based on response body, not status)

### Health Check Endpoint
GET /health
Returns: {"status": "ok", "version": "1.0.0"}

### Rate Limiting
Max 10 concurrent requests
Queue anything beyond that
Return 429 if queue exceeds 50

---

## Skill 5 - Testing Approach

### Test Cases to Always Cover
1. Site with dedicated /locations page (expect high confidence)
2. Site with footer addresses only (expect medium confidence)  
3. Site that is JS-rendered (expect js_rendered)
4. Site that blocks crawlers (expect blocked)
5. Single location site (expect count 1, low confidence)
6. Site with 5+ locations (expect count 5+, high confidence)
7. Site that times out (expect unreachable)
8. Invalid URL input (expect error in response)

### Real Med Spa URLs to Test Against
Use these actual med spa websites for testing:
- A single location med spa in your target metro
- A 2-3 location regional chain
- A franchise med spa (should detect multiple)

### What to Assert
- Response is always valid JSON
- location_count is always integer or null
- confidence is always one of the defined values
- Response time is under 30 seconds
- locations_found is always a list (empty or populated)