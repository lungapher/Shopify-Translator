import os
import json
import threading
import time
from flask import Flask, jsonify, request
from flask_cors import CORS

from translate_images import translate_all_images
from google.oauth2 import service_account

app = Flask(__name__)
CORS(app)

# === Load Google Credentials from ENV ===
credentials_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
if not credentials_json:
    raise Exception("Missing GOOGLE_APPLICATION_CREDENTIALS_JSON environment variable")

credentials_info = json.loads(credentials_json)
credentials = service_account.Credentials.from_service_account_info(credentials_info)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "credentials.json"

# Write credentials to file for Google SDK
with open("credentials.json", "w") as f:
    f.write(credentials_json)

# === Status Store ===
status = {
    "running": False,
    "completed": 0,
    "failed": [],
    "total": 0
}

# === Routes ===
@app.route('/')
def home():
    return jsonify({"message": "Shopify Translator API is running."})

@app.route('/status')
def get_status():
    return jsonify(status)

@app.route('/failed')
def get_failed():
    return jsonify({"failed": status["failed"]})

@app.route('/re-run-failed')
def re_run_failed():
    thread = threading.Thread(target=start_translation, kwargs={"retry_failed": True})
    thread.start()
    return jsonify({"status": "retrying failed products"})

@app.route('/start-translation')
def start_translation_route():
    chunk_size = int(request.args.get("chunk", 10))
    thread = threading.Thread(target=start_translation, args=(chunk_size,))
    thread.start()
    return jsonify({"status": "started", "chunk_size": chunk_size})

@app.route('/webhook/product-create', methods=["POST"])
def product_webhook():
    thread = threading.Thread(target=start_translation, args=(10,))
    thread.start()
    return jsonify({"status": "translation triggered by webhook"})

# === Translation Trigger Function ===
def start_translation(chunk_size=10, retry_failed=False):
    if status["running"]:
        print("Translation already in progress...")
        return

    status["running"] = True
    try:
        print(f"🚀 Starting {'failed retry' if retry_failed else 'full'} translation (chunk={chunk_size})")
        result = translate_all_images(chunk_size=chunk_size, retry_failed=retry_failed)
        status["completed"] = result["completed"]
        status["failed"] = result["failed"]
        status["total"] = result["total"]
        print("✅ Translation finished")
    except Exception as e:
        print("❌ Translation failed:", e)
    finally:
        status["running"] = False

# === Background Tasks ===
def auto_start_translation():
    time.sleep(5)
    print("🔄 Auto-starting translation at startup...")
    start_translation(chunk_size=10)

def auto_retry_failed_every_hour():
    while True:
        time.sleep(3600)
        if status["failed"]:
            print("⏳ Auto-retrying failed products...")
            start_translation(retry_failed=True)

# === Main Entry ===
if __name__ == '__main__':
    threading.Thread(target=auto_start_translation).start()
    threading.Thread(target=auto_retry_failed_every_hour, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)
