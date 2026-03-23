"""
app.py — Flask wrapper for blog-autofill service.

Endpoints:
    GET  /health           → {"status": "ok"}
    POST /run              → triggers English-only blog autofill, returns JSON results
    GET  /run?secret=...   → same (convenient for browser / cron ping)
    POST /run-en           → same as /run
    POST /run-cn           → translates existing English posts and updates CN fields only
    GET  /run-cn?secret=...→ same

Protect the /run endpoint with the RUN_SECRET env var.
If RUN_SECRET is not set, the endpoint is open (set it!).
"""

import os, threading
from flask import Flask, request, jsonify

app = Flask(__name__)

RUN_SECRET = os.environ.get("RUN_SECRET", "")

# Track running jobs to prevent concurrent runs
_job_lock = threading.Lock()

def _check_secret():
    if not RUN_SECRET:
        return None  # open if not configured
    provided = request.args.get("secret") or request.headers.get("X-Run-Secret", "")
    if provided != RUN_SECRET:
        return jsonify({"error": "Unauthorized"}), 401
    return None


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


def _run_with_lock(handler):
    err = _check_secret()
    if err:
        return err

    if not _job_lock.acquire(blocking=False):
        return jsonify({"error": "A run is already in progress. Try again in a few minutes."}), 429

    try:
        return handler()
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        _job_lock.release()


@app.route("/run", methods=["GET", "POST"])
@app.route("/run-en", methods=["GET", "POST"])
def run_en():
    def handler():
        import autofill
        result = autofill.run_autofill_en()
        return jsonify({
            "status": "done",
            "mode": "english",
            "created": len(result["created"]),
            "errors": len(result["errors"]),
            "posts": result["created"],
            "failures": result["errors"],
        })

    return _run_with_lock(handler)


@app.route("/run-cn", methods=["GET", "POST"])
def run_cn():
    def handler():
        import autofill
        limit = request.args.get("limit", default=6, type=int)
        result = autofill.run_autofill_cn(limit=limit)
        return jsonify({
            "status": "done",
            "mode": "chinese",
            "translated": len(result["translated"]),
            "errors": len(result["errors"]),
            "posts": result["translated"],
            "failures": result["errors"],
        })

    return _run_with_lock(handler)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
