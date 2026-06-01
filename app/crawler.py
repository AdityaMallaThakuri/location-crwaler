"""
crawler.py - Web crawler for med spa location pages.

Accepts a website URL and returns a prioritised list of page URLs to extract
location data from (max 10 pages).  Follows the rules in CLAUDE.md and the
priority order in skills.md Skill 1.

Edge cases handled (Phase 3):
  EC1  JS-rendered sites   – flagged when body text < 500 chars + scripts present
  EC2  Blocked sites       – 401/403/503 with rotated-UA retry
  EC3  Redirect chains     – max 3 redirects; cross-domain redirect → stop
  EC4  Malformed URLs      – validate domain, add scheme, strip trailing slash
"""

import random
import re
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
]

BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Ordered by likelihood of containing location data (skills.md Skill 1)
LOCATION_PATHS = [
    "/locations",
    "/location",
    "/our-locations",
    "/find-us",
    "/find-a-location",
    "/clinics",
    "/our-clinics",
    "/offices",
    "/contact",
    "/contacts",
    "/visit-us",
    "/stores",
    "/branches",
]

# Link text patterns that suggest a locations page (skills.md Skill 1)
LOCATION_LINK_TEXTS = [
    "locations",
    "find a location",
    "our locations",
    "find us",
    "visit us",
    "our clinics",
    "contact us",
    "near you",
    "all locations",
]

# URL path keywords used when filtering sitemap entries
LOCATION_URL_KEYWORDS = [
    "location",
    "clinic",
    "office",
    "branch",
    "store",
    "find-us",
    "contact",
    "visit",
]

MAX_PAGES = 10
REQUEST_TIMEOUT = 10       # seconds per single HTTP request
PROBE_STOP_AT = 3          # stop probing once this many valid paths are found
MAX_PROBE_ATTEMPTS = 5     # never try more than this many paths total (keeps us under 30s)
MAX_REDIRECTS = 3          # EC3 – follow at most this many redirects per request
JS_BODY_THRESHOLD = 500    # EC1 – body text below this → flag as JS-rendered

# EC4 – valid domain regex: one-or-more labels + TLD (alpha only, 2+ chars)
DOMAIN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_headers(exclude_ua: str = "") -> dict:
    """
    Return BASE_HEADERS with a randomly chosen User-Agent.

    *exclude_ua* is the UA used in the previous attempt; we pick a
    different one so retries rotate the agent (skills.md Skill 3).
    """
    options = [ua for ua in USER_AGENTS if ua != exclude_ua] or USER_AGENTS
    headers = BASE_HEADERS.copy()
    headers["User-Agent"] = random.choice(options)
    return headers


def _base_url(url: str) -> str:
    """Return scheme + netloc (e.g. 'https://example.com')."""
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _same_domain(url: str, base: str) -> bool:
    """Return True if *url* belongs to the same domain as *base*."""
    p_url = urlparse(url)
    p_base = urlparse(base)
    return not p_url.netloc or p_url.netloc == p_base.netloc


def _normalise_url(url: str) -> str:
    """Strip trailing slash so deduplication is reliable."""
    return url.rstrip("/")


# ---------------------------------------------------------------------------
# EC4 – URL validation
# ---------------------------------------------------------------------------

def validate_and_normalise_url(url: str) -> tuple:
    """
    Validate and normalise a raw URL string.

    Steps:
      1. Strip whitespace.
      2. Add 'https://' if no scheme is present.
      3. Strip trailing slashes from the path.
      4. Check that the domain matches DOMAIN_RE.

    Returns:
        (normalised_url: str, error: str | None)
        error is None on success; a descriptive string on failure.
    """
    url = url.strip()
    if not url:
        return "", "URL is empty"

    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Parse
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return "", f"Malformed URL: {url!r}"

    netloc = parsed.netloc.lower()
    if not netloc:
        return "", f"URL has no domain: {url!r}"

    # Reconstruct with trailing slash stripped from path (preserve query/fragment)
    path = parsed.path.rstrip("/")
    clean = parsed._replace(netloc=netloc, path=path).geturl()

    # Validate domain (strip port if present)
    host = netloc.split(":")[0]
    if not DOMAIN_RE.match(host):
        return "", f"Invalid domain: {host!r}"

    return clean, None


# ---------------------------------------------------------------------------
# EC1 – JS-rendered detection
# ---------------------------------------------------------------------------

def is_js_only(html: str | None) -> bool:
    """
    Return True when the page body has fewer than JS_BODY_THRESHOLD visible
    characters yet contains <script> tags — the hallmark of a JS-rendered SPA
    with no meaningful static content (EC1, threshold = 500 chars).
    """
    if not html:
        return True
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("body")
    target = body if body else soup
    text = target.get_text(strip=True)
    return len(text) < JS_BODY_THRESHOLD and bool(soup.find("script"))


# ---------------------------------------------------------------------------
# EC2 / EC3 – Fetch with retry, UA rotation, redirect cap
# ---------------------------------------------------------------------------

def fetch_page(url: str, _retried: bool = False, _prev_ua: str = "") -> tuple:
    """
    Fetch a single URL and return (html, status_code, error).

    EC2 – Blocked sites:
      • 401, 403 → return error="blocked" immediately (skills.md Skill 3).
      • 503      → retry once with a different User-Agent (2-second wait);
                   return error="blocked" if still 503 after retry.
      • 429      → wait 5 s then retry once (skills.md Skill 3).

    EC3 – Redirects:
      • Follows at most MAX_REDIRECTS hops (raises TooManyRedirects beyond).
      • If the final URL is on a different domain, returns error="cross_domain_redirect".

    Never raises; always returns a 3-tuple:
        (html: str | None, status: int | None, error: str | None)
    """
    headers = _get_headers(exclude_ua=_prev_ua)
    current_ua = headers["User-Agent"]
    original_netloc = urlparse(url).netloc.lower()

    try:
        with requests.Session() as sess:
            sess.max_redirects = MAX_REDIRECTS
            resp = sess.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )

        # EC3 – cross-domain redirect
        final_netloc = urlparse(resp.url).netloc.lower()
        if final_netloc and final_netloc != original_netloc:
            return None, None, "cross_domain_redirect"

        # EC2 – rate-limited: wait 5 s then retry once
        if resp.status_code == 429 and not _retried:
            time.sleep(5)
            return fetch_page(url, _retried=True, _prev_ua=current_ua)

        # EC2 – hard-blocked: stop immediately
        if resp.status_code in (401, 403):
            return None, resp.status_code, "blocked"

        # EC2 – 503: retry once with a different UA
        if resp.status_code == 503 and not _retried:
            time.sleep(2)
            return fetch_page(url, _retried=True, _prev_ua=current_ua)

        if resp.status_code == 503:
            return None, 503, "blocked"

        if resp.status_code == 404:
            return None, 404, "not_found"

        if resp.status_code >= 400:
            return None, resp.status_code, f"http_{resp.status_code}"

        return resp.text, resp.status_code, None

    except requests.exceptions.TooManyRedirects:
        return None, None, "too_many_redirects"
    except requests.exceptions.Timeout:
        return None, None, "timeout"
    except requests.exceptions.ConnectionError:
        return None, None, "connection_error"
    except Exception as exc:  # noqa: BLE001
        return None, None, str(exc)


# ---------------------------------------------------------------------------
# Remaining public helpers (unchanged from Phase 1)
# ---------------------------------------------------------------------------

def is_robots_allowed(url: str) -> bool:
    """
    Check whether *url* is permitted by the site's robots.txt.

    Returns True (allow) if robots.txt cannot be fetched or parsed.
    """
    base = _base_url(url)
    robots_url = f"{base}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
        return rp.can_fetch("*", url)
    except Exception:  # noqa: BLE001
        return True


def fetch_sitemap(base: str) -> list:
    """
    Fetch /sitemap.xml and return <loc> entries that contain a
    location-related keyword in their path (skills.md Skill 1).

    Returns:
        list[str]: Absolute URLs from the sitemap, possibly empty.
    """
    sitemap_url = f"{base}/sitemap.xml"
    html, status, error = fetch_page(sitemap_url)
    if error or not html:
        return []

    try:
        soup = BeautifulSoup(html, "lxml-xml")
        locs = [tag.get_text(strip=True) for tag in soup.find_all("loc")]
        return [
            loc for loc in locs
            if any(kw in urlparse(loc).path.lower() for kw in LOCATION_URL_KEYWORDS)
        ]
    except Exception:  # noqa: BLE001
        return []


def find_location_links(html: str, base: str) -> list:
    """
    Scan all <a> tags in *html* for link text matching LOCATION_LINK_TEXTS
    (skills.md Skill 1 — Nav/Footer Link Text Matching).

    Returns:
        list[str]: Absolute, same-domain URLs (deduped), possibly empty.
    """
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "html.parser")
        seen: set = set()
        found: list = []
        for a in soup.find_all("a", href=True):
            text = a.get_text(separator=" ", strip=True).lower()
            if any(pattern in text for pattern in LOCATION_LINK_TEXTS):
                full = urljoin(base, a["href"])
                key = _normalise_url(full)
                if key not in seen and _same_domain(full, base):
                    seen.add(key)
                    found.append(full)
        return found
    except Exception:  # noqa: BLE001
        return []


def probe_common_paths(base: str, already_found: set) -> list:
    """
    Try LOCATION_PATHS by appending each to *base* and checking for a 200
    response.  Stops early once PROBE_STOP_AT valid paths are found or
    MAX_PROBE_ATTEMPTS paths have been tried.

    Returns:
        list[str]: Accessible location URLs, possibly empty.
    """
    found: list = []
    attempts = 0
    for path in LOCATION_PATHS:
        if len(found) >= PROBE_STOP_AT or attempts >= MAX_PROBE_ATTEMPTS:
            break
        attempts += 1
        url = base + path
        if _normalise_url(url) in already_found:
            continue
        html, status, error = fetch_page(url)
        time.sleep(random.uniform(1, 2))
        if status == 200 and html:
            found.append(url)
    return found


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def crawl(url: str) -> dict:
    """
    Crawl a website and return a prioritised list of page URLs likely to
    contain location/address data.  Follows the priority order in CLAUDE.md
    and skills.md Skill 1.

    EC4: URL is validated and normalised before any network activity.

    Args:
        url: The website's root URL (scheme optional; https assumed if absent).

    Returns:
        dict with keys:
            pages         (list[str])  – URLs to extract from, max 10.
            homepage_html (str|None)   – Cached HTML of the homepage.
            error         (str|None)   – Human-readable error description.
            error_type    (str|None)   – One of: "blocked", "unreachable",
                                         "js_rendered", or None on success.
    """
    result: dict = {
        "pages": [],
        "homepage_html": None,
        "error": None,
        "error_type": None,
    }

    # EC4 – validate and normalise URL
    url, val_err = validate_and_normalise_url(url)
    if val_err:
        result["error"] = val_err
        result["error_type"] = "invalid_url"
        return result

    base = _base_url(url)

    # robots.txt check
    if not is_robots_allowed(url):
        result["error"] = "Blocked by robots.txt"
        result["error_type"] = "blocked"
        return result

    # Step 1: Fetch homepage
    homepage_html, status, error = fetch_page(url)

    if error == "blocked" or status in (401, 403):
        result["error"] = "Site returned 401/403 Forbidden"
        result["error_type"] = "blocked"
        return result

    if error in ("timeout", "connection_error", "cross_domain_redirect", "too_many_redirects") \
            or homepage_html is None:
        result["error"] = f"Could not reach site: {error}"
        result["error_type"] = "unreachable"
        return result

    # EC1 – JS-rendered check (500-char threshold)
    if is_js_only(homepage_html):
        result["error"] = "Site appears to require JavaScript rendering"
        result["error_type"] = "js_rendered"
        return result

    result["homepage_html"] = homepage_html

    seen: set = {_normalise_url(url), _normalise_url(base), _normalise_url(base + "/")}
    pages: list = [url]

    # Step 2: Sitemap
    time.sleep(random.uniform(1, 2))
    for u in fetch_sitemap(base):
        key = _normalise_url(u)
        if key not in seen and len(pages) < MAX_PAGES:
            seen.add(key)
            pages.append(u)

    # Step 3: Nav/footer location links on homepage
    for u in find_location_links(homepage_html, base):
        key = _normalise_url(u)
        if key not in seen and len(pages) < MAX_PAGES:
            seen.add(key)
            pages.append(u)

    # Step 4: Probe common paths as fallback (only if sparse)
    if len(pages) < 3:
        for u in probe_common_paths(base, seen):
            key = _normalise_url(u)
            if key not in seen and len(pages) < MAX_PAGES:
                seen.add(key)
                pages.append(u)

    result["pages"] = pages[:MAX_PAGES]
    return result