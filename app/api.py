"""
api.py - Flask blueprint for the /extract-locations endpoint.

Orchestrates crawler → extractor → response assembly.  Always returns HTTP
200 with a structured JSON body; success/failure is signalled inside the body.
Rate limiting: max 10 concurrent, queue up to 50, 429 beyond that.
Timeout: 30 seconds for the full crawl + extract pipeline.
"""

import concurrent.futures
import logging
import random
import threading
import time
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

from app.crawler import crawl, fetch_page
from app.extractor import deduplicate_addresses, extract_locations, pick_best_result

logger = logging.getLogger(__name__)
bp = Blueprint("api", __name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CRAWL_TIMEOUT = 30  # seconds — must respond before Clay times out

# ---------------------------------------------------------------------------
# Rate limiting (skills.md Skill 4)
# ---------------------------------------------------------------------------

_semaphore = threading.Semaphore(10)   # max concurrent active requests
_in_flight = 0                          # waiting + active
_in_flight_lock = threading.Lock()
_MAX_IN_FLIGHT = 60                     # 10 active + 50 queued = 60 total


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------

def _ok(location_count, confidence, source_page, locations_found, detection_method):
    """Build a successful response dict in the exact shape from CLAUDE.md."""
    return {
        "success": True,
        "location_count": location_count,
        "confidence": confidence,
        "source_page": source_page,
        "locations_found": locations_found,
        "detection_method": detection_method,
        "error": None,
    }


def _fail(confidence, error_msg, location_count=None):
    """Build a failure response dict in the exact shape from CLAUDE.md."""
    return {
        "success": False,
        "location_count": location_count,
        "confidence": confidence,
        "source_page": None,
        "locations_found": [],
        "detection_method": None,
        "error": error_msg,
    }


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

# URL path keywords that indicate a dedicated location/clinic page
_LOCATION_PATH_KWS = {
    "location", "clinic", "office", "branch", "store",
    "find-us", "find-a-location", "visit-us", "branches", "stores",
}


def _infer_detection_method(source_url: str, base_url: str) -> str:
    """
    Map a source page URL to one of the four detection_method values
    defined in CLAUDE.md: location_page / footer / nav / subpages.
    """
    path = urlparse(source_url).path.lower().rstrip("/")
    base_path = urlparse(base_url).path.lower().rstrip("/")

    if any(kw in path for kw in _LOCATION_PATH_KWS):
        return "location_page"

    if "contact" in path:
        return "nav"

    if path in ("", "/") or path == base_path:
        return "footer"

    return "subpages"


def _estimate_count(all_addresses: list, best: dict) -> int:
    """
    Estimate total location count from extraction signals.

    Priority (CLAUDE.md): full addresses > location cards > phones > assume 1.
    """
    if all_addresses:
        return len(all_addresses)
    if best.get("cards", 0) >= 2:
        return best["cards"]
    if best.get("phones", 0) > 1:
        return best["phones"]
    # CLAUDE.md: "No addresses found → return location_count: 1"
    return 1


# ---------------------------------------------------------------------------
# Core pipeline (runs inside a worker thread for timeout enforcement)
# ---------------------------------------------------------------------------

def _run_pipeline(url: str) -> dict:
    """
    Full crawl → extract → assemble pipeline.

    Called inside a ThreadPoolExecutor so the Flask route can enforce the
    30-second wall-clock timeout via future.result(timeout=CRAWL_TIMEOUT).

    Returns a response dict (always the exact CLAUDE.md shape).
    """
    # --- Crawl ---
    crawl_result = crawl(url)

    error_type = crawl_result.get("error_type")
    if error_type == "blocked":
        return _fail("blocked", crawl_result["error"])
    if error_type == "unreachable":
        return _fail("unreachable", crawl_result["error"])
    if error_type == "js_rendered":
        return _fail("js_rendered", crawl_result["error"])
    if error_type == "invalid_url":
        return _fail("low", crawl_result["error"])

    pages = crawl_result["pages"]
    homepage_html = crawl_result["homepage_html"]

    # Normalise base URL for detection_method inference
    base_url = url if url.startswith(("http://", "https://")) else f"https://{url}"

    # --- Extract from each page ---
    page_results: list = []
    for i, page_url in enumerate(pages):
        if i == 0 and homepage_html:
            # Homepage already fetched by crawler — use cached HTML
            html = homepage_html
        else:
            time.sleep(random.uniform(1, 2))
            html, _status, _err = fetch_page(page_url)
            if not html:
                continue

        page_results.append(extract_locations(page_url, html))

    if not page_results:
        return _fail("low", "No pages could be fetched or extracted", location_count=1)

    # --- Assemble ---
    all_addresses = deduplicate_addresses(page_results)
    best = pick_best_result(page_results)
    count = _estimate_count(all_addresses, best)
    method = _infer_detection_method(best["source_url"], base_url)

    return _ok(count, best["confidence"], best["source_url"], all_addresses, method)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@bp.route("/extract-locations", methods=["POST"])
def extract_locations_route():
    """
    POST /extract-locations

    Body (JSON):
        website_url  (str, required)
        company_name (str, required)

    Always returns HTTP 200.  Check 'success' in the body for pass/fail.
    """
    global _in_flight
    start = time.time()
    website_url = ""
    company_name = ""

    # --- Rate limiting gate ---
    with _in_flight_lock:
        if _in_flight >= _MAX_IN_FLIGHT:
            logger.warning("rate limit hit: %d requests in flight", _in_flight)
            return (
                jsonify({"error": "Too many concurrent requests, try again shortly"}),
                429,
            )
        _in_flight += 1

    _semaphore.acquire()
    try:
        # --- Input validation ---
        body = request.get_json(silent=True) or {}
        website_url = (body.get("website_url") or "").strip()
        company_name = (body.get("company_name") or "").strip()

        if not website_url:
            return jsonify(_fail("low", "website_url is required")), 200

        if not company_name:
            return jsonify(_fail("low", "company_name is required")), 200

        # --- Run pipeline with hard 30-second timeout ---
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_run_pipeline, website_url)
                result = future.result(timeout=CRAWL_TIMEOUT)

        except concurrent.futures.TimeoutError:
            result = _fail(
                "unreachable",
                f"Crawl exceeded {CRAWL_TIMEOUT}s timeout",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("unhandled error crawling %s", website_url)
            result = _fail("low", f"Internal error: {exc}")

        elapsed = time.time() - start
        logger.info(
            "request done | company=%r url=%r success=%s confidence=%s "
            "count=%s elapsed=%.2fs",
            company_name,
            website_url,
            result.get("success"),
            result.get("confidence"),
            result.get("location_count"),
            elapsed,
        )

        return jsonify(result), 200

    finally:
        _semaphore.release()
        with _in_flight_lock:
            _in_flight -= 1
