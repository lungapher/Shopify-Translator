# Let's prepare the upgraded version of the user's Flask app:
# - Adds support for translating all existing product images
# - Adds a background sync process
# - Adds a status endpoint for tracking progress
# - Preserves the original image editing and upload logic

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import base64
import threading
import time
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

from google.cloud import vision
from google.cloud import translate_v2 as translate

app = Flask(__name__)
CORS(app)

# Environment Variables
SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_CREDENTIALS_PATH

# Google Clients
vision_client = vision.ImageAnnotatorClient()
translate_client = translate.Client()

KES_EXCHANGE_RATE = 18.5
MARKUP_PERCENT = 20

# Shared status dictionary
translation_status = {
    "total": 0,
    "completed": 0,
    "last_product": ""
}

def translate_text(text, source='zh', target='en'):
    if not text.strip():
        return text
    try:
        result = translate_client.translate(text, source_language=source, target_language=target)
        return result['translatedText']
    except Exception:
        return text

def extract_text_with_boxes(image_url):
    image = vision.Image()
    image.source.image_uri = image_url
    response = vision_client.text_detection(image=image)

    results = []
    for annotation in response.text_annotations[1:]:  # Skip main text block
        results.append({
            'text': annotation.description,
            'vertices': [(v.x, v.y) for v in annotation.bounding_poly.vertices]
        })
    return results

def download_image(image_url):
    resp = requests.get(image_url)
    return Image.open(BytesIO(resp.content)).convert("RGBA")

def replace_text_on_image(image, ocr_results):
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except:
        font = ImageFont.load_default()
    for item in ocr_results:
        translated = translate_text(item['text'])
        draw.polygon(item['vertices'], fill="white")
        x, y = item['vertices'][0]
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

    payload = {
        "image": {
            "attachment": image_base64
        }
    }

    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products/{product_id}/images.json"
    return requests.post(url, headers=headers, json=payload)

def update_product_fields(product):
    product_id = product['id']

    title = translate_text(product.get('title', ''))
    body = translate_text(product.get('body_html', ''))
    tags = ', '.join([translate_text(tag.strip()) for tag in product.get('tags', '').split(',')])

    new_variants = []
    for v in product.get('variants', []):
        price = float(v.get('price', 0)) * KES_EXCHANGE_RATE * (1 + MARKUP_PERCENT / 100)
        new_variants.append({
            **v,
            "price": round(price, 0),
            "title": translate_text(v.get('title', '')),
            "option1": translate_text(v.get('option1', '')),
            "option2": translate_text(v.get('option2', '')),
            "option3": translate_text(v.get('option3', ''))
        })

    payload = {
        "product": {
            "id": product_id,
            "title": title,
            "body_html": body,
            "tags": tags,
            "variants": new_variants
        }
    }

    headers = {
        "X-Shopify-Access-Token": SHOPIFY_API_KEY,
        "Content-Type": "application/json"
    }
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products/{product_id}.json"
    requests.put(url, headers=headers, json=payload)

def process_product(product):
    product_id = product['id']
    update_product_fields(product)

    for image in product.get('images', []):
        try:
            image_url = image.get('src')
            ocr_results = extract_text_with_boxes(image_url)
            downloaded = download_image(image_url)
            updated = replace_text_on_image(downloaded, ocr_results)
            upload_translated_image_to_shopify(product_id, updated)
        except Exception as e:
            print(f"Image processing failed for product {product_id}: {e}")

@app.route('/status')
def status():
    return jsonify(translation_status)

@app.route('/translate-all', methods=['POST'])
def translate_all_products():
    def run_translation():
        page = 1
        total_processed = 0
        while True:
            url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?limit=50&page={page}"
            headers = {
                "X-Shopify-Access-Token": SHOPIFY_API_KEY,
                "Content-Type": "application/json"
            }
            response = requests.get(url, headers=headers)
            products = response.json().get('products', [])
            if not products:
                break

            for product in products:
                process_product(product)
                total_processed += 1
                translation_status['completed'] = total_processed
                translation_status['last_product'] = product.get('title', '')

            page += 1

        translation_status['total'] = total_processed

    thread = threading.Thread(target=run_translation)
    thread.start()
    return jsonify({"status": "processing", "message": "Started background product translation."})

@app.route('/')
def health():
    return "✅ Shopify Translator & Image OCR System is Live."

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

