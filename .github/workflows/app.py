import os
import io
import base64
import logging
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from PIL import Image, ImageDraw, ImageFont
import requests
from google.cloud import vision
from google.cloud import translate_v2 as translate
from google.oauth2 import service_account

app = Flask(__name__)
CORS(app)

# Setup Google credentials from service account JSON
creds = service_account.Credentials.from_service_account_file(
    os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
)
vision_client = vision.ImageAnnotatorClient(credentials=creds)
translate_client = translate.Client(credentials=creds)

# Shopify credentials
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE")
SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY")
SHOPIFY_ADMIN_API = f"https://{SHOPIFY_API_KEY}@{SHOPIFY_STORE}/admin/api/2024-04"

# Track failed image translations
failed_images = []

def extract_text(img_url):
    response = requests.get(img_url)
    content = response.content
    image = vision.Image(content=content)
    response = vision_client.text_detection(image=image)
    return response.text_annotations

def translate_text(text):
    result = translate_client.translate(text, target_language='en')
    return result['translatedText']

def overlay_translated_text(img_url, annotations):
    img_bytes = requests.get(img_url).content
    image = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    for ann in annotations[1:]:
        box = ann.bounding_poly.vertices
        translated = translate_text(ann.description)
        x, y = box[0].x, box[0].y
        draw.rectangle([(x, y), (box[2].x, box[2].y)], fill=(255, 255, 255, 200))
        draw.text((x, y), translated, fill="black", font=font)

    output = io.BytesIO()
    image.save(output, format='PNG')
    output.seek(0)
    return output

def upload_image_to_shopify(product_id, img_io):
    img_base64 = base64.b64encode(img_io.read()).decode('utf-8')
    data = {
        "image": {
            "attachment": img_base64
        }
    }
    url = f"{SHOPIFY_ADMIN_API}/products/{product_id}/images.json"
    resp = requests.post(url, json=data)
    if resp.status_code == 201:
        return resp.json()["image"]["src"]
    return None

def delete_old_image(image_id, product_id):
    del_url = f"{SHOPIFY_ADMIN_API}/products/{product_id}/images/{image_id}.json"
    requests.delete(del_url)

def process_product(product):
    product_id = product["id"]
    for image in product["images"]:
        try:
            img_url = image["src"]
            annotations = extract_text(img_url)
            if not annotations:
                continue
            translated_img = overlay_translated_text(img_url, annotations)
            new_img_url = upload_image_to_shopify(product_id, translated_img)
            if new_img_url:
                delete_old_image(image["id"], product_id)
        except Exception as e:
            failed_images.append({"product_id": product_id, "image_url": image["src"], "error": str(e)})

def fetch_all_products():
    url = f"{SHOPIFY_ADMIN_API}/products.json?limit=250"
    products = []
    while url:
        resp = requests.get(url)
        if resp.status_code != 200:
            break
        data = resp.json()
        products.extend(data.get("products", []))
        link_header = resp.headers.get("Link")
        url = None
        if link_header and 'rel="next"' in link_header:
            for part in link_header.split(","):
                if 'rel="next"' in part:
                    url = part.split(";")[0].strip("<> ")
    return products

@app.route("/start-translation", methods=["GET"])
def start_translation():
    threading.Thread(target=batch_translate_products).start()
    return jsonify({"status": "started"})

@app.route("/failed", methods=["GET"])
def get_failed():
    return jsonify(failed_images)

def batch_translate_products():
    products = fetch_all_products()
    for product in products:
        process_product(product)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
