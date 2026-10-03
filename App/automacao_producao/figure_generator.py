"""Generates brand-new figures from a plain-language description -- no
input image, unlike image_enhancer.py's edit calls (same OpenAI account/
key though). Nothing here is "preserve the original": the whole image
comes from the text description alone, filtered through Baby Luz's own
visual style via STYLE_PREFIX.

Known limitation, confirmed live across several different subjects (a
baby elephant, a military sticker, a batch of teddy bears): OpenAI's
/v1/images/generations endpoint does NOT reliably honor "background":
"transparent" the way /v1/images/edits does for image_enhancer.py -- it
tends to add some kind of backdrop (a photographic blur, a vignette) even
when the prompt explicitly asks for none, or when output_format is
forced to "png". There's no reliable one-call fix for this; the only
tool that actually strips a background reliably is image_enhancer's own
edit-based call, which is too slow to run on every draft (confirmed live:
roughly as long BY ITSELF as generating an entire batch of 10 drafts).

So generation and cleanup are deliberately two separate, independently
callable steps here, not one automatic pipeline:
- generate_batch() asks for several drafts in ONE request (the API's own
  "n" parameter runs them together server-side -- confirmed live, 10
  drafts in one call took about the same wall-clock time as 3, and nowhere
  close to 10x a single draft) -- fast, but backgrounds are NOT clean.
- clean_figure() runs image_enhancer's real background removal on exactly
  ONE chosen draft. The caller (the GUI page) is what decides when to
  spend that extra time -- only on the drafts actually worth keeping,
  instead of on all of them regardless of whether they'll be used.
"""
import base64

import requests

import image_enhancer
import paths

GENERATION_ENDPOINT = "https://api.openai.com/v1/images/generations"
MODEL = "gpt-image-2"

STYLE_PREFIX = (
    "Ilustração isolada para aplique de roupa infantil, estilo Baby Luz: fofo, delicado, "
    "harmonioso, sofisticado e levemente kawaii quando o tema pedido for infantil (ou "
    "temático/realista quando o tema não for infantil, respeitando o estilo que o próprio tema "
    "sugerir). Traço limpo, nítido, alta qualidade, cores equilibradas, proporções corretas, sem "
    "deformações. Cada peça do lote deve ser um modelo/composição DIFERENTE dentro do mesmo tema e "
    "estilo pedidos -- nunca repita a mesma pose/composição. IMPORTANTE: a imagem deve conter só o "
    "desenho isolado, sem nenhum fundo -- nem cor sólida, nem gradiente, nem desfoque, nem vinheta, "
    "nem cenário, nem efeito de foto ao redor. Tema pedido: "
)


class FigureGenerationError(Exception):
    pass


def generate_batch(description: str, count: int = 10) -> list[bytes]:
    """One API call, several different drafts back (same theme/style,
    different compositions -- see STYLE_PREFIX). Raw bytes, exactly what
    the model drew -- background is NOT removed (see module docstring);
    call clean_figure() on whichever ones are actually worth keeping."""
    api_key = paths.read_openai_api_key()
    response = requests.post(
        GENERATION_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": MODEL,
            "prompt": STYLE_PREFIX + description.strip(),
            "background": "transparent",
            "output_format": "png",
            "size": "1024x1024",
            "n": count,
        },
        timeout=300,
    )
    if response.status_code != 200:
        raise FigureGenerationError(f"OpenAI retornou {response.status_code}: {response.text[:300]}")

    result = response.json()
    try:
        items = result["data"]
    except KeyError as ex:
        raise FigureGenerationError(f"Resposta inesperada da OpenAI: {result}") from ex
    return [base64.b64decode(item["b64_json"]) for item in items]


def clean_figure(raw_bytes: bytes) -> bytes:
    """Runs ONE draft through image_enhancer's real background removal --
    the slow step, deliberately never run automatically on a whole batch
    (see module docstring). Raises image_enhancer.ImageEnhanceError on
    failure -- unlike the old combined call, this does NOT silently fall
    back to the raw bytes, since the caller asked specifically for the
    cleaned version and should know if that didn't happen."""
    return image_enhancer.enhance_and_remove_background(raw_bytes)
