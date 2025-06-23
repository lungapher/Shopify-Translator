# translate_images.py

import os
import io
import base64
import requests
from PIL import Image, ImageDraw, ImageFont

from google.cloud import vision
from google.cloud import translate_v2 as translate

# Setup clients
vision_client = vision.ImageAnnotatorClient()
translate_client = translate.Client()

SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")  # like mystore.myshopify.com
SHOPIFY_TOKEN = os.getenv("SHOPIFY_ADMIN_API_TOKEN")


def detect_text(image_url):
    response = requests.get(image_url)
    image = vision.Image(content=response.content)
    result = vision_client.text_detection(image=image)
    return result.text_annotations


def translate_text(text, target_lang="en"):
    result = translate_client.translate(text, target_language=target_lang)
    return result['translatedText']


def overlay_translation(image_url, annotations):
    response = requests.get(image_url)
    image = Image.open(io.BytesIO(response.content)).convert("RGB")
    draw = ImageDraw.Draw(image)

    font = ImageFont.load_default()

    for annotation in annotations[1:]:  # [0] is the full text block
        translated = translate_text(annotation.description)
        vertices = [(v.x, v.y) for v in annotation.bounding_poly.vertices]
        x0, y0 = vertices[0]
        x1, y1 = vertices[2]

        # Draw white rectangle over original text
        draw.rectangle([x0, y0, x1, y1], fill="white")
        draw.text((x0, y0), translated, fill="black", font=font)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    buffer.seek(0)

    return buffer


def upload_to_shopify(product_id, image_bytes, original_image_id=None):
    url = f"https://{SHOPIFY_DOMAIN}/admin/api/2024-01/products/{product_id}/images.json"
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": SHOPIFY_TOKEN
    }

    # Convert image to base64
    encoded_image = base64.b64encode(image_bytes.read()).decode()

    image_data = {
        "image": {
            "attachment": encoded_image
        }
    }

    if original_image_id:
        # Replace original image
        url = f"{url}/{original_image_id}.json"
        response = requests.put(url, headers=headers, json=image_data)
    else:
        # Upload new image
        response = requests.post(url, headers=headers, json=image_data)

    return response.status_code, response.json()


def translate_all_images():
    # 1. Get all products
    products = requests.get(
        f"https://{SHOPIFY_DOMAIN}/admin/api/2024-01/products.json",
        headers={"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    ).json().get("products", [])

    failed = []

    for product in products:
        product_id = product["id"]
        for image in product["images"]:
            try:
                annotations = detect_text(image["src"])
                if not annotations:
                    continue
                translated_img = overlay_translation(image["src"], annotations)
                upload_to_shopify(product_id, translated_img, image["id"])
            except Exception as e:
                failed.append({"product_id": product_id, "image_id": image["id"], "error": str(e)})

    return {
        "status": "done",
        "failed": failed
    }
