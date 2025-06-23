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

# Config
SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS

# Clients
vision_client = vision.ImageAnnotatorClient()
translate_client = translate.Client()

# Progress track
status = {"total":0,"done":0,"failed":0,"running":False}
failures = []

def translate_text(text, source='zh', target='en'):
    try:
        res = translate_client.translate(text, source_language=source, target_language=target)
        return res["translatedText"]
    except Exception as e:
        logging.warning(f"Translate fail: {e}")
        return text

def ocr_extract(image_url):
    img = vision.Image()
    img.source.image_uri = image_url
    res = vision_client.text_detection(image=img)
    return res.text_annotations[1:] if len(res.text_annotations)>1 else []

def process_image(product_id, image):
    image_url = image.get("src")
    for ann in ocr_extract(image_url):
        box = [(v.x, v.y) for v in ann.bounding_poly.vertices]
        text = ann.description
        img = Image.open(BytesIO(requests.get(image_url).content)).convert("RGBA")
        draw = ImageDraw.Draw(img)
        draw.polygon(box, fill="white")
        translated = translate_text(text)
        draw.text(box[0], translated, fill="black", font=ImageFont.load_default())
        buf = BytesIO()
        img.save(buf, format="PNG")
        att = base64.b64encode(buf.getvalue()).decode("utf-8")
        resp = requests.post(f"https://{SHOPIFY_STORE}/admin/api/2024-01/products/{product_id}/images.json",
                             headers={
                               "X-Shopify-Access-Token": SHOPIFY_API_KEY,
                               "Content-Type":"application/json"
                             },
                             json={"image":{"attachment":att}})
        if resp.status_code != 201:
            failures.append((product_id, image_url))
    status["done"] += 1

def batch_process(chunk):
    status.update({"running":True,"done":0,"failed":0,"total":0})
    failures.clear()
    res = requests.get(f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?limit=250",
                       headers={"X-Shopify-Access-Token":SHOPIFY_API_KEY}).json()
    prods = res["products"]
    status["total"] = len(prods)
    for i in range(0, len(prods), chunk):
        for prod in prods[i:i+chunk]:
            for img in prod.get("images", []):
                process_image(prod["id"], img)
            time.sleep(1)
    status["running"] = False
    status["failed"] = len(failures)

@app.route("/start-translation", methods=["POST"])
def start_translation():
    if status["running"]:
        return jsonify({"status":"busy"}), 409
    chunk = int(request.args.get("chunk", 5))
    thread = threading.Thread(target=batch_process, args=(chunk,))
    thread.start()
    return jsonify({"status":"started","chunk":chunk})

@app.route("/status", methods=["GET"])
def get_status():
    return jsonify(status)

@app.route("/failed", methods=["GET"])
def get_failed():
    return jsonify({"failed":failures})

@app.route("/failed/retry", methods=["POST"])
def retry_failed():
    for pid, url in list(failures):
        process_image(pid, {"src":url})
    status["failed"] = len(failures)
    return jsonify({"retried":True,"remaining_failed":len(failures)})

@app.route("/", methods=["GET"])
def health():
    return "✅ Upgraded Shopify Translator is live."

if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5000)
