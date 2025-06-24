import os
import logging
import asyncio
import json
import base64
import aiohttp
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.cloud import vision
from google.cloud import translate_v2 as translate
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

#  Environment variables
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
SHOPIFY_ADMIN_API_ACCESS_TOKEN = os.getenv("SHOPIFY_ADMIN_API_ACCESS_TOKEN")

# Google Cloud Clients
vision_client = vision.ImageAnnotatorClient()
translate_client = translate.Client()

# Failed translations storage
failed_translations = []

def detect_language(text):
    try:
        result = translate_client.detect_language(text)
        return result["language"]
    except Exception as e:
        logging.error(f"Language detection error: {str(e)}")
        return None

def translate_text(text, target="en"):
    try:
        return translate_client.translate(text, target_language=target)["translatedText"]
    except Exception as e:
        logging.error(f"Translation error: {str(e)}")
        return text  # Return original text on failure

def overlay_text(image_content, ocr_response):
    image = Image.open(BytesIO(image_content)).convert("RGBA")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("Arial.ttf", 15)
    except IOError:
        logging.warning("Custom font not found, using default font.")
        font = ImageFont.load_default()

    for annotation in ocr_response.text_annotations[1:]:
        box = [(vertex.x, vertex.y) for vertex in annotation.bounding_poly.vertices]
        translated = translate_text(annotation.description)
        draw.rectangle(box, fill=(255, 255, 255, 180))
        draw.text((box[0][0], box[0][1]), translated, fill="black", font=font)

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()

def shopify_headers():
    return {
        "X-Shopify-Access-Token": SHOPIFY_ADMIN_API_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }

async def update_image_on_shopify(session, product_id, image_id, filename, encoded_img):
    url = f"https://{SHOPIFY_STORE}/admin/api/2023-07/products/{product_id}/images/{image_id}.json"
    payload = {"image": {"attachment": encoded_img, "filename": filename}}
    async with session.put(url, headers=shopify_headers(), json=payload) as response:
        if response.status != 200:
            logging.error(f"Failed to update image {image_id} for product {product_id}: {response.status}")
        else:
            logging.info(f"Updated image {image_id} for product {product_id} successfully.")

async def process_image(session, product_id, image):
    try:
        image_url = image["src"]
        image_id = image["id"]
        async with session.get(image_url) as response:
            content = await response.read()

        ocr_response = vision_client.text_detection(image=vision.Image(content=content))
        if not ocr_response.text_annotations:
            logging.info(f"No text detected in image {image_id} for product {product_id}.")
            return

        detected_text = ocr_response.text_annotations[0].description.strip()
        if detect_language(detected_text) == "en":
            logging.info(f"Image {image_id} for product {product_id} is already in English.")
            return

        new_img = overlay_text(content, ocr_response)
        encoded_img = base64.b64encode(new_img).decode("utf-8")
        filename = f"translated_{image_id}.png"

        await update_image_on_shopify(session, product_id, image_id, filename, encoded_img)

    except Exception as e:
        error_msg = f"Failed to process image {image_id} for product {product_id}: {str(e)}"
        logging.error(error_msg)
        failed_translations.append({"product_id": product_id, "image_id": image_id, "error": str(e)})

async def process_all_products():
    try:
        async with aiohttp.ClientSession() as session:
            page = 1
            while True:
                url = f"https://{SHOPIFY_STORE}/admin/api/2023-07/products.json?limit=250&page={page}"
                async with session.get(url, headers=shopify_headers()) as response:
                    res = await response.json()
                    products = res.get("products", [])
                    if not products:
                        break
                    tasks = [
                        process_image(session, product["id"], image)
                        for product in products
                        for image in product.get("images", [])
                    ]
                    await asyncio.gather(*tasks)
                page += 1
    except Exception as e:
        logging.error(f"Error during processing of all products: {str(e)}")

@app.route("/", methods=["GET"])
def home():
    return "🟢 Shopify Translator Running!"

@app.route("/start-translation", methods=["GET"])
def start_translation():
    asyncio.run(process_all_products())
    return jsonify({"status": "Started manual scan"})

@app.route("/failed", methods=["GET"])
def get_failed():
    return jsonify({"failed": failed_translations})

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    product_id = data.get("id")
    if product_id:
        try:
            asyncio.run(process_individual_product(product_id))
        except Exception as e:
            logging.error(f"Webhook processing error for product {product_id}: {str(e)}")
            failed_translations.append({"product_id": product_id, "error": str(e)})
    return "", 200

async def process_individual_product(product_id):
    async with aiohttp.ClientSession() as session:
        url = f"https://{SHOPIFY_STORE}/admin/api/2023-07/products/{product_id}.json"
        async with session.get(url, headers=shopify_headers()) as response:
            res = await response.json()
            product = res.get("product")
            if product:
                tasks = [
                    process_image(session, product_id, image)
                    for image in product.get("images", [])
                ]
                await asyncio.gather(*tasks)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(port=port)
