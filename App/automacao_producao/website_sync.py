"""Talks to the customer-facing catalog website's PHP API (babyluzconfeccao.com.br):
publishing the approved catalog for customers to browse, and pulling in what they
picked (name/phone + chosen REFs) so the operator can validate it into the local
production queue. The shared secret lives only in %LOCALAPPDATA%\\ProductionAutomation\\
(see paths.py) -- never in this repo.
"""
import base64
import time
import uuid

import requests

import hostinger_cache
import paths

API_BASE_URL = "https://babyluzconfeccao.com.br/api"


def _headers() -> dict:
    return {
        "X-Api-Secret": paths.read_website_api_secret(),
        # Identifies THIS machine, stably, regardless of its current
        # network IP -- see paths.read_or_create_machine_id and
        # get_caller_identity() on the PHP side (config.php). The site's
        # "matriz" (which machine's catalogs show to customers) used to be
        # decided by request IP alone, which broke for real: this same
        # machine's outbound connection flips between IPv4 and IPv6
        # depending on the network at the moment, so a catalog published
        # right when that flip happened silently stopped matching whatever
        # IP was on record as the matriz.
        "X-Machine-Id": paths.read_or_create_machine_id(),
    }


# Catálogo grande (centenas de figuras) NÃO vai numa requisição só: o PHP do
# site estoura tempo/memória com um pacote gigante e o catálogo ficava só
# com parte das figuras. Vai em lotes pequenos (ver publicar.php, "MODO EM
# LOTES"); o que já estava no site só é trocado no pedido final, então uma
# queda no meio nunca deixa a vitrine com o catálogo pela metade.
BATCH_MAX_ITEMS = 40
BATCH_MAX_BASE64_CHARS = 10 * 1024 * 1024  # ~7,5 MB de imagem por pedido
BATCH_RETRY_WAITS_S = (3, 8, 20, 45)
BATCH_TIMEOUT_S = 300


def _encode_product(product: dict) -> dict:
    with open(product["imagem_path"], "rb") as f:
        imagem_base64 = base64.b64encode(f.read()).decode("ascii")
    entry = {
        "referencia": product["referencia"],
        "nome": product.get("nome"),
        "imagem_base64": imagem_base64,
        "medidas": product.get("medidas") or [],
    }
    grande_bytes = product.get("imagem_grande_bytes")
    if grande_bytes:
        entry["imagem_grande_base64"] = base64.b64encode(grande_bytes).decode("ascii")
    return entry


def _server_accepts_batches() -> bool:
    """publicar.php answers GET with {"lotes": true} once it knows the batch
    protocol. An older server answers 405 -- and MUST NOT be sent batches: it
    would treat each one as a full replacement of the catalog."""
    try:
        response = requests.get(f"{API_BASE_URL}/publicar.php", headers=_headers(), timeout=30)
        return response.status_code == 200 and response.json().get("lotes") is True
    except Exception:
        return False


def _post_publish(payload: dict) -> dict:
    """One publicar.php call, retried on network errors / 5xx / a non-JSON
    reply -- safe to repeat because the server upserts by catalog+REF."""
    attempts = 1 + len(BATCH_RETRY_WAITS_S)
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.post(
                f"{API_BASE_URL}/publicar.php", json=payload, headers=_headers(), timeout=BATCH_TIMEOUT_S)
            if response.status_code >= 500:
                raise RuntimeError(f"o site respondeu erro {response.status_code}: {response.text[:200]}")
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("erro", "erro desconhecido ao publicar catálogo"))
            return data
        except (requests.RequestException, RuntimeError, ValueError) as ex:
            last_error = ex
            if isinstance(ex, requests.HTTPError) and ex.response is not None and ex.response.status_code < 500:
                raise  # 4xx: repetir não resolve
            if attempt < attempts - 1:
                wait_s = BATCH_RETRY_WAITS_S[attempt]
                print(f"  falhou ({ex}) -- tentando de novo em {wait_s}s "
                      f"(tentativa {attempt + 2}/{attempts})...", flush=True)
                time.sleep(wait_s)
    raise RuntimeError(f"Não consegui enviar depois de {attempts} tentativas: {last_error}")


def publish_catalog(
    catalogo_nome: str, products: list[dict], privado: bool = False, categoria: str | None = None,
) -> int:
    """products: [{"referencia": str, "nome": str | None, "imagem_path": str,
    "imagem_grande_bytes": bytes | None, "medidas": list[str]}, ...]. imagem_path
    is the small thumbnail used for the site's catalog grid (unchanged);
    imagem_grande_bytes, when given, is a bigger/higher-quality JPEG (see
    image_storage.generate_zoom_jpeg_bytes) used only for the site's zoom
    popup -- omitted (None) just leaves whatever zoom image that REF
    already had on the site, if any. medidas is the list of customer-facing
    sizes (e.g. ["29cm", "35cm"]) the site offers a picker for on this REF;
    empty/omitted means no size picker for it. Replaces only this catalog's
    section of the site's showcase (see publicar.php's catalogo-scoped
    upsert) -- other catalogs' sections are left untouched. Returns how many
    products were actually published. privado=True tells the PHP backend to
    hide this catalog from the public showcase (requires PHP support for the
    "privado" flag in publicar.php -- the products are uploaded either way).

    categoria ('aplique' | 'faixa' | None): decides which type/size buttons
    the site shows on each figure of this catalog (None keeps the old single
    "Adicionar"). Sent with every request, so a republish never loses it.

    No limit on catalog size: the products are sent in batches (see
    BATCH_MAX_ITEMS), each retried on its own if it fails, and the result is
    checked against what the site reports as active at the end. Falls back to
    the old single-request upload only against a server that predates batches."""
    total = len(products)

    if not _server_accepts_batches():
        print("AVISO: o site ainda não aceita envio em lotes -- enviando tudo de uma vez.")
        payload: dict = {"catalogo": catalogo_nome, "produtos": [_encode_product(p) for p in products]}
        if categoria:
            payload["categoria"] = categoria
        if privado:
            payload["privado"] = True
        response = requests.post(
            f"{API_BASE_URL}/publicar.php", json=payload, headers=_headers(), timeout=600)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("erro", "erro desconhecido ao publicar catálogo"))
        hostinger_cache.clear()
        return data["publicados"]

    session = uuid.uuid4().hex
    published = 0
    sent = 0
    batch: list[dict] = []
    batch_chars = 0

    def flush():
        nonlocal published, sent, batch, batch_chars
        if not batch:
            return
        payload = {"catalogo": catalogo_nome, "produtos": batch,
                   "lote": {"sessao": session, "ultimo": False}}
        if categoria:
            payload["categoria"] = categoria
        if privado:
            payload["privado"] = True
        first = sent + 1
        data = _post_publish(payload)
        published += data.get("publicados", 0)
        sent += len(batch)
        print(f"  enviadas {first}-{sent} de {total} figura(s)  ({sent * 100 // max(total, 1)}%)", flush=True)
        batch, batch_chars = [], 0

    print(f"Enviando {total} figura(s) em lotes de até {BATCH_MAX_ITEMS}...", flush=True)
    for product in products:
        entry = _encode_product(product)
        entry_chars = len(entry["imagem_base64"]) + len(entry.get("imagem_grande_base64", ""))
        if batch and (len(batch) >= BATCH_MAX_ITEMS or batch_chars + entry_chars > BATCH_MAX_BASE64_CHARS):
            flush()
        batch.append(entry)
        batch_chars += entry_chars
    flush()

    # Pedido final: só agora o site desativa o que sobrou do catálogo antigo.
    final_payload = {"catalogo": catalogo_nome, "produtos": [],
                     "lote": {"sessao": session, "ultimo": True}}
    if categoria:
        final_payload["categoria"] = categoria
    if privado:
        final_payload["privado"] = True
    final = _post_publish(final_payload)
    hostinger_cache.clear()

    active = final.get("ativos")
    if active is not None:
        print(f'Conferido no site: {active} figura(s) ativa(s) em "{catalogo_nome}" '
              f"(enviadas {published} de {total}).", flush=True)
        if active != published:
            print(f"AVISO: o site tem {active} figura(s) ativa(s) mas foram enviadas {published} -- "
                  f"confira o catálogo no site.", flush=True)
    return published


def create_personalized_catalog(catalog_names: list[str], cliente_nome: str) -> str:
    """Registers a personalized showcase link for one or more catalogs,
    labeled with the client's name, reachable at
    https://babyluzconfeccao.com.br/?c=<codigo>. Returns the generated
    codigo (the caller builds the full URL around it).
    catalog_names: one or more catalog names to include in the link.
    PHP receives "catalogos" (list) + "catalogo" (first, for backwards
    compat with older PHP versions that only handle a single field)."""
    response = requests.post(
        f"{API_BASE_URL}/criar_catalogo_personalizado.php",
        json={
            "catalogos": catalog_names,
            "catalogo": catalog_names[0] if catalog_names else "",
            "cliente": cliente_nome,
        },
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("erro", "erro desconhecido ao criar catálogo personalizado"))
    return data["codigo"]


def excluir_produto(catalogo_nome: str, referencia: str) -> None:
    """Removes just one product from the public showcase (by catalog + REF),
    leaving the rest of the catalog untouched -- for when a single design
    has an error and needs to disappear from the site on its own, without
    republishing or deleting the whole catalog. Deactivates rather than
    deletes the row (see excluir_catalogo)."""
    response = requests.post(
        f"{API_BASE_URL}/excluir_produto.php",
        json={"catalogo": catalogo_nome, "referencia": referencia},
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("erro", "erro desconhecido ao excluir produto do site"))
    hostinger_cache.clear()


def excluir_catalogo(catalogo_nome: str) -> None:
    """Removes a catalog's whole section from the public showcase (used when
    the catalog is deleted locally) -- deactivates rather than deletes the
    rows, so past orders referencing them stay intact."""
    response = requests.post(
        f"{API_BASE_URL}/excluir_catalogo.php",
        json={"catalogo": catalogo_nome},
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("erro", "erro desconhecido ao excluir catálogo do site"))
    hostinger_cache.clear()


def definir_ordem_catalogos(ordens: dict[str, int]) -> None:
    """ordens: {catalogo_nome: posicao}. Only changes display order on the
    public showcase (definir_ordem.php's own table) -- never touches
    produtos, so this can't accidentally affect what's shown/active."""
    response = requests.post(
        f"{API_BASE_URL}/definir_ordem.php",
        json={"ordens": [{"catalogo": nome, "ordem": ordem} for nome, ordem in ordens.items()]},
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("erro", "erro desconhecido ao definir ordem dos catálogos"))
    hostinger_cache.clear()


def definir_matriz() -> str:
    """Marks THIS machine (by its stable X-Machine-Id, see _headers) as the
    matriz -- only what it publishes shows to customers from now on. Rarely
    needed day-to-day now that identity doesn't depend on IP, but still the
    right way to deliberately switch which of the shop's machines is the
    matriz. Returns the identity value the server stored."""
    response = requests.post(f"{API_BASE_URL}/definir_matriz.php", headers=_headers(), timeout=30)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("erro", "erro desconhecido ao definir a máquina matriz"))
    return data["matriz_ip"]


def list_published_catalog_names() -> set[str]:
    """Reads meus_catalogos.php -- scoped server-side to whatever this same
    machine has published (by request IP, see excluir_catalogo.php) --
    NOT catalogo.php. catalogo.php is the public storefront now, and (once
    a matriz machine is configured) only shows THAT machine's catalogs; on
    any other machine it would look empty even though plenty is genuinely
    published, which would have made sync_catalogs() below think nothing
    needs comparing. meus_catalogos.php always reflects reality for the
    machine actually asking, matriz or not."""
    response = requests.get(f"{API_BASE_URL}/meus_catalogos.php", headers=_headers(), timeout=30)
    response.raise_for_status()
    return set(response.json())


def sync_catalogs(local_catalog_names: set[str]) -> list[str]:
    """Deactivates any catalog still showing on the site that isn't one of
    local_catalog_names -- the fix for residue left behind when the local
    database is wiped (e.g. a Windows reinstall) without each old catalog
    ever getting a proper "Excluir catálogo" click first. Refuses to run if
    local_catalog_names is empty: an empty local list is far more likely to
    mean "the local database failed to load" than "every catalog was
    genuinely deleted," and running anyway would deactivate the entire
    public showcase on that false premise."""
    if not local_catalog_names:
        raise ValueError(
            "Lista de catalogos locais vazia -- recusando sincronizar (evita apagar tudo do site "
            "por engano se o banco local nao carregou).")

    published_names = list_published_catalog_names()
    orphan_names = published_names - local_catalog_names
    for name in orphan_names:
        excluir_catalogo(name)
    return sorted(orphan_names)


def criar_link_pedido(nome: str, telefone: str) -> str:
    """Returns a code (not the full URL -- see pa.do_create_pedido_link) for
    the customer-facing "meu pedido" read-only summary page (pedido.html),
    merging every order under this exact nome+telefone. Idempotent: the
    server returns the SAME code for a nome+telefone it's already seen, so
    clicking "WebPedido" again for a repeat customer never creates a second,
    different link."""
    response = requests.post(
        f"{API_BASE_URL}/criar_link_pedido.php",
        json={"nome": nome, "telefone": telefone},
        headers=_headers(), timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("erro", "erro desconhecido ao criar link do pedido"))
    return data["codigo"]


def criar_link_pedido_producao(
    nome: str, telefone: str, escopo: str, itens: list[dict],
) -> tuple[str, list[str], int]:
    """Link "meu pedido" of ONE past production (escopo, e.g. "prod-58"):
    the page shows exactly `itens` ([{"catalogo_nome", "referencia",
    "quantidade"}, ...]) -- not every order the client ever placed. Same
    escopo again = same code, list refreshed. Returns (code, up to 50 items
    the site has no product for -- e.g. a catalog never published -- , how
    many in total); those don't appear on the page."""
    response = requests.post(
        f"{API_BASE_URL}/criar_link_pedido.php",
        json={"nome": nome, "telefone": telefone, "escopo": escopo, "itens": itens},
        headers=_headers(), timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("erro", "erro desconhecido ao criar link do pedido"))
    return data["codigo"], data.get("faltando", []), data.get("total_faltando", 0)


def list_pedidos(status: str = "pendente") -> list[dict]:
    response = requests.get(
        f"{API_BASE_URL}/pedidos.php", params={"status": status}, headers=_headers(), timeout=30)
    response.raise_for_status()
    return response.json()


def list_representantes() -> list[dict]:
    """id, nome, usuario, ativo, criado_em for every representative, active
    or not (see gui_page_representantes.py) -- never includes the password."""
    response = requests.get(f"{API_BASE_URL}/representantes.php", headers=_headers(), timeout=30)
    response.raise_for_status()
    return response.json()


def criar_representante(nome: str, usuario: str, senha: str, regiao: str = "") -> int:
    """Registers a new sales rep with login credentials for their own order
    panel (painel.html). Returns the new representative's id."""
    response = requests.post(
        f"{API_BASE_URL}/criar_representante.php",
        json={"nome": nome, "usuario": usuario, "senha": senha, "regiao": regiao},
        headers=_headers(), timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("erro", "erro desconhecido ao criar representante"))
    return data["id"]


def editar_representante(
    representante_id: int, nome: str, usuario: str, ativo: bool, regiao: str = "", nova_senha: str | None = None,
) -> None:
    """nova_senha=None (or "") keeps the current password -- only sending a
    non-empty value resets it (see editar_representante.php)."""
    payload = {"id": representante_id, "nome": nome, "usuario": usuario, "ativo": ativo, "regiao": regiao}
    if nova_senha:
        payload["senha"] = nova_senha
    response = requests.post(
        f"{API_BASE_URL}/editar_representante.php", json=payload, headers=_headers(), timeout=30)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("erro", "erro desconhecido ao editar representante"))


def excluir_representante(representante_id: int) -> None:
    """Deactivates (never deletes) -- past orders attributed to this rep
    keep their history, same reasoning as excluir_catalogo/excluir_produto."""
    response = requests.post(
        f"{API_BASE_URL}/excluir_representante.php",
        json={"id": representante_id}, headers=_headers(), timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("erro", "erro desconhecido ao excluir representante"))


def renomear_catalogo(nome_antigo: str, nome_novo: str) -> int:
    """Renames a catalog ALREADY on the site (its figures and its saved position) without re-sending a
    single image -- renomear_catalogo.php. Returns how many figures were renamed (0 = the site had no
    catalog with the old name)."""
    response = requests.post(
        f"{API_BASE_URL}/renomear_catalogo.php",
        json={"antigo": nome_antigo, "novo": nome_novo},
        headers=_headers(), timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("erro", "erro desconhecido ao renomear o catálogo no site"))
    hostinger_cache.clear()
    return int(data.get("produtos_renomeados", 0))


def definir_categoria(catalogo_nome: str, categoria: str | None) -> int:
    """Changes ONLY the category ('aplique' | 'faixa' | None to clear) of an
    already-published catalog on the site -- no images re-sent. Returns how
    many figures were updated (0 = not published from this machine)."""
    response = requests.post(
        f"{API_BASE_URL}/definir_categoria.php",
        json={"catalogo": catalogo_nome, "categoria": categoria or ""},
        headers=_headers(), timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("erro", "erro desconhecido ao definir a categoria no site"))
    hostinger_cache.clear()
    return data.get("atualizados", 0)


def remover_item_pedido(pedido_id: int, produto_id: int, item_id: int | None = None) -> None:
    """Removes one item from an order without deleting the whole order --
    for when the operator only wants to drop one design the client picked.
    item_id (when the site sent it) removes just THAT line: the same figure can
    be in an order more than once (different type/size); without it every line
    of the figure goes, as before."""
    payload = {"pedido_id": pedido_id, "produto_id": produto_id}
    if item_id is not None:
        payload["item_id"] = item_id
    response = requests.post(
        f"{API_BASE_URL}/remover_item_pedido.php",
        json=payload,
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("erro", "erro desconhecido ao remover item do pedido"))


def validar_pedido(pedido_id: int) -> None:
    _acao_pedido(pedido_id, "validar")


def excluir_pedido(pedido_id: int) -> None:
    _acao_pedido(pedido_id, "excluir")


def _acao_pedido(pedido_id: int, acao: str) -> None:
    response = requests.post(
        f"{API_BASE_URL}/pedido_acao.php",
        json={"pedido_id": pedido_id, "acao": acao},
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("erro", "erro desconhecido"))
