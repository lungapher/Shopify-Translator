# Let's generate the upgraded Flask app that includes:
# 1. Full product image translation for all products
# 2. Async/threading for speedup
# 3. Real-time status tracking via a `/status` endpoint

upgraded_flask_code = """
import os
import base64
import threading
import requests
from io import BytesIO
from flask import Flask, request, jsonify
from flask_cors import CORS
from PIL import Image, ImageDraw, ImageFont
from google.cloud import vision
from google.cloud import translate_v2 as translate

# Flask app
app = Flask(__name__)
CORS(app)

# Google API clients
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
vision_client = vision.ImageAnnotatorClient()
translate_client = translate.Client()

# Shopify config
SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
SHOPIFY_API_URL = f"https://{SHOPIFY_STORE}/admin/api/2024-01"

# Currency conversion
KES_EXCHANGE_RATE = 18.5
MARKUP_PERCENT = 20

# Global progress tracker
progress = {
    "total_images": 0,
    "processed_images": 0,
    "status": "idle"
}


def translate_text(text, source='zh', target='en'):
    if not text.strip():
        return text
    try:
        result = translate_client.translate(text, source_language=source, target_language=target)
        return result['translatedText']
    except Exception as e:
        return f"[Translation failed] {str(e)}"


def extract_text_with_boxes(image_url):
    image = vision.Image()
    image.source.image_uri = image_url
    response = vision_client.text_detection(image=image)
    results = []
    for annotation in response.text_annotations[1:]:
        vertices = [(v.x, v.y) for v in annotation.bounding_poly.vertices]
        results.append({"text": annotation.description, "vertices": vertices})
    return results


def download_image(image_url):
    response = requests.get(image_url)
    return Image.open(BytesIO(response.content)).convert("RGBA")


def replace_text_on_image(image, ocr_results):
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except:
        font = ImageFont.load_default()
    for item in ocr_results:
        translated = translate_text(item["text"])
        vertices = item["vertices"]
        draw.polygon(vertices, fill="white")
        x, y = vertices[0]
        draw.text((x, y), translated, fill="black", font=font)
    return image


def upload_translated_image_to_shopify(product_id, image_obj):
    buffered = BytesIO()
    image_obj.save(buffered, format="PNG")
    image_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {"image": {"attachment": image_base64}}
    url = f"{SHOPIFY_API_URL}/products/{product_id}/images.json"
    response = requests.post(url, headers=headers, json=payload)
    return response.status_code == 201


def process_product_images(product):
    global progress
    product_id = product["id"]
    for image in product.get("images", []):
        image_url = image.get("src")
        if not image_url:
            continue
        try:
            ocr_results = extract_text_with_boxes(image_url)
            if not ocr_results:
                continue
            downloaded = download_image(image_url)
            edited = replace_text_on_image(downloaded, ocr_results)
            upload_translated_image_to_shopify(product_id, edited)
        except Exception as e:
            print(f"Failed to process image: {image_url}", e)
        progress["processed_images"] += 1


def fetch_all_products():
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_API_KEY,
        "Content-Type": "application/json"
    }
    products = []
    page = 1
    while True:
        url = f"{SHOPIFY_API_URL}/products.json?limit=250&page={page}"
        response = requests.get(url, headers=headers).json()
        batch = response.get("products", [])
        if not batch:
            break
        products.extend(batch)
        page += 1
    return products


def start_bulk_translation():
    global progress
    progress["status"] = "running"
    all_products = fetch_all_products()
    progress["total_images"] = sum(len(p.get("images", [])) for p in all_products)
    progress["processed_images"] = 0

    threads = []
    for product in all_products:
        t = threading.Thread(target=process_product_images, args=(product,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()
    progress["status"] = "complete"


@app.route("/")
def health():
    return "✅ Bulk Translator API is live."


@app.route("/start-translation", methods=["POST"])
def start_translation():
    thread = threading.Thread(target=start_bulk_translation)
    thread.start()
    return jsonify({"status": "started"})


@app.route("/status", methods=["GET"])
def check_status():
    return jsonify(progress)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
"""

upgraded_flask_code[:2000]  # Showing the first 2000 characters to verify
