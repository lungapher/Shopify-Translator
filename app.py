import os
import threading
import json
import base64
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.cloud import vision
from google.cloud import translate_v2 as translate
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

app = Flask(__name__)
CORS(app)

# Shopify and Google Cloud configuration
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE")
SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY")
SHOPIFY_API_PASS = os.environ.get("SHOPIFY_API_PASS")
vision_client = vision.ImageAnnotatorClient()
translate_client = translate.Client()

failed_translations = []

def detect_language(text):
    result = translate_client.detect_language(text)
    return result["language"]

def translate_text(text, target="en"):
    return translate_client.translate(text, target_language=target)["translatedText"]

def overlay_text(image_content, ocr_response):
    image = Image.open(BytesIO(image_content)).convert("RGBA")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    for annotation in ocr_response.text_annotations[1:]:
        box = [(vertex.x, vertex.y) for vertex in annotation.bounding_poly.vertices]
        translated = translate_text(annotation.description)
        draw.rectangle(box, fill=(255, 255, 255, 180))
        draw.text((box[0][0], box[0][1]), translated, fill="black", font=font)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()

def process_image(product_id, image):
    try:
        image_url = image["src"]
        image_id = image["id"]
        response = requests.get(image_url)
        content = response.content

        ocr_response = vision_client.text_detection(image=vision.Image(content=content))
        if not ocr_response.text_annotations:
            return

        detected_text = ocr_response.text_annotations[0].description.strip()
        if detect_language(detected_text) == "en":
            return  # Skip English images

        new_img = overlay_text(content, ocr_response)
        encoded_img = base64.b64encode(new_img).decode("utf-8")
        filename = f"translated_{image_id}.png"

        update_image_on_shopify(product_id, image_id, filename, encoded_img)
    except Exception as e:
        failed_translations.append({"product_id": product_id, "image_id": image["id"], "error": str(e)})

def update_image_on_shopify(product_id, image_id, filename, encoded_img):
    url = f"https://{SHOPIFY_API_KEY}:{SHOPIFY_API_PASS}@{SHOPIFY_STORE}/admin/api/2023-07/products/{product_id}/images/{image_id}.json"
    payload = {
        "image": {
            "attachment": encoded_img,
            "filename": filename
        }
    }
    requests.put(url, json=payload)

def process_all_products():
    try:
        page = 1
        while True:
            url = f"https://{SHOPIFY_API_KEY}:{SHOPIFY_API_PASS}@{SHOPIFY_STORE}/admin/api/2023-07/products.json?limit=250&page={page}"
            res = requests.get(url).json()
            products = res.get("products", [])
            if not products:
                break
            for product in products:
                for image in product.get("images", []):
                    process_image(product["id"], image)
            page += 1
    except Exception as e:
        print("Processing error:", str(e))

@app.route("/start-translation", methods=["GET"])
def start_translation():
    thread = threading.Thread(target=process_all_products)
    thread.start()
    return jsonify({"status": "Translation started in background"}), 200

@app.route("/failed", methods=["GET"])
def get_failed():
    return jsonify({"failed": failed_translations}), 200

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if data.get("id"):
        threading.Thread(target=lambda: process_image(data["id"], data.get("image", {}))).start()
    return "", 200

@app.route("/", methods=["GET"])
def index():
    return "🟢 Shopify Translator API Running"

if __name__ == "__main__":
    app.run(port=int(os.environ.get("PORT", 10000)))
