import os, threading, time, requests, base64
from io import BytesIO
from flask import Flask, request, jsonify
from flask_cors import CORS
from PIL import Image, ImageDraw, ImageFont
from google.cloud import vision, translate_v2 as translate

app = Flask(__name__)
CORS(app)

# ENV
SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

# Google clients
vision_client = vision.ImageAnnotatorClient()
translate_client = translate.Client()

# Constants
KES_RATE, MARKUP = 18.5, 0.20
status = {"total": 0, "done": 0, "failed": []}
lock = threading.Lock()

def translate_text(s): return translate_client.translate(s, source_language='zh', target_language='en')['translatedText'] if s.strip() else ""

def ocr_and_replace(img_url):
    img = Image.open(BytesIO(requests.get(img_url).content)).convert("RGBA")
    resp = vision_client.text_detection({"source":{"image_uri":img_url}})
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    for annot in resp.text_annotations[1:]:
        txt, vs = annot.description, [(v.x, v.y) for v in annot.bounding_poly.vertices]
        draw.polygon(vs, fill="white")
        draw.text(vs[0], translate_text(txt), fill="black", font=font)
    return img

def upload_image(pid, img):
    buf = BytesIO(); img.save(buf, format="PNG")
    att = base64.b64encode(buf.getvalue()).decode()
    return requests.post(f"https://{SHOPIFY_STORE}/admin/api/2024-01/products/{pid}/images.json",
                         headers={"X-Shopify-Access-Token": SHOPIFY_API_KEY, "Content-Type":"application/json"},
                         json={"image":{"attachment":att}})

def process_product(prod):
    pid = prod['id']
    for img in prod.get('images', []):
        try:
            upload_image(pid, ocr_and_replace(img['src']))
        except Exception:
            with lock:
                status["failed"].append(pid)
    with lock:
        status["done"] += 1

def run_all(chunk=5):
    resp = requests.get(f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?limit=250",
                        headers={"X-Shopify-Access-Token": SHOPIFY_API_KEY}).json()
    prods = resp.get('products', [])
    status.update({"total": len(prods), "done": 0, "failed": []})
    sem = threading.Semaphore(chunk)
    def worker(prod):
        with sem:
            process_product(prod)
    for p in prods:
        threading.Thread(target=worker, args=(p,)).start()

@app.route('/start-translation', methods=['GET'])
def start_trigger():
    chunk = int(request.args.get('chunk', 5))
    threading.Thread(target=run_all, args=(chunk,)).start()
    return jsonify({"started": True, "chunk": chunk})

@app.route('/status', methods=['GET'])
def get_status():
    return jsonify(status)

@app.route('/failed', methods=['GET'])
def get_failed():
    return jsonify(status["failed"])

@app.route('/health', methods=['GET'])
def health(): return "🎉 Live"

# Auto-start on boot
threading.Thread(target=lambda: time.sleep(5) or run_all()).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
