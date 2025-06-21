from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os

app = Flask(__name__)
CORS(app)

# Environment variables (for local testing you can hardcode, but don't do this in production)
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
def translate_latest_product():
    try:
        data = request.get_json()
        product = data.get('product') or data  # Shopify may send directly or nested

        product_id = product['id']
        original_title = product.get('title', '')
        original_body = product.get('body_html', '')

        new_title = translate_text(original_title)
        new_body = translate_text(original_body)

        update_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products/{product_id}.json"
        update_headers = {
            "X-Shopify-Access-Token": SHOPIFY_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "product": {
                "id": product_id,
                "title": new_title,
                "body_html": new_body
            }
        }
        update_res = requests.put(update_url, headers=update_headers, json=payload)
        update_res.raise_for_status()

        return jsonify({
            "status": "success",
            "product_id": product_id,
            "original_title": original_title,
            "translated_title": new_title
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
