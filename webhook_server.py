import os
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- Config (set these as env vars on wherever you host this) ---
VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN")      # you invent this string; must match Meta's App Dashboard webhook config
META_APP_SECRET = os.getenv("META_APP_SECRET")        # from Meta App Dashboard > Settings > Basic; used to verify requests really came from Meta
IG_USER_ID = os.getenv("IG_USER_ID")                  # same value bot.py uses
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")        # same value bot.py uses (must additionally carry messaging permissions - see README)
TRIGGER_WORD = os.getenv("TRIGGER_WORD", "myth")
GUIDE_REPLY_MESSAGE = os.getenv(
    "GUIDE_REPLY_MESSAGE",
    "Thanks for commenting! Here's the full guide on unlearning intimacy myths: <ADD_YOUR_LINK_HERE>",
)

GRAPH_API_VERSION = "v19.0"  # matches bot.py

# In-memory guard so a retried webhook delivery in the same process
# doesn't try to send a second private reply to the same comment
# (Meta only allows one). This resets on restart - fine for this
# scale, not meant as a durable dedupe store.
_already_replied = set()


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """Meta calls this once, when you register the webhook URL in the App Dashboard."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403


def _valid_signature(raw_body, signature_header):
    if not META_APP_SECRET or not signature_header:
        return False
    expected = "sha256=" + hmac.new(
        META_APP_SECRET.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def send_private_reply(comment_id, message_text):
    url = f"https://graph.instagram.com/{GRAPH_API_VERSION}/{IG_USER_ID}/messages"
    payload = {
        "recipient": {"comment_id": comment_id},
        "message": {"text": message_text},
        "access_token": IG_ACCESS_TOKEN,
    }
    response = requests.post(url, json=payload)
    print("Private reply response:", response.status_code, response.text)
    return response.json()


@app.route("/webhook", methods=["POST"])
def handle_webhook():
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _valid_signature(request.get_data(), signature):
        return jsonify({"status": "invalid signature"}), 403

    data = request.get_json(silent=True) or {}

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") not in ("comments", "live_comments"):
                continue

            value = change.get("value", {})
            comment_id = value.get("id")
            comment_text = (value.get("text") or "").lower()

            if not comment_id or comment_id in _already_replied:
                continue

            if TRIGGER_WORD.lower() in comment_text:
                send_private_reply(comment_id, GUIDE_REPLY_MESSAGE)
                _already_replied.add(comment_id)

    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
