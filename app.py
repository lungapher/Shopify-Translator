from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os

app = Flask(__name__)
CORS(app)  # Optional: Enable CORS if needed

# Load environment variables
SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

def translate_text(text, source='zh', target='en'):
    if not text.strip():
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
        return f"Translation Error: {str(e)}"

@app.route('/translate-latest', methods=['GET'])
def translate_latest_product():
    try:
        # Get the latest product from Shopify
        url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?limit=1&order=created_at desc"
        headers = {
            "X-Shopify-Access-Token": SHOPIFY_API_KEY
        }
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        product = res.json()['products'][0]

        product_id = product['id']
        new_title = translate_text(product['title'])
        new_body = translate_text(product['body_html'])

        # Update product with translated content
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
            "status": "translated",
            "product_id": product_id,
            "new_title": new_title
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/')
def index():
    return "✅ Shopify Translator API is running."

# Only used for local development. On Render, gunicorn will start the app.
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
