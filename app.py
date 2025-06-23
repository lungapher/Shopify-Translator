import os
import json
import time
from flask import Flask, jsonify, request
from flask_cors import CORS
from google.cloud import vision
from google.cloud import translate_v2 as translate
from google.oauth2 import service_account

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Load credentials from environment variable
creds_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
if not creds_json:
    raise Exception("Missing GOOGLE_APPLICATION_CREDENTIALS_JSON environment variable")

credentials = service_account.Credentials.from_service_account_info(json.loads(creds_json))

# Initialize Google Cloud clients
vision_client = vision.ImageAnnotatorClient(credentials=credentials)
translate_client = translate.Client(credentials=credentials)

# Health check
@app.route("/", methods=["GET"])
def index():
    return jsonify({"message": "Shopify Translator is running!"})

# Endpoint to start translation
@app.route("/start-translation", methods=["GET"])
def start_translation():
    chunk = int(request.args.get("chunk", 10))
    # Placeholder logic for now
    return jsonify({"status": "started", "chunk_size": chunk})

# Endpoint to handle failed cases
@app.route("/failed", methods=["GET"])
def get_failed():
    return jsonify({"failed": []})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
