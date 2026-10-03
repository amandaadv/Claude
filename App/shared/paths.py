"""Same on-disk locations the C#/WPF app uses (see AppPaths.cs). Reusing them means
the Python CLI and the WPF app share the same database, images, model and API key --
nothing imported here is lost when we go back to the GUI later.
"""
import os
import uuid

ROOT_FOLDER = os.path.join(os.environ["LOCALAPPDATA"], "ProductionAutomation")

DATABASE_FILE_PATH = os.path.join(ROOT_FOLDER, "app.db")
STORAGE_FOLDER = os.path.join(ROOT_FOLDER, "storage")
BACKUPS_FOLDER = os.path.join(ROOT_FOLDER, "backups")
CHATGPT_BROWSER_PROFILE_DIR = os.path.join(ROOT_FOLDER, "chatgpt_browser_profile")
MODELS_FOLDER = os.path.join(ROOT_FOLDER, "models")
CLIP_VISION_MODEL_PATH = os.path.join(MODELS_FOLDER, "clip-vit-base-patch32-vision-quantized.onnx")
OPENAI_API_KEY_FILE_PATH = os.path.join(ROOT_FOLDER, "openai-apikey.txt")
# Confusingly-similar names, two different things: WEBSITE_API_SECRET_FILE_PATH
# is the shared secret for babyluzconfeccao.com.br's OWN custom PHP endpoints
# (publicar.php etc, see website_sync.py); HPANEL_API_KEY_FILE_PATH is a
# Hostinger *hosting-platform* API token (developers.hostinger.com), used only
# to clear that site's server-side cache after a publish/delete.
WEBSITE_API_SECRET_FILE_PATH = os.path.join(ROOT_FOLDER, "hostinger-api-secret.txt")
HPANEL_API_KEY_FILE_PATH = os.path.join(ROOT_FOLDER, "hostinger-hpanel-api-key.txt")
# Identifies THIS machine to the website (see website_sync._headers's
# X-Machine-Id) so the site's "matriz" scoping (which machine's catalogs are
# the ones that show to customers) doesn't depend on this computer's public
# IP -- confirmed live that the same machine's outbound connection flips
# between an IPv4 and an IPv6 address depending on the network at the
# moment, so IP-based scoping silently dropped a catalog right when that
# flip happened during a publish. This id, once generated, never changes.
MACHINE_ID_FILE_PATH = os.path.join(ROOT_FOLDER, "machine-id.txt")

def read_openai_api_key() -> str:
    """No baked-in default on purpose -- this key is billed to Baby Luz's own
    OpenAI account, so it must never live in source (see read_hpanel_api_key
    for the same reasoning). Raises FileNotFoundError (an OSError subclass)
    if the file isn't there, matching what every caller already expects from
    this function's `except OSError` handling."""
    if not os.path.exists(OPENAI_API_KEY_FILE_PATH):
        raise FileNotFoundError(
            f"Chave da OpenAI não configurada. Crie o arquivo:\n{OPENAI_API_KEY_FILE_PATH}\ncom a chave dentro.")
    # utf-8-sig strips a leading BOM if present -- the key file was written by a
    # tool that added one, and a bare BOM character breaks the HTTP Authorization
    # header (latin-1 encoding) with a cryptic error.
    with open(OPENAI_API_KEY_FILE_PATH, "r", encoding="utf-8-sig") as f:
        return f.read().strip()


def read_website_api_secret() -> str:
    """No baked-in default on purpose -- see read_openai_api_key above."""
    if not os.path.exists(WEBSITE_API_SECRET_FILE_PATH):
        raise FileNotFoundError(
            f"Secret da API do site não configurado. Crie o arquivo:\n{WEBSITE_API_SECRET_FILE_PATH}\ncom o valor dentro.")
    with open(WEBSITE_API_SECRET_FILE_PATH, "r", encoding="utf-8-sig") as f:
        return f.read().strip()


def read_or_create_machine_id() -> str:
    if os.path.exists(MACHINE_ID_FILE_PATH):
        with open(MACHINE_ID_FILE_PATH, "r", encoding="utf-8-sig") as f:
            existing = f.read().strip()
        if existing:
            return existing
    new_id = uuid.uuid4().hex
    os.makedirs(os.path.dirname(MACHINE_ID_FILE_PATH), exist_ok=True)
    with open(MACHINE_ID_FILE_PATH, "w", encoding="utf-8") as f:
        f.write(new_id)
    return new_id


def read_hpanel_api_key() -> str | None:
    """No baked-in default here on purpose -- unlike the other two keys
    above, this one's scope is the whole Hostinger account (every site on
    it, not just babyluzconfeccao.com.br), so it shouldn't live in source.
    Returns None if the file isn't there; callers should treat cache-clear
    as best-effort, not something to fail the whole operation over."""
    if not os.path.exists(HPANEL_API_KEY_FILE_PATH):
        return None
    with open(HPANEL_API_KEY_FILE_PATH, "r", encoding="utf-8-sig") as f:
        return f.read().strip()
