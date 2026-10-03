"""Calls OpenAI's image-edit API (gpt-image-1) to upscale/sharpen one figure
and strip its background to a transparent PNG in a single request -- the
same result the shop used to get by hand through ChatGPT Plus, one figure at
a time. ChatGPT Plus itself has no API access; this uses a separate
pay-per-image OpenAI API key (see paths.read_openai_api_key()).

PROMPT is the shop's own hand-tuned Baby Luz brand prompt (their words, not
mine) -- copied verbatim from what they already use manually in ChatGPT,
since a side-by-side test showed it preserves far more of the original
figure's detail than a short generic instruction does.
"""
import base64
import io

import requests
from PIL import Image

import paths

API_URL = "https://api.openai.com/v1/images/edits"
# "chatgpt-image-latest" was tried here first (to match the ChatGPT web
# app's own model) but produced a badly distorted result via this specific
# edit endpoint -- likely a routing alias tuned for how the product calls it
# internally, not for a direct /v1/images/edits call. gpt-image-2 is a real,
# dedicated, versioned image model (gpt-image-1's successor), a safer bet
# for this same call shape.
MODEL = "gpt-image-2"

PROMPT = """Você é um assistente especializado em criação e edição de imagens para a marca Baby Luz, que vende tanto produtos infantis fofos quanto peças em outros estilos (realista, temático, etc). O catálogo inclui os dois -- não force um estilo fofo/infantil numa arte que já é realista ou de outro estilo; a prioridade é sempre respeitar e realçar o estilo que a própria imagem já tem.

Sempre que eu enviar uma imagem para melhorar, preserve ao máximo o desenho original, a composição, as proporções, as cores, os traços, os elementos, o formato e a identidade visual. Não invente novos elementos e não altere personagens, flores, animais, textos ou detalhes sem que eu peça.

Priorize imagens em alta resolução, com acabamento limpo, nítido e profissional. Corrija baixa qualidade, serrilhados, ruídos, deformações, marcas, resíduos, bordas ruins, partes borradas e imperfeições.

Remova completamente o fundo, inclusive resíduos cinza, branco, sombras de fundo, halos e áreas entre os elementos. Preserve apenas os elementos principais da arte. O resultado deve possuir transparência real, inclusive nos espaços vazados internos.

Nunca corte partes importantes da imagem. Preserve margens e mantenha todos os elementos completamente visíveis, respeitando a orientação e a composição original.

Se a arte já for no estilo fofo/infantil, mantenha um estilo fofo, delicado, harmonioso, sofisticado e levemente kawaii, com expressão agradável, acabamento suave e cores equilibradas. Se a arte já for realista, mantenha e realce o realismo -- textura, sombreado, profundidade e riqueza de detalhes como a imagem original já tem, sem simplificar pra um traço mais "desenho"/cartoon. Em qualquer estilo, animais e personagens devem possuir aparência bonita, proporcional e bem definida, evitando deformações.

Sempre considere como prioridade: preservar a originalidade, manter as cores originais, melhorar a qualidade, não deformar, não cortar, respeitar as proporções e entregar com fundo transparente.

Antes de finalizar, verifique: fundo realmente transparente; ausência de resíduos; elementos completos; bordas limpas; cores preservadas; proporções corretas; boa nitidez; ausência de deformações; composição equilibrada; nenhum detalhe importante removido."""


class ImageEnhanceError(Exception):
    pass


def _closest_size(image_bytes: bytes) -> str:
    """gpt-image-1 only accepts a few fixed output sizes -- picks the one
    closest to the source figure's own aspect ratio instead of always
    forcing a square, which was distorting/simplifying non-square figures."""
    with Image.open(io.BytesIO(image_bytes)) as image:
        width, height = image.size
    ratio = width / height
    if ratio > 1.2:
        return "1536x1024"
    if ratio < 1 / 1.2:
        return "1024x1536"
    return "1024x1024"


def enhance_and_remove_background(image_bytes: bytes) -> bytes:
    """Returns the edited image's raw PNG bytes (RGBA, transparent background)."""
    api_key = paths.read_openai_api_key()
    response = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        files={"image": ("figure.png", image_bytes, "image/png")},
        # No explicit "quality" -- forcing "high" made gpt-image-2 take well
        # over 2 minutes (the ChatGPT web app itself finishes in ~40s), so
        # its default is likely much closer to whatever quality tier the
        # web app actually uses than "high" is.
        data={
            "model": MODEL, "prompt": PROMPT, "background": "transparent",
            "size": _closest_size(image_bytes),
        },
        # gpt-image-2 at "high" quality has been slower than gpt-image-1 ever
        # was -- 120s was cutting off requests that were still genuinely
        # working server-side (and likely still got billed for, timeout or
        # not), not actually failing.
        timeout=300,
    )
    if response.status_code != 200:
        raise ImageEnhanceError(f"OpenAI retornou {response.status_code}: {response.text[:300]}")

    result = response.json()
    try:
        b64_image = result["data"][0]["b64_json"]
    except (KeyError, IndexError) as ex:
        raise ImageEnhanceError(f"Resposta inesperada da OpenAI: {result}") from ex

    return base64.b64decode(b64_image)
