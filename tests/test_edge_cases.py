"""
test_edge_cases.py – Phase 3 edge case tests.

Run with:  python test_edge_cases.py
Each section tests exactly one edge case.  Any AssertionError means a failure.
"""
import sys
import os
import types
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

from app.crawler import (
    is_js_only, validate_and_normalise_url, fetch_page,
    find_location_links, _get_headers, USER_AGENTS,
)
from app.extractor import (
    _normalise_address, extract_addresses, extract_city_mentions,
    deduplicate_addresses, extract_locations, calculate_confidence,
)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

def check(label, cond):
    print(f"  {'OK' if cond else 'XX'} {label}")
    assert cond, f"FAILED: {label}"


# ===========================================================================
# EC1 – JS-rendered detection (threshold = 500 chars)
# ===========================================================================
print("\n--- EC1: JS-rendered detection ---")

JS_HTML = """<html><head></head><body>
<div id="root"></div>
<script src="/bundle.js"></script>
<script>window.__data__={}</script>
</body></html>"""

RICH_HTML = """<html><body>
<p>Welcome to our med spa. We offer a wide range of treatments including
Botox, fillers, laser hair removal, chemical peels, microneedling, and more.
Our experienced team of licensed professionals is dedicated to helping you
look and feel your best. Visit us at any of our convenient locations across
South Florida. Book your appointment today!</p>
</body></html>"""

check("JS-only page (tiny text + script) -> True",  is_js_only(JS_HTML))
check("Rich text page (500+ chars body) -> False",  not is_js_only(RICH_HTML))
check("None input -> True",                          is_js_only(None))
check("Empty string -> True",                        is_js_only(""))

# A page with exactly 499 visible chars + script -> still flagged
short_html = f"<html><body>{'x' * 499}<script>a</script></body></html>"
check("499 chars + script -> True",  is_js_only(short_html))

rich_no_script = f"<html><body>{'x' * 600}</body></html>"
check("600 chars, no script -> False", not is_js_only(rich_no_script))

print(f"  {PASS} EC1 all checks passed")


# ===========================================================================
# EC2 – Blocked site handling (401, 403, 503 with UA rotation)
# ===========================================================================
print("\n--- EC2: Blocked site handling ---")

def _mock_response(status_code, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.url = "https://example.com"
    return resp

# 401 -> blocked on first attempt (no retry)
with patch("app.crawler.requests.Session") as mock_sess_cls:
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    sess.get.return_value = _mock_response(401)
    mock_sess_cls.return_value = sess
    html, status, error = fetch_page("https://example.com")
    check("401 -> error='blocked'",      error == "blocked")
    check("401 -> status=401",           status == 401)
    check("401 -> html=None",            html is None)
    check("401 -> only 1 request made",  sess.get.call_count == 1)

# 403 -> blocked on first attempt (no retry)
with patch("app.crawler.requests.Session") as mock_sess_cls:
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    sess.get.return_value = _mock_response(403)
    mock_sess_cls.return_value = sess
    html, status, error = fetch_page("https://example.com")
    check("403 -> error='blocked'",      error == "blocked")
    check("403 -> only 1 request made",  sess.get.call_count == 1)

# 503 -> retry once with different UA -> if still 503, return blocked
with patch("app.crawler.requests.Session") as mock_sess_cls, \
     patch("app.crawler.time.sleep"):
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    sess.get.return_value = _mock_response(503)
    mock_sess_cls.return_value = sess
    html, status, error = fetch_page("https://example.com")
    check("503 × 2 -> error='blocked'",   error == "blocked")
    check("503 × 2 -> status=503",        status == 503)
    # fetch_page is recursive so Session is created twice (once per call)
    check("503 × 2 -> tried 2 sessions",  mock_sess_cls.call_count == 2)

# UA rotation: exclude_ua works
original_ua = USER_AGENTS[0]
rotated_headers = _get_headers(exclude_ua=original_ua)
check("UA rotation excludes previous UA", rotated_headers["User-Agent"] != original_ua)

print(f"  {PASS} EC2 all checks passed")


# ===========================================================================
# EC3 – Redirect chain handling
# ===========================================================================
print("\n--- EC3: Redirect chains ---")

import requests as _requests_module

# Cross-domain redirect: resp.url ends up on a different domain
with patch("app.crawler.requests.Session") as mock_sess_cls:
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    r = _mock_response(200, "<html><body>" + "x" * 600 + "</body></html>")
    r.url = "https://other-domain.com/landing"  # different domain
    sess.get.return_value = r
    mock_sess_cls.return_value = sess
    html, status, error = fetch_page("https://example.com")
    check("Cross-domain redirect -> error='cross_domain_redirect'",
          error == "cross_domain_redirect")
    check("Cross-domain redirect -> html=None", html is None)

# Same-domain redirect is fine
with patch("app.crawler.requests.Session") as mock_sess_cls:
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    r = _mock_response(200, "<html><body>" + "x" * 600 + "</body></html>")
    r.url = "https://example.com/home"           # same domain
    sess.get.return_value = r
    mock_sess_cls.return_value = sess
    html, status, error = fetch_page("https://example.com")
    check("Same-domain redirect -> success", error is None and html is not None)

# TooManyRedirects exception
with patch("app.crawler.requests.Session") as mock_sess_cls:
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    sess.get.side_effect = _requests_module.exceptions.TooManyRedirects()
    mock_sess_cls.return_value = sess
    html, status, error = fetch_page("https://example.com")
    check("TooManyRedirects -> error='too_many_redirects'",
          error == "too_many_redirects")

# Session max_redirects is set to MAX_REDIRECTS
with patch("app.crawler.requests.Session") as mock_sess_cls:
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    sess.get.return_value = _mock_response(200, "<html><body>" + "x"*600 + "</body></html>")
    mock_sess_cls.return_value = sess
    fetch_page("https://example.com")
    from app.crawler import MAX_REDIRECTS
    check(f"Session.max_redirects set to {MAX_REDIRECTS}",
          sess.max_redirects == MAX_REDIRECTS)

print(f"  {PASS} EC3 all checks passed")


# ===========================================================================
# EC4 – Malformed URL validation
# ===========================================================================
print("\n--- EC4: URL validation ---")

ok_cases = [
    ("https://example.com",        "https://example.com"),
    ("http://example.com/path/",   "http://example.com/path"),
    ("example.com",                "https://example.com"),
    ("www.example.co.uk",          "https://www.example.co.uk"),
    ("sub.domain.example.com",     "https://sub.domain.example.com"),
    ("EXAMPLE.COM",                "https://example.com"),         # lowercased domain
]
for raw, expected in ok_cases:
    url, err = validate_and_normalise_url(raw)
    check(f"Valid URL {raw!r} -> {expected!r}", err is None and url == expected)

fail_cases = [
    ("",                    "empty"),
    ("notadomain",          "invalid"),
    ("localhost",           "invalid"),
    ("192.168.1.1",        "invalid"),   # bare IP has no alpha TLD
    ("https://",            "no domain"),
    ("just spaces   ",     "empty or invalid"),
]
for raw, reason in fail_cases:
    url, err = validate_and_normalise_url(raw)
    check(f"Invalid URL {raw!r} ({reason}) -> error", err is not None)

# Trailing slashes stripped
url, err = validate_and_normalise_url("https://example.com/path/to/page/")
check("Trailing slashes stripped", err is None and not url.endswith("/"))

print(f"  {PASS} EC4 all checks passed")


# ===========================================================================
# EC5 – Address normalisation and deduplication
# ===========================================================================
print("\n--- EC5: Address normalisation & dedup ---")

# _normalise_address expansions
pairs = [
    ("123 Main St, Miami, FL 33101",     "123 main street miami fl 33101"),
    ("456 Ocean Ave, Tampa, FL 33601",   "456 ocean avenue tampa fl 33601"),
    ("789 Park Blvd, Orlando, FL 32801", "789 park boulevard orlando fl 32801"),
    ("100 Pine Dr, Naples, FL 34101",    "100 pine drive naples fl 34101"),
    ("55 Oak Rd, Sarasota, FL 34230",    "55 oak road sarasota fl 34230"),
]
for raw, expected_norm in pairs:
    norm = _normalise_address(raw)
    check(f"norm({repr(raw)[:32]}) = {repr(expected_norm)[:32]}",
          norm == expected_norm)

# Same street, abbreviated vs full -> same dedup key
addr_short = "123 Main St, Miami, FL 33101"
addr_long  = "123 Main Street, Miami, FL 33101"
check("St and Street normalise to same key",
      _normalise_address(addr_short) == _normalise_address(addr_long))

# deduplicate_addresses uses normalised key
HTML_DUP = """<html><body>
<p>123 Main St, Suite 100, Miami, FL 33101</p>
<p>123 Main Street, Suite 100, Miami, FL 33101</p>
<p>456 Ocean Blvd, Fort Lauderdale, FL 33301</p>
</body></html>"""

r1 = extract_locations("https://example.com/p1", HTML_DUP)
r2 = extract_locations("https://example.com/p2", HTML_DUP)
merged = deduplicate_addresses([r1, r2])
# The two "123 Main" variants are the same; plus "456 Ocean" = 2 unique
check(f"Dedup collapses St vs Street ({len(merged)} unique addresses)", len(merged) == 2)

# Punctuation stripped: comma, period, hash
raw_with_punct = "123 Main St., #200, Miami, FL 33101"
raw_clean      = "123 Main Street 200 Miami FL 33101"
# normalise both and compare – after punct-strip and abbrev-expand they should match
n1 = _normalise_address(raw_with_punct)
n2 = _normalise_address(raw_clean)
check("Punctuation stripped during normalisation", n1 == n2)

print(f"  {PASS} EC5 all checks passed")


# ===========================================================================
# EC6 – Footer city list with dash separators and service prefixes
# ===========================================================================
print("\n--- EC6: Footer city list detection ---")

DASH_FOOTER_HTML = """<html><body>
<footer>
  <p>Serving Miami - Boca Raton - Fort Lauderdale</p>
</footer>
</body></html>"""

PIPE_FOOTER_HTML = """<html><body>
<footer>
  <p>Miami | Boca Raton | Fort Lauderdale</p>
</footer>
</body></html>"""

MIXED_HTML = """<html><body>
<footer>
  <p>Locations in Miami - Boca Raton - Fort Lauderdale</p>
  <p>Also available in Palm Beach / Delray</p>
</footer>
</body></html>"""

# Dash-separated with "Serving" prefix
dash_cities = extract_city_mentions(DASH_FOOTER_HTML)
check("Dash-separated cities extracted",    len(dash_cities) >= 3)
check("'Miami' found in dash list",         "Miami" in dash_cities)
check("'Boca Raton' found in dash list",    "Boca Raton" in dash_cities)
check("'Fort Lauderdale' found in dash list", "Fort Lauderdale" in dash_cities)
check("'Serving' NOT in cities",            not any("Serving" in c for c in dash_cities))

# Pipe-separated (original behaviour still works)
pipe_cities = extract_city_mentions(PIPE_FOOTER_HTML)
check("Pipe-separated cities still extracted", len(pipe_cities) >= 3)

# Mixed separators
mixed_cities = extract_city_mentions(MIXED_HTML)
check("Mixed dash + slash separators work", len(mixed_cities) >= 4)

# 'Locations in' prefix stripped
LOC_IN_HTML = """<html><body>
<footer><p>Locations in Tampa - Clearwater - St Petersburg</p></footer>
</body></html>"""
loc_cities = extract_city_mentions(LOC_IN_HTML)
check("'Locations in' prefix stripped",     "Tampa" in loc_cities)
check("'Locations in' not in city list",
      not any("Locations" in c for c in loc_cities))

# City mentions feed into confidence
cities_for_conf = ["Miami", "Boca Raton", "Fort Lauderdale"]
conf = calculate_confidence([], 0, 0, cities_for_conf)
check("3 city mentions with no addresses -> medium confidence", conf == "medium")

print(f"  {PASS} EC6 all checks passed")


# ===========================================================================
print("\n\033[92m=== All 6 edge cases PASSED ===\033[0m\n")
