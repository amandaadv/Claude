"""Calls the OpenAI vision API to read products + REF numbers off one flattened
catalog page. Same endpoint, model, prompt and response shape as
OpenAiPageVisionScanner.cs, so results match what the C# app would produce.
"""
import base64
import json
import re

import requests

ENDPOINT = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-4o-mini"

PROMPT_TEXT = (
    "This image is one page of a product catalog. It contains several separate product "
    "illustrations arranged in a grid, each with a printed reference caption below it in the "
    "format 'REF. NNNN'. For EACH product visible, return its approximate bounding box as "
    "fractions of the full image width/height (left, top, width, height, each 0.0-1.0, "
    "covering ONLY the illustration itself, NOT the caption text below it) and the reference "
    "number you read (as a plain string, e.g. \"REF. 2317\"). "
    "Return ONLY a JSON array, no other text, like: "
    "[{\"left\":0.1,\"top\":0.05,\"width\":0.35,\"height\":0.25,\"reference\":\"REF. 2317\"}]"
)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _strip_markdown_code_fence(text: str) -> str:
    trimmed = text.strip()
    if trimmed.startswith("```"):
        first_newline = trimmed.find("\n")
        last_fence = trimmed.rfind("```")
        if first_newline >= 0 and last_fence > first_newline:
            return trimmed[first_newline + 1:last_fence].strip()
    return trimmed


CUSTOMER_PHOTO_PROMPT_TEXT = (
    "This is a photo a customer sent to a print shop, showing a product they want printed "
    "(a small decorative illustration/appliqué design meant to be printed on baby clothing -- "
    "e.g. cartoon animals, flowers, food, baby-shower characters -- always a flat printed/drawn "
    "graphic, never a real photograph of a real person, animal, or physical scene). It could be: "
    "(a) a clean photo/screenshot of a SINGLE such design, possibly with a printed reference code "
    "visible somewhere in the image (format like 'REF. 2406' or similar), (b) a screenshot of a "
    "whole catalog page showing MULTIPLE distinct designs at once, (c) a photo of a physical "
    "printed item (fabric, tag) with no visible reference code, or (d) something else entirely "
    "unrelated (a selfie or photo of a real person, a random real-world object or scene, a "
    "document, an unrelated screenshot, etc). "
    "Return ONLY a JSON object with these fields: "
    "\"produto_visivel\" (boolean -- true ONLY if the image actually shows a flat decorative "
    "illustration/design of the kind described above; false for ANY photograph of a real person "
    "or real-world scene, and false whenever you are not confident it's one of these designs -- "
    "when in doubt, answer false), "
    "\"references\" (a JSON array of every reference code legible anywhere in the image, e.g. "
    "[\"REF. 2406\"] if there's exactly one, [\"REF. 2401\",\"REF. 2402\", ...] if several are "
    "visible because it's a multi-product screenshot, or [] if none is legible -- always [] when "
    "produto_visivel is false), "
    "\"note\" (a short plain-text note in Portuguese, max 15 words, describing what you see). "
    "Return ONLY the JSON object, no other text, like: "
    "{\"produto_visivel\":true,\"references\":[\"REF. 2406\"],\"note\":\"foto limpa de um produto único\"}"
)


def read_customer_photo(photo_bytes: bytes, api_key: str) -> dict:
    """Asks the vision model to read any printed reference code directly off a
    customer's photo, and flag whether multiple products are visible at once
    (e.g. a screenshot of a whole catalog page) so the caller can warn instead
    of silently guessing with a low-confidence visual match."""
    b64 = base64.b64encode(photo_bytes).decode("ascii")

    body = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": CUSTOMER_PHOTO_PROMPT_TEXT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }
        ],
        "max_tokens": 300,
    }

    response = requests.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=60,
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"] or "{}"
    cleaned = _strip_markdown_code_fence(content)
    raw = json.loads(cleaned)

    return {
        "produto_visivel": bool(raw.get("produto_visivel", True)),
        "references": [r for r in (raw.get("references") or []) if r],
        "note": raw.get("note") or "",
    }


CAPTION_PROMPT_TEXT = (
    "This image shows a small caption from a product catalog, reading something like "
    "\"ref 1207\" or \"REF 117\" -- the text may be a normal font or may have been "
    "converted to outline/curve shapes (still forming readable digits). Return ONLY the "
    "reference number, digits only, no other text. If you can't confidently read any "
    "number, return an empty response."
)


def read_caption_number(image_bytes: bytes, api_key: str) -> str | None:
    """Reads just the digits off one small caption crop (see
    master_artwork.find_curve_caption_products) -- a tiny, high-contrast,
    few-word image, nothing like the full messy catalog page scan_page was
    built for, so a plain digits-only prompt is enough. Returns None when
    the model couldn't read anything (caller skips that piece)."""
    b64 = base64.b64encode(image_bytes).decode("ascii")

    body = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": CAPTION_PROMPT_TEXT},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }
        ],
        "max_tokens": 20,
    }

    response = requests.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=30,
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"] or ""
    digits = re.search(r"\d+", content)
    return digits.group(0) if digits else None


def scan_page(page_image_bytes: bytes, api_key: str) -> list[dict]:
    """Returns a list of {left, top, width, height, reference} dicts, fractions 0-1,
    covering only the illustration (not the caption)."""
    b64 = base64.b64encode(page_image_bytes).decode("ascii")

    body = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT_TEXT},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }
        ],
        "max_tokens": 2000,
    }

    response = requests.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=120,
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"] or "[]"
    cleaned = _strip_markdown_code_fence(content)
    raw_products = json.loads(cleaned)

    products = []
    for raw in raw_products:
        left = _clamp01(raw.get("left", 0.0))
        top = _clamp01(raw.get("top", 0.0))
        width = _clamp01(min(raw.get("width", 0.0), 1 - left))
        height = _clamp01(min(raw.get("height", 0.0), 1 - top))
        products.append({
            "left": left, "top": top, "width": width, "height": height,
            "reference": raw.get("reference"),
        })
    return products
