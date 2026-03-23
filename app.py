"""
app.py — Flask wrapper for blog-autofill service.

Endpoints:
  GET  /health         → {"status": "ok"}
  POST /run            → triggers blog autofill, returns JSON results
  GET  /run?secret=... → same (convenient for browser / cron ping)

Protect the /run endpoint with the RUN_SECRET env var.
If RUN_SECRET is not set, the endpoint is open (set it!).
"""

import os, threading, time
from flask import Flask, request, jsonify

app = Flask(__name__)

RUN_SECRET = os.environ.get("RUN_SECRET", "")

# Track running jobs to prevent concurrent runs
_job_lock  = threading.Lock()
_last_result = None

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


@app.route("/run", methods=["GET", "POST"])
def run():
    err = _check_secret()
    if err:
        return err

    if not _job_lock.acquire(blocking=False):
        return jsonify({"error": "A run is already in progress. Try again in a few minutes."}), 429

    try:
        import autofill
        result = autofill.run_autofill()
        return jsonify({
            "status":   "done",
            "created":  len(result["created"]),
            "errors":   len(result["errors"]),
            "posts":    result["created"],
            "failures": result["errors"],
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        _job_lock.release()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
