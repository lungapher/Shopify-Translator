from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

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
    response = requests.post(url, data=params)
    result = response.json()
    return result['data']['translations'][0]['translatedText']

@app.route('/translate-latest', methods=['GET'])
def translate_latest_product():
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?limit=1&order=created_at desc"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_API_KEY
    }
    res = requests.get(url, headers=headers)
    product = res.json()['products'][0]

    product_id = product['id']
    new_title = translate_text(product['title'])
    new_body = translate_text(product['body_html'])

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
    return jsonify({
        "status": "translated",
        "product_id": product_id,
        "new_title": new_title
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
