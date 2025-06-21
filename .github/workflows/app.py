from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os

app = Flask(__name__)
CORS(app)

# Load environment variables or fallback for testing
SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY", "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")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "salibay.com")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyCpM6Reul5DuUBVQ3VvGDEK5Z7WpsLsFTk")

def translate_text(text, source='zh', target='en'):
    if not text or not text.strip():
        return text
    url = 'https://translation.googleapis.com/language/translate/v2'
    params = {
        'q': text,
        'source': source,
        'target': target,
        'format': 'text',
        'key': GOOGLE_API_KEY
    }
    try:
        response = requests.post(url, data=params)
        response.raise_for_status()
        result = response.json()
        return result['data']['translations'][0]['translatedText']
    except Exception as e:
        return f"[Translation Failed] {str(e)}"

@app.route('/translate-latest', methods=['POST'])
def translate_product():
    try:
        data = request.get_json()
        product = data.get('product') or data
        product_id = product['id']

        # Translate title and body_html
        new_title = translate_text(product.get('title', ''))
        new_body = translate_text(product.get('body_html', ''))

        # Translate tags
        tags = product.get('tags', '')
        new_tags = ', '.join([translate_text(tag.strip()) for tag in tags.split(',')]) if tags else ''

        # Translate variants (option values)
        new_variants = []
        for variant in product.get('variants', []):
            translated_variant = variant.copy()
            translated_variant['title'] = translate_text(variant.get('title', ''))
            translated_variant['option1'] = translate_text(variant.get('option1', ''))
            translated_variant['option2'] = translate_text(variant.get('option2', ''))
            translated_variant['option3'] = translate_text(variant.get('option3', ''))
            new_variants.append(translated_variant)

        # Translate image alt texts
        new_images = []
        for image in product.get('images', []):
            translated_image = image.copy()
            translated_image['alt'] = translate_text(image.get('alt', ''))
            new_images.append(translated_image)

        # Build update payload
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

        # Update Shopify product
        update_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products/{product_id}.json"
        headers = {
            "X-Shopify-Access-Token": SHOPIFY_API_KEY,
            "Content-Type": "application/json"
        }

        update_res = requests.put(update_url, headers=headers, json=payload)
        update_res.raise_for_status()

        return jsonify({
            "status": "translated",
            "product_id": product_id,
            "new_title": new_title,
            "new_tags": new_tags
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/')
def health_check():
    return "✅ Shopify Translator API is running."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
