"""
main.py - Flask application factory and production entry point.

Responsibilities:
  - Create and configure the Flask app
  - Register the /extract-locations blueprint (app/api.py)
  - Expose GET /health for Render uptime checks and Clay warmup pings
  - Add CORS headers to every response (required for Clay HTTP API columns)
  - Handle OPTIONS preflight requests
  - Expose module-level `app` for gunicorn (app.main:app)
  - Run on port 5000 in local development
"""

import logging

from flask import Flask, jsonify

from app.api import CRAWL_TIMEOUT, bp


def create_app() -> Flask:
    """
    Application factory.  Returns a fully configured Flask app.
    Used by the module-level `app` binding (gunicorn) and by tests.
    """
    application = Flask(__name__)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------
    application.config["JSON_SORT_KEYS"] = False
    application.config["CRAWL_TIMEOUT"] = CRAWL_TIMEOUT

    # ------------------------------------------------------------------
    # Blueprints
    # ------------------------------------------------------------------
    application.register_blueprint(bp)

    # ------------------------------------------------------------------
    # CORS — required for Clay HTTP API column (CLAUDE.md)
    # Applies to every response including errors.
    # ------------------------------------------------------------------
    @application.after_request
    def _add_cors(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    # OPTIONS preflight for /extract-locations
    @application.route("/extract-locations", methods=["OPTIONS"])
    def _cors_preflight():
        return "", 204

    # ------------------------------------------------------------------
    # Health check — used by Render monitoring + Clay warmup (skills.md Skill 4)
    # ------------------------------------------------------------------
    @application.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "version": "1.0.0"})

    # ------------------------------------------------------------------
    # JSON error handlers — Clay must never receive Flask's HTML error pages
    # ------------------------------------------------------------------
    @application.errorhandler(404)
    def not_found(_err):
        return jsonify({"error": "endpoint not found"}), 404

    @application.errorhandler(405)
    def method_not_allowed(_err):
        return jsonify({"error": "method not allowed"}), 405

    return application


# ---------------------------------------------------------------------------
# Module-level app binding — required by gunicorn (app.main:app)
# ---------------------------------------------------------------------------
app = create_app()


# ---------------------------------------------------------------------------
# Local dev entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
        threaded=True,
    )
