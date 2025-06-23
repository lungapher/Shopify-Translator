import os, threading, time, base64, requests
from io import BytesIO
from flask import Flask, request, jsonify
from flask_cors import CORS
from PIL import Image, ImageDraw, ImageFont
from google.cloud import vision
from google.cloud import translate_v2 as translate

# Setup
app = Flask(__name__)
CORS(app)
SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
vision_client = vision.ImageAnnotatorClient()
translate_client = translate.Client()

KES_RATE = float(os.getenv("KES_EXCHANGE_RATE", 18.5))
MARKUP = float(os.getenv("MARKUP_PERCENT", 20))

# State tracked in-memory (for simplicity)
state = {"total": 0, "done": 0, "failed": []}
lock = threading.Lock()

def translate_text(text, src='zh', tgt='en'):
    return translate_client.translate(text or "", src, tgt)["translatedText"]

def extract_boxes(url):
    img = vision.Image(); img.source.image_uri = url
    res = vision_client.text_detection(image=img)
    return [{
        "text": a.description,
        "vertices": [(v.x, v.y) for v in a.bounding_poly.vertices]
    } for a in res.text_annotations[1:]]

def download(url):
    return Image.open(BytesIO(requests.get(url).content)).convert("RGBA")

def update_image_with_text(img, boxes):
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    for b in boxes:
        pts = b["vertices"]
        draw.polygon(pts, fill=(255,255,255,200))
        draw.text(pts[0], translate_text(b["text"]), fill="black", font=font)
    return img

def upload_image(product_id, img):
    buf = BytesIO()
    img.save(buf, format="PNG")
    payload = {"image": {"attachment": base64.b64encode(buf.getvalue()).decode()}}
    return requests.post(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/products/{product_id}/images.json",
        headers={"X-Shopify-Access-Token": SHOPIFY_API_KEY, "Content-Type": "application/json"},
        json=payload)

def process_product(p):
    pid = p["id"]
    try:
        # image logic
        for img in p.get("images", []):
            box = extract_boxes(img["src"])
            if box:
                new_img = update_image_with_text(download(img["src"]), box)
                upload_image(pid, new_img)
        # update other fields
        variants = []
        for v in p.get("variants", []):
            price = float(v["price"])
            variants.append({
                **v,
                "price": round(price * KES_RATE * (1+MARKUP/100), 0),
                "title": translate_text(v["title"]),
                "option1": translate_text(v["option1"]),
                "option2": translate_text(v.get("option2","")),
                "option3": translate_text(v.get("option3","")),
            })
        body = translate_text(p.get("body_html",""))
        title = translate_text(p.get("title",""))
        tags = ", ".join(translate_text(t) for t in p.get("tags","").split(","))
        requests.put(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/products/{pid}.json",
            headers={"X-Shopify-Access-Token": SHOPIFY_API_KEY, "Content-Type": "application/json"},
            json={"product": {"id":pid,"title":title,"body_html":body,"tags":tags,"variants":variants}}
        )
    except Exception as e:
        with lock:
            state["failed"].append({"id":pid,"error":str(e)})
    finally:
        with lock:
            state["done"] += 1

@app.route("/start-translation")
def start():
    chunk = int(request.args.get("chunk",10))
    resp = requests.get(f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?limit=250",
                        headers={"X-Shopify-Access-Token": SHOPIFY_API_KEY})
    prods = resp.json().get("products", [])
    state.update({"total": len(prods), "done": 0, "failed": []})
    threading.Thread(target=lambda: [
        process_product(p) or time.sleep(1) for p in prods
    ]).start()
    return jsonify({"status":"started","total":state["total"]})

@app.route("/status")
def status():
    return jsonify({"total": state["total"], "done": state["done"], "failed": state["failed"]})

@app.route("/failed", methods=["GET","POST"])
def retry_failed():
    if request.method=="GET":
        return jsonify(state["failed"])
    rets = []
    for item in list(state["failed"]):
        process_product({"id":item["id"], **{}})  # minimal
        rets.append(item["id"])
        with lock:
            state["failed"] = [f for f in state["failed"] if f["id"]!=item["id"]]
    return jsonify({"retried": rets})

@app.route("/")
def health():
    return "✅ running"

if __name__=="__main__":
    app.run(host="0.0.0.0", port=5000)
