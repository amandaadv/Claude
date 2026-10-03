"""Image embedding via the same CLIP ONNX model the WPF app uses, with the exact same
preprocessing as ClipImagePreprocessor.cs (resize shortest side to 224, center-crop
224x224, normalize with CLIP's mean/std) so embeddings are interchangeable with ones
already stored in the database by the C# app.
"""
import io

import numpy as np
import onnxruntime
from PIL import Image

import paths

TARGET_SIZE = 224
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

_session = None


def _get_session():
    global _session
    if _session is None:
        _session = onnxruntime.InferenceSession(paths.CLIP_VISION_MODEL_PATH)
    return _session


def preprocess(image_bytes: bytes) -> np.ndarray:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = image.size

    shortest_side = min(width, height)
    scale = TARGET_SIZE / shortest_side
    resized_width = max(TARGET_SIZE, round(width * scale))
    resized_height = max(TARGET_SIZE, round(height * scale))
    image = image.resize((resized_width, resized_height), Image.BILINEAR)

    crop_x = max(0, (resized_width - TARGET_SIZE) // 2)
    crop_y = max(0, (resized_height - TARGET_SIZE) // 2)
    image = image.crop((crop_x, crop_y, crop_x + TARGET_SIZE, crop_y + TARGET_SIZE))

    pixels = np.asarray(image, dtype=np.float32) / 255.0  # HWC, RGB
    pixels = (pixels - MEAN) / STD
    tensor = np.transpose(pixels, (2, 0, 1))  # CHW
    return tensor[np.newaxis, :, :, :].astype(np.float32)  # NCHW


def generate_embedding(image_bytes: bytes) -> np.ndarray:
    tensor = preprocess(image_bytes)
    session = _get_session()
    (embedding,) = session.run(["image_embeds"], {"pixel_values": tensor})
    return embedding[0].astype(np.float32)


def embedding_to_bytes(embedding: np.ndarray) -> bytes:
    return embedding.astype("<f4").tobytes()


def embedding_from_bytes(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype="<f4")


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)
