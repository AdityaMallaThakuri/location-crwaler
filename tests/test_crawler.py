"""
tests/test_crawler.py

Full test suite for the MedSpa Location Crawler API.

Covers all 8 test cases from skills.md Skill 5, plus API contract and
edge-case tests.  All unit tests use 'responses' to mock HTTP — no real
network calls.

Run unit tests only:   pytest tests/test_crawler.py -m "not integration"
Run all (incl. live):  pytest tests/test_crawler.py
"""

import json
import time

import pytest
import requests
import responses as rsps
from unittest.mock import patch

from app.main import create_app

# ---------------------------------------------------------------------------
# Constants shared across tests
# ---------------------------------------------------------------------------

BASE = "https://medspa-test.example.com"

VALID_CONFIDENCES = frozenset({
    "high", "medium", "low",
    "blocked", "unreachable", "js_rendered",
})

# Enough text to make the page body > 500 chars (threshold for is_js_only).
_PAD = (
    "Welcome to our premier medical spa offering world-class aesthetic "
    "treatments delivered by board-certified professionals. "
) * 6  # ~330 chars × 6 → > 500

# ---------------------------------------------------------------------------
# HTML fixtures used across tests
# ---------------------------------------------------------------------------

TWO_ADDRS = """
<div class="location-card">
  <p>123 Main St, Miami, FL 33101</p>
  <p>(305) 555-0001</p>
</div>
<div class="location-card">
  <p>456 Ocean Blvd, Fort Lauderdale, FL 33301</p>
  <p>(954) 555-0002</p>
</div>
"""

FIVE_ADDRS = TWO_ADDRS + """
<div class="location-card">
  <p>789 Brickell Ave, Miami, FL 33131</p>
  <p>(305) 555-0003</p>
</div>
<div class="location-card">
  <p>321 Palm Dr, Boca Raton, FL 33432</p>
  <p>(561) 555-0004</p>
</div>
<div class="location-card">
  <p>654 Sunset Way, Hollywood, FL 33021</p>
  <p>(954) 555-0005</p>
</div>
"""

ONE_ADDR = "<p>100 Pine St, Suite 200, Naples, FL 34102</p>"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    return create_app()


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def _fast_patches(request):
    """
    Applied to every non-integration test:
      • Suppress all time.sleep() calls so tests finish instantly.
      • Stub is_robots_allowed() — it uses urllib (not requests), which the
        'responses' library does not intercept.
    """
    if request.node.get_closest_marker("integration"):
        yield
        return
    with (
        patch("app.crawler.time.sleep"),
        patch("app.api.time.sleep"),
        patch("app.crawler.is_robots_allowed", return_value=True),
    ):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _post(client, url=BASE, company="Test Spa"):
    """POST /extract-locations and return (response, parsed_json, elapsed_s)."""
    t0 = time.time()
    rv = client.post(
        "/extract-locations",
        data=json.dumps({"website_url": url, "company_name": company}),
        content_type="application/json",
    )
    return rv, rv.get_json(), time.time() - t0


def _assert_shape(data: dict, elapsed: float):
    """
    Universal assertions that EVERY response must satisfy
    (skills.md Skill 5 — 'What to Assert').
    """
    assert isinstance(data.get("success"), bool), \
        f"'success' must be bool, got {type(data.get('success'))}"

    assert "location_count" in data, \
        "'location_count' key must always be present"
    assert (
        data["location_count"] is None
        or isinstance(data["location_count"], int)
    ), f"'location_count' must be int or null, got {data['location_count']!r}"

    assert data.get("confidence") in VALID_CONFIDENCES, \
        f"'confidence' {data.get('confidence')!r} not in {VALID_CONFIDENCES}"

    assert isinstance(data.get("locations_found"), list), \
        f"'locations_found' must be list, got {type(data.get('locations_found'))}"

    assert elapsed < 30, \
        f"Response took {elapsed:.2f}s — limit is 30s"


def _page(nav="", body="", footer="", js_only=False):
    """Build minimal valid HTML for mocking."""
    pad = "" if js_only else _PAD
    script = "<script>window.__APP__={}</script>" if js_only else ""
    return (
        "<!DOCTYPE html><html><head><title>Test Spa</title></head>\n"
        "<body>\n"
        f"<nav><a href='/'>Home</a>{nav}</nav>\n"
        f"<main>{pad}{body}</main>\n"
        f"<footer>{footer}</footer>\n"
        f"{script}\n"
        "</body></html>"
    )


# ===========================================================================
# 8 SKILL-5 TEST CASES
# ===========================================================================

# ── Case 1 ──────────────────────────────────────────────────────────────────

@rsps.activate
def test_case1_dedicated_locations_page(client):
    """Skill 5 case 1: site with dedicated /locations page → high confidence."""
    rsps.add(rsps.GET, BASE,
             body=_page(nav='<a href="/locations">Our Locations</a>'),
             status=200)
    rsps.add(rsps.GET, f"{BASE}/locations",
             body=_page(body=TWO_ADDRS),
             status=200)

    rv, data, elapsed = _post(client)

    assert rv.status_code == 200
    _assert_shape(data, elapsed)
    assert data["success"] is True
    assert data["confidence"] == "high"
    assert isinstance(data["location_count"], int)
    assert data["location_count"] >= 2
    assert len(data["locations_found"]) >= 2
    assert data["detection_method"] == "location_page"


# ── Case 2 ──────────────────────────────────────────────────────────────────

@rsps.activate
def test_case2_footer_addresses_medium(client):
    """Skill 5 case 2: footer with 1 address + city list → medium confidence."""
    rsps.add(rsps.GET, BASE,
             body=_page(body=ONE_ADDR,
                        footer="Miami | Fort Lauderdale | Boca Raton"),
             status=200)

    rv, data, elapsed = _post(client)

    assert rv.status_code == 200
    _assert_shape(data, elapsed)
    assert data["success"] is True
    assert data["confidence"] == "medium"
    assert data["location_count"] >= 1


# ── Case 3 ──────────────────────────────────────────────────────────────────

@rsps.activate
def test_case3_js_rendered(client):
    """Skill 5 case 3: JS SPA with < 500 chars visible body → js_rendered."""
    rsps.add(rsps.GET, BASE, body=_page(js_only=True), status=200)

    rv, data, elapsed = _post(client)

    assert rv.status_code == 200
    _assert_shape(data, elapsed)
    assert data["success"] is False
    assert data["confidence"] == "js_rendered"
    assert data["location_count"] is None
    assert data["locations_found"] == []


# ── Case 4 ──────────────────────────────────────────────────────────────────

@rsps.activate
def test_case4_blocked_403(client):
    """Skill 5 case 4: site returns 403 → confidence='blocked'."""
    rsps.add(rsps.GET, BASE, status=403)

    rv, data, elapsed = _post(client)

    assert rv.status_code == 200
    _assert_shape(data, elapsed)
    assert data["success"] is False
    assert data["confidence"] == "blocked"
    assert data["location_count"] is None
    assert data["locations_found"] == []


# ── Case 5 ──────────────────────────────────────────────────────────────────

@rsps.activate
def test_case5_single_location_low(client):
    """Skill 5 case 5: one address, no other signals → count=1, low confidence."""
    rsps.add(rsps.GET, BASE, body=_page(body=ONE_ADDR), status=200)

    rv, data, elapsed = _post(client)

    assert rv.status_code == 200
    _assert_shape(data, elapsed)
    assert data["success"] is True
    assert data["confidence"] == "low"
    assert data["location_count"] == 1
    # locations_found should contain the address we extracted
    assert isinstance(data["locations_found"], list)


# ── Case 6 ──────────────────────────────────────────────────────────────────

@rsps.activate
def test_case6_five_plus_locations(client):
    """Skill 5 case 6: /locations page with 5 addresses → high, count >= 5."""
    rsps.add(rsps.GET, BASE,
             body=_page(nav='<a href="/locations">Find a Location</a>'),
             status=200)
    rsps.add(rsps.GET, f"{BASE}/locations",
             body=_page(body=FIVE_ADDRS),
             status=200)

    rv, data, elapsed = _post(client)

    assert rv.status_code == 200
    _assert_shape(data, elapsed)
    assert data["success"] is True
    assert data["confidence"] == "high"
    assert isinstance(data["location_count"], int)
    assert data["location_count"] >= 5
    assert len(data["locations_found"]) >= 5


# ── Case 7 ──────────────────────────────────────────────────────────────────

@rsps.activate
def test_case7_timeout_unreachable(client):
    """Skill 5 case 7: connection error on homepage → confidence='unreachable'."""
    rsps.add(rsps.GET, BASE,
             body=requests.exceptions.ConnectionError("Connection timed out"))

    rv, data, elapsed = _post(client)

    assert rv.status_code == 200
    _assert_shape(data, elapsed)
    assert data["success"] is False
    assert data["confidence"] == "unreachable"
    assert data["location_count"] is None


# ── Case 8 ──────────────────────────────────────────────────────────────────

def test_case8_invalid_url(client):
    """Skill 5 case 8: non-domain URL string → validation error in body."""
    rv, data, elapsed = _post(client, url="notavalidurl")

    assert rv.status_code == 200
    _assert_shape(data, elapsed)
    assert data["success"] is False
    assert data["error"] is not None
    assert data["location_count"] is None


# ===========================================================================
# API CONTRACT TESTS (HTTP shape guarantees)
# ===========================================================================

def test_http_status_always_200_on_error(client):
    """HTTP status is always 200 even on validation errors (Clay requirement)."""
    rv, data, _ = _post(client, url="notavalidurl")
    assert rv.status_code == 200


def test_missing_website_url(client):
    """Omitting website_url → HTTP 200 + success=False + descriptive error."""
    rv = client.post(
        "/extract-locations",
        data=json.dumps({"company_name": "Test"}),
        content_type="application/json",
    )
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["success"] is False
    assert "website_url" in (data.get("error") or "")
    assert isinstance(data["locations_found"], list)


def test_missing_company_name(client):
    """Omitting company_name → HTTP 200 + success=False."""
    rv = client.post(
        "/extract-locations",
        data=json.dumps({"website_url": "https://example.com"}),
        content_type="application/json",
    )
    assert rv.status_code == 200
    assert rv.get_json()["success"] is False


def test_empty_json_body(client):
    """Empty JSON object → HTTP 200 + success=False."""
    rv = client.post(
        "/extract-locations",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert rv.status_code == 200
    assert rv.get_json()["success"] is False


def test_non_json_body(client):
    """Non-JSON body → HTTP 200 + success=False (never crashes)."""
    rv = client.post("/extract-locations", data="not json", content_type="text/plain")
    assert rv.status_code == 200
    assert rv.get_json()["success"] is False


def test_health_endpoint(client):
    """GET /health → {"status": "ok", "version": "1.0.0"}."""
    rv = client.get("/health")
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["status"] == "ok"
    assert data["version"] == "1.0.0"


def test_wrong_http_method_returns_json(client):
    """GET on /extract-locations → 405 with JSON body (not Flask HTML)."""
    rv = client.get("/extract-locations")
    assert rv.status_code == 405
    assert rv.get_json() is not None


def test_unknown_route_returns_json(client):
    """Unknown route → 404 with JSON body (never HTML)."""
    rv = client.get("/this-does-not-exist")
    assert rv.status_code == 404
    assert rv.get_json() is not None


# ===========================================================================
# EDGE CASE COVERAGE (Phase 3 hardening)
# ===========================================================================

@rsps.activate
def test_ec2_blocked_401(client):
    """EC2: 401 Unauthorized is treated the same as 403 → blocked."""
    rsps.add(rsps.GET, BASE, status=401)

    rv, data, elapsed = _post(client)
    _assert_shape(data, elapsed)
    assert data["success"] is False
    assert data["confidence"] == "blocked"
    assert data["location_count"] is None


@rsps.activate
def test_ec6_dash_separator_city_list(client):
    """EC6: 'Serving Miami - Boca Raton - Fort Lauderdale' → medium confidence."""
    rsps.add(rsps.GET, BASE,
             body=_page(footer="Serving Miami - Boca Raton - Fort Lauderdale"),
             status=200)

    rv, data, elapsed = _post(client)
    _assert_shape(data, elapsed)
    assert data["success"] is True
    # 3 city mentions with no addresses → medium (EC6 rule)
    assert data["confidence"] == "medium"


@rsps.activate
def test_ec4_url_normalised_no_scheme(client):
    """EC4: URL without scheme is auto-prefixed with https://."""
    rsps.add(rsps.GET, BASE, body=_page(body=ONE_ADDR), status=200)

    # POST without scheme — the API should normalise it
    rv, data, elapsed = _post(client, url="medspa-test.example.com")
    _assert_shape(data, elapsed)
    # Should succeed (normalised to https://medspa-test.example.com)
    assert data["success"] is True


@rsps.activate
def test_response_locations_found_is_list_even_on_failure(client):
    """locations_found is always a list, never null — including on 403."""
    rsps.add(rsps.GET, BASE, status=403)

    rv, data, elapsed = _post(client)
    assert isinstance(data["locations_found"], list)


@rsps.activate
def test_response_under_10kb(client):
    """Response payload is under 10 KB (Clay hard limit)."""
    rsps.add(rsps.GET, BASE, body=_page(body=FIVE_ADDRS), status=200)

    rv, data, elapsed = _post(client)
    assert len(rv.data) < 10_240, \
        f"Response is {len(rv.data)} bytes — Clay limit is 10 KB"


# ===========================================================================
# INTEGRATION TEST (real network — skipped by default)
# ===========================================================================

@pytest.mark.integration
def test_integration_httpbin(client):
    """
    Live end-to-end test against httpbin.org — a stable, public endpoint.
    Run with:  pytest tests/test_crawler.py -m integration
    """
    rv, data, elapsed = _post(client, url="https://httpbin.org", company="httpbin")

    assert rv.status_code == 200
    _assert_shape(data, elapsed)

    # httpbin.org is reachable — must not time out or be blocked by firewall
    assert data["confidence"] != "unreachable", \
        "httpbin.org should be reachable from this network"
    # No addresses expected → count is 1 (CLAUDE.md default) or null on edge cases
    assert data["location_count"] is None or data["location_count"] >= 1
