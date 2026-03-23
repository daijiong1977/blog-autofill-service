"""
app.py — Flask wrapper for blog-autofill service.

Endpoints:
    GET  /health           → {"status": "ok"}
    POST /run              → triggers Chinese translation backfill, returns JSON results
    GET  /run?secret=...   → same (convenient for browser / cron ping)
    POST /run-cn           → same as /run
    POST /run-en           → disabled by default

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
@app.route("/run-cn", methods=["GET", "POST"])
def run_cn():
    def handler():
        import autofill
        limit = request.args.get("limit", default=3, type=int)
        batch_size = request.args.get("batch_size", default=3, type=int)
        result = autofill.run_autofill_cn(limit=limit, batch_size=batch_size)
        return jsonify({
            "status": "done",
            "mode": "chinese",
            "translated": len(result["translated"]),
            "errors": len(result["errors"]),
            "batch_size": result.get("batch_size"),
            "batches": result.get("batches"),
            "posts": result["translated"],
            "failures": result["errors"],
        })

    return _run_with_lock(handler)


@app.route("/run-en", methods=["GET", "POST"])
def run_en_disabled():
    err = _check_secret()
    if err:
        return err
    return jsonify({
        "status": "disabled",
        "mode": "english",
        "message": "English generation is disabled. This service now keeps the original English content and only backfills Chinese translations.",
    }), 410


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
