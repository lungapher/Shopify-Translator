import os
import base64
import requests
from io import BytesIO
from flask import Flask, request, jsonify
from flask_cors import CORS
from PIL import Image, ImageDraw, ImageFont

# Google Cloud Clients
from google.cloud import vision
from google.cloud import translate_v2 as translate

# Flask Setup
app = Flask(__name__)
CORS(app)

# Environment Configs
SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_CREDENTIALS_PATH

# Google Clients
vision_client = vision.ImageAnnotatorClient()
translate_client = translate.Client()

# Constants
KES_EXCHANGE_RATE = 18.5
MARKUP_PERCENT = 20


def translate_text(text, source='auto', target='en'):
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
    for annotation in response.text_annotations[1:]:  # Skip first block (full text)
        text = annotation.description
        vertices = [(v.x, v.y) for v in annotation.bounding_poly.vertices]
        results.append({'text': text, 'vertices': vertices})
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
        original = item['text']
        translated = translate_text(original)
        vertices = item['vertices']

        x_coords = [v[0] for v in vertices]
        y_coords = [v[1] for v in vertices]
        x_min, y_min = min(x_coords), min(y_coords)
        x_max, y_max = max(x_coords), max(y_coords)

        draw.rectangle([(x_min, y_min), (x_max, y_max)], fill="white")
        draw.text((x_min, y_min), translated, fill="black", font=font)

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
    response = requests.post(url, headers=headers, json=payload)
    return response.json()


@app.route('/')
def health():
    return "✅ Shopify Translator with Image Text Replacement is live."


@app.route('/translate-latest', methods=['POST'])
def translate_product():
    try:
        data = request.get_json()
        product = data.get('product') or data
        product_id = product['id']

        new_title = translate_text(product.get('title', ''))
        new_body = translate_text(product.get('body_html', ''))
        tags = product.get('tags', '')
        new_tags = ', '.join([translate_text(tag.strip()) for tag in tags.split(',')]) if tags else ''

        new_variants = []
        for variant in product.get('variants', []):
            price = float(variant.get('price', 0))
            price_in_kes = round(price * KES_EXCHANGE_RATE * (1 + MARKUP_PERCENT / 100), 0)
            new_variants.append({
                **variant,
                "price": price_in_kes,
                "title": translate_text(variant.get('title', '')),
                "option1": translate_text(variant.get('option1', '')),
                "option2": translate_text(variant.get('option2', '')),
                "option3": translate_text(variant.get('option3', ''))
            })

        new_image_urls = []
        for image in product.get('images', []):
            image_url = image.get('src')
            ocr_results = extract_text_with_boxes(image_url)
            downloaded_image = download_image(image_url)
            updated_image = replace_text_on_image(downloaded_image, ocr_results)
            upload_result = upload_translated_image_to_shopify(product_id, updated_image)
            new_image_urls.append(upload_result.get('image', {}).get('src'))

        headers = {
            "X-Shopify-Access-Token": SHOPIFY_API_KEY,
            "Content-Type": "application/json"
        }

        payload = {
            "product": {
                "id": product_id,
                "title": new_title,
                "body_html": new_body,
                "tags": new_tags,
                "variants": new_variants
            }
        }

        url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products/{product_id}.json"
        response = requests.put(url, headers=headers, json=payload)
        response.raise_for_status()

        return jsonify({
            "status": "success",
            "product_id": product_id,
            "translated_title": new_title,
            "new_images": new_image_urls
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
