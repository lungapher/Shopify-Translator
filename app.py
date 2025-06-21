import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

# Google Cloud Libraries
from google.cloud import vision
from google.cloud import translate_v2 as translate

# Init Flask
app = Flask(__name__)
CORS(app)

# Environment Configs
SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

# Init Google API clients
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_CREDENTIALS_PATH
vision_client = vision.ImageAnnotatorClient()
translate_client = translate.Client()

# Static settings
KES_EXCHANGE_RATE = 18.5
MARKUP_PERCENT = 20


def translate_text(text, source='zh', target='en'):
    if not text.strip():
        return text
    try:
        result = translate_client.translate(text, source_language=source, target_language=target)
        return result['translatedText']
    except Exception as e:
        return f"[Translation failed] {str(e)}"


def extract_text_from_image(image_url):
    try:
        image = vision.Image()
        image.source.image_uri = image_url
        response = vision_client.text_detection(image=image)
        annotations = response.text_annotations
        return annotations[0].description if annotations else ''
    except Exception as e:
        return f"[OCR failed] {str(e)}"


@app.route('/')
def health():
    return "✅ Shopify Translator API with OCR is live."


@app.route('/translate-latest', methods=['POST'])
def translate_product():
    try:
        data = request.get_json()
        product = data.get('product') or data
        product_id = product['id']

        # Translate core fields
        new_title = translate_text(product.get('title', ''))
        new_body = translate_text(product.get('body_html', ''))
        tags = product.get('tags', '')
        new_tags = ', '.join([translate_text(tag.strip()) for tag in tags.split(',')]) if tags else ''

        # Translate variants + convert price to KES
        new_variants = []
        for variant in product.get('variants', []):
            original_price = float(variant.get('price', 0))
            price_in_kes = round(original_price * KES_EXCHANGE_RATE * (1 + MARKUP_PERCENT / 100), 0)
            translated_variant = variant.copy()
            translated_variant.update({
                "price": price_in_kes,
                "title": translate_text(variant.get('title', '')),
                "option1": translate_text(variant.get('option1', '')),
                "option2": translate_text(variant.get('option2', '')),
                "option3": translate_text(variant.get('option3', ''))
            })
            new_variants.append(translated_variant)

        # Translate image alt text using OCR
        new_images = []
        for image in product.get('images', []):
            image_url = image.get('src')
            if not image_url:
                continue

            extracted_text = extract_text_from_image(image_url)
            translated_alt = translate_text(extracted_text)

            if translated_alt and not translated_alt.startswith("["):
                translated_image = {
                    "id": image.get('id'),
                    "alt": translated_alt
                }
                new_images.append(translated_image)

        # Shopify PUT request to update product
        payload = {
            "product": {
                "id": product_id,
                "title": new_title,
                "body_html": new_body,
                "tags": new_tags,
                "variants": new_variants,
                "images": new_images
            }
        }

        headers = {
            "X-Shopify-Access-Token": SHOPIFY_API_KEY,
            "Content-Type": "application/json"
        }
        url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products/{product_id}.json"

        response = requests.put(url, headers=headers, json=payload)
        response.raise_for_status()

        return jsonify({
            "status": "success",
            "product_id": product_id,
            "translated_title": new_title
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
