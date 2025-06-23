import os
import json
import requests
import threading
import time
from flask import Flask, jsonify, request
from flask_cors import CORS
from google.cloud import vision
from google.cloud import translate_v2 as translate
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# === Configuration ===
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE")
SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET")
SHOPIFY_ADMIN_API_ACCESS_TOKEN = os.environ.get("SHOPIFY_ADMIN_API_ACCESS_TOKEN")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

# === Flask App ===
app = Flask(__name__)
CORS(app)

# === Google Clients ===
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "credentials.json"
vision_client = vision.ImageAnnotatorClient()
translate_client = translate.Client()

# === Helper: Translate Image Text ===
def translate_image_text(image_url):
    response = requests.get(image_url)
    image_bytes = BytesIO(response.content)

    image = vision.types.Image(content=image_bytes.read())
    response = vision_client.text_detection(image=image)

    annotations = response.text_annotations
    if not annotations:
        return None

    translated_lines = []
    for annotation in annotations[1:]:  # First result is full text
        box = annotation.bounding_poly.vertices
        text = annotation.description
        translated = translate_client.translate(text, target_language="en")["translatedText"]
        translated_lines.append((box, translated))

    # Overlay translated text on the image
    image_bytes.seek(0)
    img = Image.open(image_bytes).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    for box, translated_text in translated_lines:
        x = box[0].x
        y = box[0].y
        draw.text((x, y), translated_text, fill="red", font=font)

    output = BytesIO()
    img.save(output, format="JPEG")
    output.seek(0)

    return output

# === Helper: Fetch Products ===
def fetch_products():
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?limit=250"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_ADMIN_API_ACCESS_TOKEN
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json().get("products", [])
    except Exception as e:
        print(f"[Error] Fetching products: {e}")
        return []

# === Route: Test Endpoint ===
@app.route("/")
def index():
    return jsonify({"message": "Shopify Translator API is live!"})

# === Route: Start Translation ===
@app.route("/start-translation", methods=["GET"])
def start_translation():
    def run_translation():
        products = fetch_products()
        for product in products:
            for image in product.get("images", []):
                image_url = image.get("src")
                if image_url:
                    translated_img = translate_image_text(image_url)
                    # TODO: upload back to Shopify & replace image URL

    threading.Thread(target=run_translation).start()
    return jsonify({"status": "Translation started in background"})

# === App Runner ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
