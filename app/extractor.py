"""
extractor.py - Address and location data extractor for med spa websites.

Accepts a page URL + its HTML content and returns a structured dict with
addresses found, phone count, location card count, and a confidence score.
Includes helpers to deduplicate addresses across multiple pages and to pick
the best result from a list.

Patterns sourced from skills.md Skill 2.

Edge cases handled (Phase 3):
  EC5  Address deduplication – abbreviation expansion + punctuation stripping
  EC6  Footer city list      – dash separator ( - ) and service-prefix stripping
"""

import re
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Compiled regex patterns (skills.md Skill 2)
# ---------------------------------------------------------------------------

ADDRESS_RE = re.compile(
    # Street number: must NOT be preceded by a digit or dash (prevents
    # matching the tail of a phone number like 555-1234).
    r"(?<!\d)(?<!-)\b\d{1,5}[ \t]+"
    # Street name: spaces/tabs only — no newlines — to avoid cross-line greed.
    r"[A-Za-z0-9][A-Za-z0-9 \t,\.]*?"
    # Street type suffix
    r"(?:Ave(?:nue)?|St(?:reet)?|Rd|Road|Blvd|Boulevard"
    r"|Dr(?:ive)?|Ln|Way|Ct|Pl|Pkwy|Hwy|Suite|Ste)"
    r"\.?"
    # Remainder of address on the same line (city, optional unit)
    r"[^\n\r]*"
    # State abbreviation + zip
    r",[ \t]*[A-Z]{2}[ \t]*\d{5}",
    re.IGNORECASE,
)

PHONE_RE = re.compile(r"\(?\d{3}\)?[\s\-]\d{3}[\s\-]\d{4}")

# EC6 – city-list separators: pipe, slash, bullet, OR space-dash-space ( - )
# The space requirement on both sides of the dash prevents matching hyphens
# inside compound words (e.g. "North-Miami").
CITY_SEP_RE = re.compile(r"[|/•]|\s+-\s+")

# EC6 – strip common service phrases from the start of a line before splitting
# so "Serving Miami - Boca Raton" yields ["Miami", "Boca Raton"].
_SERVICE_PREFIX_RE = re.compile(
    r"^(?:serving|locations?\s+in|clinics?\s+in|offices?\s+in|"
    r"visit\s+us\s+in|available\s+in|near|we\s+serve|now\s+in|open\s+in)"
    r"\s*:?\s*",
    re.IGNORECASE,
)

# Location card CSS class keywords (skills.md Skill 2)
LOCATION_CARD_CLASSES = [
    "location-card",
    "location",
    "clinic",
    "office",
    "branch",
    "store",
    "address",
    "contact-info",
    "find-us",
]

# ---------------------------------------------------------------------------
# EC5 – Address abbreviation expansion table
# ---------------------------------------------------------------------------

# Each entry: (compiled_pattern, replacement_string)
# Patterns use \b word boundaries so "St" doesn't expand inside "Street".
_ADDR_ABBREVS: list = [
    (re.compile(r"\bst\.?\b",   re.IGNORECASE), "street"),
    (re.compile(r"\bave\.?\b",  re.IGNORECASE), "avenue"),
    (re.compile(r"\bblvd\.?\b", re.IGNORECASE), "boulevard"),
    (re.compile(r"\bdr\.?\b",   re.IGNORECASE), "drive"),
    (re.compile(r"\bln\.?\b",   re.IGNORECASE), "lane"),
    (re.compile(r"\brd\.?\b",   re.IGNORECASE), "road"),
    (re.compile(r"\bct\.?\b",   re.IGNORECASE), "court"),
    (re.compile(r"\bpl\.?\b",   re.IGNORECASE), "place"),
    (re.compile(r"\bpkwy\.?\b", re.IGNORECASE), "parkway"),
    (re.compile(r"\bhwy\.?\b",  re.IGNORECASE), "highway"),
    (re.compile(r"\bste\.?\b",  re.IGNORECASE), "suite"),
    (re.compile(r"\bapt\.?\b",  re.IGNORECASE), "apartment"),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise_address(address: str) -> str:
    """
    Normalise an address string for deduplication (EC5).

    Steps:
      1. Lowercase.
      2. Strip punctuation (, . # ( ) ) — preserves hyphens for compound names.
      3. Expand common abbreviations (St→street, Ave→avenue, etc.).
      4. Collapse runs of whitespace.

    This means "123 Main St, Miami, FL 33101" and
    "123 Main Street Miami FL 33101" hash to the same key.
    """
    addr = address.strip().lower()
    addr = re.sub(r"[,\.#\(\)]", " ", addr)
    for pattern, replacement in _ADDR_ABBREVS:
        addr = pattern.sub(replacement, addr)
    return re.sub(r"\s+", " ", addr).strip()


def _clean_soup(html: str) -> BeautifulSoup:
    """Parse HTML and strip <script>/<style> tags so regex doesn't hit JS."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup


# ---------------------------------------------------------------------------
# Extraction functions
# ---------------------------------------------------------------------------

def extract_addresses(html: str) -> list:
    """
    Extract US street addresses from *html* using ADDRESS_RE.

    Strips script/style content before matching to avoid false positives
    from minified JS.  Deduplicates via _normalise_address (EC5).

    Returns:
        list[str]: Unique address strings, possibly empty.
    """
    if not html:
        return []
    try:
        soup = _clean_soup(html)
        text = soup.get_text(separator=" ")
        matches = ADDRESS_RE.findall(text)

        seen: set = set()
        unique: list = []
        for addr in matches:
            key = _normalise_address(addr)
            if key not in seen:
                seen.add(key)
                unique.append(addr.strip())
        return unique
    except Exception:  # noqa: BLE001
        return []


def count_phones(html: str) -> int:
    """
    Count unique phone numbers in *html*.

    Each unique number is a secondary signal for one location
    (skills.md Skill 2).

    Returns:
        int: Number of distinct phone numbers found.
    """
    if not html:
        return 0
    try:
        soup = _clean_soup(html)
        text = soup.get_text(separator=" ")
        raw_phones = PHONE_RE.findall(text)
        normalised = {re.sub(r"\D", "", p) for p in raw_phones}
        return len(normalised)
    except Exception:  # noqa: BLE001
        return 0


def detect_location_cards(html: str) -> int:
    """
    Count repeating HTML elements whose CSS class list contains one of the
    LOCATION_CARD_CLASSES keywords (skills.md Skill 2).

    Returns the maximum count across all watched keywords to avoid
    double-counting when a site uses multiple matching class names on the
    same element.

    Returns:
        int: Highest element count found for any single keyword, or 0.
    """
    if not html:
        return 0
    try:
        soup = BeautifulSoup(html, "html.parser")
        max_count = 0
        for class_kw in LOCATION_CARD_CLASSES:
            elements = soup.find_all(
                lambda tag, kw=class_kw: tag.get("class") and any(
                    kw in c.lower() for c in tag.get("class", [])
                )
            )
            if len(elements) > max_count:
                max_count = len(elements)
        return max_count
    except Exception:  # noqa: BLE001
        return 0


def extract_city_mentions(html: str) -> list:
    """
    Extract city tokens from separator-delimited lists found in footers / navs.

    Supported separators (EC6 adds dash):
      |   /   •   and   ' - '  (space-dash-space)

    EC6 – service prefix stripping:
      Lines starting with "Serving", "Locations in", etc. have that prefix
      removed before splitting so that "Serving Miami - Boca Raton" yields
      ["Miami", "Boca Raton"].

    Only tokens 2–35 characters long with no digits are kept as city names.

    Returns:
        list[str]: Unique city name strings, possibly empty.
    """
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Focus on footer and nav where city lists normally appear
        search_areas: list = []
        for selector in ("footer", "nav", "[class*='footer']", "[class*='nav']"):
            el = soup.select_one(selector)
            if el:
                search_areas.append(el.get_text(separator="\n"))
        if not search_areas:
            search_areas.append(soup.get_text(separator="\n"))

        cities: list = []
        seen: set = set()

        for block in search_areas:
            for line in block.splitlines():
                # EC6 – strip service prefix before checking for separators
                stripped = _SERVICE_PREFIX_RE.sub("", line.strip())

                if not CITY_SEP_RE.search(stripped):
                    continue

                for token in CITY_SEP_RE.split(stripped):
                    token = token.strip()
                    if token and 2 <= len(token) <= 35 and not re.search(r"\d", token):
                        key = token.lower()
                        if key not in seen:
                            seen.add(key)
                            cities.append(token)

        return cities
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------------------
# Confidence scoring (skills.md Skill 2 + CLAUDE.md)
# ---------------------------------------------------------------------------

def calculate_confidence(
    addresses: list,
    phones: int,
    cards: int,
    cities: list,
) -> str:
    """
    Derive a confidence label from extraction signals.

    Rules (in priority order, skills.md Skill 2):
        2+ full addresses               → high
        1 address + multiple cities     → medium
        1 address + multiple phones     → medium
        0 addresses + multiple phones   → medium
        2+ location cards detected      → medium
        everything else                 → low

    Returns:
        str: "high", "medium", or "low"
    """
    addr_count = len(addresses)

    if addr_count >= 2:
        return "high"

    if addr_count == 1 and len(cities) > 1:
        return "medium"

    if addr_count == 1 and phones > 1:
        return "medium"

    if addr_count == 0 and phones > 1:
        return "medium"

    # EC6 – multiple city mentions in footer/nav is a location signal on its own
    # (CLAUDE.md: "medium: nav mentions of multiple cities")
    if addr_count == 0 and len(cities) > 1:
        return "medium"

    if cards >= 2:
        return "medium"

    return "low"


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def extract_locations(url: str, html: str) -> dict:
    """
    Main extraction entrypoint.  Accepts a page URL and its HTML, runs all
    extraction functions, and returns a structured result dict.

    Args:
        url:  The page URL (used as source label only; no HTTP request made).
        html: Raw HTML string of the page.

    Returns:
        dict with keys:
            addresses  (list[str])  – Street addresses found.
            phones     (int)        – Count of unique phone numbers.
            cards      (int)        – Count of repeating location card elements.
            cities     (list[str])  – City tokens from separator lists.
            confidence (str)        – "high" / "medium" / "low".
            source_url (str)        – The *url* argument, echoed back.
            error      (str|None)   – Set only if an exception occurred.
    """
    empty: dict = {
        "addresses": [],
        "phones": 0,
        "cards": 0,
        "cities": [],
        "confidence": "low",
        "source_url": url,
        "error": None,
    }

    if not html:
        return empty

    try:
        addresses = extract_addresses(html)
        phones = count_phones(html)
        cards = detect_location_cards(html)
        cities = extract_city_mentions(html)
        confidence = calculate_confidence(addresses, phones, cards, cities)

        return {
            "addresses": addresses,
            "phones": phones,
            "cards": cards,
            "cities": cities,
            "confidence": confidence,
            "source_url": url,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {**empty, "error": str(exc)}


def deduplicate_addresses(results: list) -> list:
    """
    Merge and deduplicate addresses across a list of extract_locations() dicts.

    Uses _normalise_address (EC5) as the dedup key so that abbreviated and
    fully-spelled variants of the same address are treated as one entry.

    Args:
        results: list of dicts returned by extract_locations().

    Returns:
        list[str]: Unique addresses in first-seen order across all pages.
    """
    seen: set = set()
    unique: list = []
    for result in results:
        for addr in result.get("addresses", []):
            key = _normalise_address(addr)
            if key not in seen:
                seen.add(key)
                unique.append(addr)
    return unique


def pick_best_result(results: list) -> dict:
    """
    Select the single best extraction result from a list of page results.

    Ranking criteria (descending priority):
        1. confidence rank  (high=3, medium=2, low=1)
        2. address count
        3. phone count
        4. card count

    Args:
        results: list of dicts returned by extract_locations().

    Returns:
        dict: The highest-ranked result, or a blank result dict if *results*
              is empty.
    """
    if not results:
        return {
            "addresses": [],
            "phones": 0,
            "cards": 0,
            "cities": [],
            "confidence": "low",
            "source_url": "",
            "error": None,
        }

    rank = {"high": 3, "medium": 2, "low": 1}

    return max(
        results,
        key=lambda r: (
            rank.get(r.get("confidence", "low"), 0),
            len(r.get("addresses", [])),
            r.get("phones", 0),
            r.get("cards", 0),
        ),
    )
