import os, threading, time, logging, base64, requests
from io import BytesIO
from flask import Flask, request, jsonify
from flask_cors import CORS
from PIL import Image, ImageDraw, ImageFont
from google.cloud import vision
from google.cloud import translate_v2 as translate

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

vision_client = vision.ImageAnnotatorClient()
translate_client = translate.Client()

status = {"total": 0, "done": 0, "failed": 0, "running": False}
failures = []

def translate_text(text, source='zh', target='en'):
    try:
        return translate_client.translate(text, source_language=source, target_language=target)["translatedText"]
    except Exception as e:
        logging.warning(f"Translate failed: {e}")
        return text

def ocr_extract(image_url):
    img = vision.Image()
    img.source.image_uri = image_url
    res = vision_client.text_detection(image=img)
    return res.text_annotations[1:] if len(res.text_annotations) > 1 else []

def delete_old_image(image_id):
    resp = requests.delete(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/products/{product_id}/images/{image_id}.json",
        headers={"X-Shopify-Access-Token": SHOPIFY_API_KEY}
    )
    return resp.status_code == 200

def process_image(product_id, image):
    image_id = image.get("id")
    src = image.get("src")
    try:
        ocr = ocr_extract(src)
        if not ocr:
            return True
        img = Image.open(BytesIO(requests.get(src).content)).convert("RGBA")
        draw = ImageDraw.Draw(img)
        for ann in ocr:
            box = [(v.x, v.y) for v in ann.bounding_poly.vertices]
            draw.polygon(box, fill="white")
            txt = translate_text(ann.description)
            draw.text(box[0], txt, fill="black", font=ImageFont.load_default())
        buff = BytesIO(); img.save(buff, format="PNG")
        att = base64.b64encode(buff.getvalue()).decode("utf-8")
        resp = requests.post(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/products/{product_id}/images.json",
            headers={"X-Shopify-Access-Token": SHOPIFY_API_KEY, "Content-Type": "application/json"},
            json={"image": {"attachment": att}}
        )
        resp.raise_for_status()
        if image_id:
            delete_old_image(image_id)
        return True
    except Exception as e:
        logging.error(f"Error on {product_id}/{src}: {e}")
        return False

def process_product(prod):
    pid = prod["id"]
    images = prod.get("images", [])
    ok = all(process_image(pid, img) for img in images)
    if not ok:
        failures.append(pid)
    status["done"] += 1
    return ok

def batch_process(chunk):
    status.update({"running": True, "done": 0, "failed": 0})
    failures.clear()
    page = 1
    products = []
    while True:
        resp = requests.get(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?limit=250&page={page}",
            headers={"X-Shopify-Access-Token": SHOPIFY_API_KEY}
        ).json()
        prods = resp.get("products", [])
        if not prods:
            break
        products.extend(prods)
        page += 1
    status["total"] = len(products)
    for i in range(0, len(products), chunk):
        for prod in products[i : i + chunk]:
            process_product(prod)
        time.sleep(1)
    status.update({"running": False, "failed": len(failures)})

@app.route("/start-translation", methods=["POST"])
def start_translation():
    if status["running"]:
        return jsonify({"status": "busy"}), 409
    chunk = max(1, int(request.args.get("chunk", 5)))
    threading.Thread(target=batch_process, args=(chunk,), daemon=True).start()
    return jsonify({"status": "started", "chunk": chunk})

@app.route("/status", methods=["GET"])
def get_status():
    return jsonify(status)

@app.route("/failed", methods=["GET"])
def get_failed():
    return jsonify({"failed_ids": failures})

@app.route("/failed/retry", methods=["POST"])
def retry_failed():
    for pid in list(failures):
        prod = {"id": pid, "images": []}
        retry = process_product(prod)
    status["failed"] = len(failures)
    return jsonify({"retried": True, "remaining_failed": len(failures)})

@app.route("/", methods=["GET"])
def health():
    return "✅ Shopify Translator is active."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
