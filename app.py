import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.cloud import vision
from google.cloud import translate_v2 as translate
from google.auth.exceptions import DefaultCredentialsError

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Log the credentials path being used
credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
logger.info(f"Using credentials from: {credentials_path}")

# Initialize Flask
app = Flask(__name__)
CORS(app)

try:
    # Initialize Google Cloud Vision and Translate clients
    vision_client = vision.ImageAnnotatorClient()
    translate_client = translate.Client()
    logger.info("Google Cloud clients initialized successfully.")
except DefaultCredentialsError as e:
    logger.error("Failed to load Google Cloud credentials: %s", e)
    raise

@app.route("/")
def home():
    return jsonify({"message": "Shopify Translator API is running."})

@app.route("/translate", methods=["POST"])
def translate_text():
    data = request.json
    text = data.get("text", "")
    target_lang = data.get("target", "en")

    if not text:
        return jsonify({"error": "Text is required."}), 400

    try:
        translation = translate_client.translate(text, target_language=target_lang)
        return jsonify({
            "input": text,
            "translatedText": translation["translatedText"],
            "detectedSourceLanguage": translation.get("detectedSourceLanguage")
        })
    except Exception as e:
        logger.error("Translation failed: %s", e)
        return jsonify({"error": "Translation failed."}), 500

# Run with gunicorn, not Flask's built-in server
# gunicorn app:app

