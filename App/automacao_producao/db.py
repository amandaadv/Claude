"""Raw sqlite3 access to the exact same database and schema the C# app uses
(see 001_InitialSchema.sql). No ORM, mirroring the repository classes in
src/ProductionAutomation.Infrastructure/Catalogs and Search.
"""
import hashlib
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import paths


@contextmanager
def connect():
    conn = sqlite3.connect(paths.DATABASE_FILE_PATH)
    try:
        yield conn
    finally:
        conn.close()


_BASE_SCHEMA_STATEMENTS = [
    # This CLI was always run against a database the WPF app's own
    # migrations (001_InitialSchema.sql) had already created -- a machine
    # that never ran the WPF app has no catalogs/production_* tables at
    # all, so the ALTER TABLE calls below fail outright with "no such
    # table". CREATE TABLE IF NOT EXISTS makes a first run on a genuinely
    # empty database bootstrap the same base tables the WPF app would have,
    # while staying a no-op (as before) on a database that already has them.
    """
    CREATE TABLE IF NOT EXISTS catalogs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT NULL,
        collection TEXT NULL,
        year INTEGER NULL,
        manufacturer TEXT NULL,
        notes TEXT NULL,
        pdf_path TEXT NOT NULL,
        file_hash TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS catalog_arts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        catalog_id INTEGER NOT NULL REFERENCES catalogs(id),
        reference TEXT NULL,
        page_number INTEGER NOT NULL,
        is_composite INTEGER NOT NULL DEFAULT 0,
        original_image_path TEXT NULL,
        preview_path TEXT NULL,
        width_px INTEGER NULL,
        height_px INTEGER NULL,
        source_type TEXT NOT NULL,
        quality_score REAL NULL,
        quality_dpi REAL NULL,
        quality_pixel_dimensions TEXT NULL,
        embedding BLOB NULL,
        review_status TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_catalog_arts_catalog_id ON catalog_arts(catalog_id);",
    "CREATE INDEX IF NOT EXISTS idx_catalog_arts_reference ON catalog_arts(reference);",
    """
    CREATE TABLE IF NOT EXISTS production_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        width_mm REAL NOT NULL,
        height_mm REAL NOT NULL,
        margin_left_mm REAL NOT NULL,
        margin_right_mm REAL NOT NULL,
        margin_top_mm REAL NOT NULL,
        margin_bottom_mm REAL NOT NULL,
        spacing_h_mm REAL NOT NULL,
        spacing_v_mm REAL NOT NULL,
        keep_aspect_ratio_default INTEGER NOT NULL,
        is_default INTEGER NOT NULL DEFAULT 0
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS production_queue_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        catalog_art_id INTEGER NOT NULL REFERENCES catalog_arts(id),
        width_mm REAL NOT NULL,
        height_mm REAL NOT NULL,
        aspect_mode TEXT NOT NULL,
        status TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS productions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        operator TEXT NULL,
        profile_id INTEGER NOT NULL REFERENCES production_profiles(id),
        cdr_file_path TEXT NULL,
        status TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS production_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        production_id INTEGER NOT NULL REFERENCES productions(id),
        catalog_art_id INTEGER NOT NULL REFERENCES catalog_arts(id),
        reference TEXT NULL,
        width_mm REAL NOT NULL,
        height_mm REAL NOT NULL,
        orientation TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        page_number INTEGER NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_production_items_production_id ON production_items(production_id);",
    """
    CREATE TABLE IF NOT EXISTS ai_feedback_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query_image_path TEXT NOT NULL,
        suggested_art_id INTEGER NULL REFERENCES catalog_arts(id),
        suggested_score REAL NULL,
        correct_art_id INTEGER NOT NULL REFERENCES catalog_arts(id),
        catalog_id INTEGER NOT NULL REFERENCES catalogs(id),
        created_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS enhanced_catalog_arts (
        catalog_art_id INTEGER PRIMARY KEY REFERENCES catalog_arts(id),
        enhanced_at TEXT NOT NULL,
        backup_tag TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS product_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT NOT NULL,
        material TEXT NOT NULL,
        largura_cm REAL NOT NULL,
        altura_cm REAL NOT NULL,
        valor REAL NOT NULL,
        UNIQUE(tipo, material, largura_cm, altura_cm)
    );
    """,
]


def ensure_schema_extensions() -> None:
    """This CLI shares its database with the WPF app's original migrations
    (001_InitialSchema.sql), which don't know about the master-.cdr feature.
    Adds the one extra column it needs if it isn't already there -- safe to
    call every startup, and harmless for the WPF app since it only ever
    selects named columns, never SELECT *."""
    with connect() as conn:
        for statement in _BASE_SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.commit()

        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(catalogs);")}
        if "master_cdr_path" not in existing_columns:
            conn.execute("ALTER TABLE catalogs ADD COLUMN master_cdr_path TEXT;")
        if "published_at" not in existing_columns:
            conn.execute("ALTER TABLE catalogs ADD COLUMN published_at TEXT;")
        if "default_width_mm" not in existing_columns:
            conn.execute("ALTER TABLE catalogs ADD COLUMN default_width_mm REAL;")
        if "default_height_mm" not in existing_columns:
            conn.execute("ALTER TABLE catalogs ADD COLUMN default_height_mm REAL;")
        # Limpeza de um bug antigo: com a Tabela de Preços vazia o campo "Tipo" abria
        # escrito "CTkComboBox" (nome do componente) e isso era gravado como tipo.
        conn.execute("UPDATE catalogs SET tipo_produto = NULL WHERE tipo_produto = 'CTkComboBox';")
        if "categoria_site" not in existing_columns:
            # 'aplique' | 'faixa' | NULL -- decide, no site, quais botões de
            # tipo/medida cada figura mostra (regras em regras_medidas.json
            # no servidor). NULL = catálogo continua no "Adicionar" antigo.
            conn.execute("ALTER TABLE catalogs ADD COLUMN categoria_site TEXT;")
        if "available_sizes" not in existing_columns:
            # Comma-separated customer-facing sizes (e.g. "29cm,35cm") this
            # catalog's figures sell in -- same list applies to every REF in
            # the catalog, so it's set once here rather than per REF. The
            # site's order page still lets the customer pick a size per
            # figure she adds to the cart (see index.html); this just says
            # which options exist for the whole catalog.
            conn.execute("ALTER TABLE catalogs ADD COLUMN available_sizes TEXT;")

        queue_columns = {row[1] for row in conn.execute("PRAGMA table_info(production_queue_items);")}
        if "client_name" not in queue_columns:
            conn.execute("ALTER TABLE production_queue_items ADD COLUMN client_name TEXT;")
        if "client_phone" not in queue_columns:
            conn.execute("ALTER TABLE production_queue_items ADD COLUMN client_phone TEXT;")
        if "client_representative" not in queue_columns:
            # Nome do representante que tirou o pedido com a cliente no site
            # (ver clientes.representante no site) -- carregado junto do
            # nome/telefone pra sobreviver até a produção e, dali, até o
            # orçamento (ver do_generate_budget).
            conn.execute("ALTER TABLE production_queue_items ADD COLUMN client_representative TEXT;")
        production_item_columns = {row[1] for row in conn.execute("PRAGMA table_info(production_items);")}
        if "nominal_width_mm" not in production_item_columns:
            # Tamanho da peça ANTES de a folha esticar a linha (a produção pode esticar a largura até 20%):
            # é ele que "Gerar de novo" devolve pra fila -- senão esticaria em cima do esticado.
            conn.execute("ALTER TABLE production_items ADD COLUMN nominal_width_mm REAL;")
            conn.execute("ALTER TABLE production_items ADD COLUMN nominal_height_mm REAL;")
        if "medida_texto" not in production_item_columns:
            # Mesmo texto da fila ("Termocolante · 110 x 100 mm") gravado na produção: é o que permite
            # "Gerar de novo" devolver a peça com a MEDIDA que a cliente escolheu (e não com o tamanho
            # do catálogo). NULL = peça sem medida escolhida.
            conn.execute("ALTER TABLE production_items ADD COLUMN medida_texto TEXT;")
        if "medida_texto" not in queue_columns:
            # "Termocolante · 110 x 100 mm": tipo + medida que a cliente escolheu no site
            # pra essa peça. Só existe em pedido do site com medida escolhida (NULL nos
            # outros) -- é o que diz à tela de produção que o tamanho da peça é uma
            # ESCOLHA da cliente e não o tamanho do catálogo.
            conn.execute("ALTER TABLE production_queue_items ADD COLUMN medida_texto TEXT;")
        if "replaces_production_id" not in queue_columns:
            # Produção antiga da qual essa peça foi reenfileirada ("Gerar de
            # novo"): quando a nova produção termina, o card antigo some do
            # histórico em vez de ficar repetido (ver pa.do_generate_production).
            conn.execute("ALTER TABLE production_queue_items ADD COLUMN replaces_production_id INTEGER;")
        if "order_batch_id" not in queue_columns:
            # Agrupa as peças que vieram de UM pedido só (site, Lista de REFs, Gerar de novo,
            # Buscar Produto...). Antes a Fila de Produção agrupava só por nome+telefone, então
            # dois pedidos pendentes do MESMO cliente viravam um grupo só -- gerar produção de um
            # pedido novo arrastava junto peças esquecidas de um pedido antigo (ex: produzia faixa
            # de novo mesmo sem o pedido atual ter faixa, ou "Gerar de novo" devolvia N peças mas
            # a fila mostrava mais que isso). NULL = peça antiga de antes dessa coluna existir --
            # continua agrupada só por nome+telefone, como sempre foi.
            conn.execute("ALTER TABLE production_queue_items ADD COLUMN order_batch_id INTEGER;")
        if "created_at" not in queue_columns:
            conn.execute("ALTER TABLE production_queue_items ADD COLUMN created_at TEXT;")

        art_columns = {row[1] for row in conn.execute("PRAGMA table_info(catalog_arts);")}
        if "override_width_mm" not in art_columns:
            conn.execute("ALTER TABLE catalog_arts ADD COLUMN override_width_mm REAL;")
        if "override_height_mm" not in art_columns:
            conn.execute("ALTER TABLE catalog_arts ADD COLUMN override_height_mm REAL;")

        production_columns = {row[1] for row in conn.execute("PRAGMA table_info(productions);")}
        if "client_name" not in production_columns:
            conn.execute("ALTER TABLE productions ADD COLUMN client_name TEXT;")
        if "client_phone" not in production_columns:
            conn.execute("ALTER TABLE productions ADD COLUMN client_phone TEXT;")
        if "client_representative" not in production_columns:
            conn.execute("ALTER TABLE productions ADD COLUMN client_representative TEXT;")

        catalog_columns = {row[1] for row in conn.execute("PRAGMA table_info(catalogs);")}
        if "tipo_produto" not in catalog_columns:
            # "Aplique Baby", "Faixa Digital", etc. -- junto com "material"
            # (Textil/UV) abaixo, identifica qual linha da tabela de preços
            # (product_prices) usar pra cada REF desse catálogo no orçamento
            # (ver do_generate_budget). NULL = catálogo ainda não classificado
            # -- o orçamento avisa em vez de adivinhar um preço errado.
            conn.execute("ALTER TABLE catalogs ADD COLUMN tipo_produto TEXT;")
        if "material" not in catalog_columns:
            conn.execute("ALTER TABLE catalogs ADD COLUMN material TEXT;")

        profile_columns = {row[1] for row in conn.execute("PRAGMA table_info(production_profiles);")}
        if "material" not in profile_columns:
            # "Textil" | "UV" | NULL (perfil genérico, não amarrado a nenhum material) -- é isso
            # que deixa "Gerar produção" perguntar só o MATERIAL (o que o operador realmente
            # decide) e achar o perfil certo sozinho, em vez de pedir pra escolher entre nomes de
            # perfil que não dizem nada (ver gui_page_queue.py). Um perfil já cadastrado nas
            # larguras usadas até hoje pro Têxtil (580mm) ou pro UV (400mm) é classificado sozinho
            # aqui; qualquer outra largura fica sem material (o operador confirma em Perfis de
            # Produção se for um caso diferente).
            conn.execute("ALTER TABLE production_profiles ADD COLUMN material TEXT;")
            conn.execute("UPDATE production_profiles SET material = 'Textil' WHERE width_mm = 580;")
            conn.execute("UPDATE production_profiles SET material = 'UV' WHERE width_mm = 400;")

        if "quantity" not in queue_columns:
            # NULL means "fill one row with as many copies as fit" (the
            # original, still-default behavior); a real number means "place
            # exactly this many copies, across as many rows as it takes" --
            # see production.calculate_layout.
            conn.execute("ALTER TABLE production_queue_items ADD COLUMN quantity INTEGER;")

        # med_width/height_mm used to be NOT NULL, back when every catalog's
        # captions included a "MED WxHMM" size -- some (CATALOGO APLIQUE BABY
        # COPA COZINHA) only have "REF NNNN", no size. shape_index used to be
        # a single top-level shape index, too, before a page turned up where
        # several products share one Group (six jam jars grouped together
        # with six REF captions next to it) -- matching against the group as
        # a whole associated every REF with the same six-item image, so it
        # became shape_path, a "8,3"-style index path that can reach into
        # nested groups (see master_artwork._flatten_shapes). Sqlite can't
        # alter a column's NOT NULL or rename it away in place, so recreate
        # the table if it's still the old shape (harmless: this table is a
        # rebuildable cache, reimporting a master file regenerates it -- see
        # replace_master_ref_index).
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(master_ref_index);")}
        if columns and ("shape_path" not in columns or columns["med_width_mm"][3] == 1):
            conn.execute("DROP TABLE master_ref_index;")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS master_ref_index (
                catalog_id INTEGER NOT NULL,
                ref_number TEXT NOT NULL,
                page_index INTEGER NOT NULL,
                shape_path TEXT NOT NULL,
                med_width_mm REAL,
                med_height_mm REAL,
                PRIMARY KEY (catalog_id, ref_number)
            );
            """
        )

        if "display_order" not in existing_columns:
            conn.execute("ALTER TABLE catalogs ADD COLUMN display_order INTEGER;")
            # Backfills using whatever order these catalogs already show in
            # today (created_at DESC, get_all_catalogs()'s old sort) --
            # otherwise every catalog starting at the same NULL/0 would
            # scramble the list the first time this runs, right before the
            # operator has even touched the new reorder buttons.
            rows = conn.execute("SELECT id FROM catalogs ORDER BY created_at DESC;").fetchall()
            conn.executemany(
                "UPDATE catalogs SET display_order = ? WHERE id = ?;",
                [(i, row[0]) for i, row in enumerate(rows)],
            )

        if "is_private" not in existing_columns:
            conn.execute("ALTER TABLE catalogs ADD COLUMN is_private INTEGER NOT NULL DEFAULT 0;")

        conn.commit()


def replace_master_ref_index(catalog_id: int, entries: dict) -> None:
    """entries: {ref_number: {"page_index", "shape_path", "med_width_mm", "med_height_mm"}}."""
    with connect() as conn:
        conn.execute("DELETE FROM master_ref_index WHERE catalog_id = ?;", (catalog_id,))
        conn.executemany(
            """
            INSERT INTO master_ref_index (catalog_id, ref_number, page_index, shape_path, med_width_mm, med_height_mm)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            [
                (catalog_id, ref_number, entry["page_index"], entry["shape_path"],
                 entry["med_width_mm"], entry["med_height_mm"])
                for ref_number, entry in entries.items()
            ],
        )
        conn.commit()


def get_master_ref_entries_by_catalog(catalog_id: int):
    """Every REF this catalog's master file mapped to a shape -- for backfilling
    a size straight from the vector artwork (see pa.do_backfill_sizes_from_master)
    on catalogs whose original file had no "MED WxHMM" caption text at all,
    so med_width_mm/med_height_mm came back empty for every REF."""
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT ref_number, page_index, shape_path, med_width_mm, med_height_mm
            FROM master_ref_index WHERE catalog_id = ?;
            """,
            (catalog_id,),
        )
        return cur.fetchall()


def get_master_ref_entry(catalog_id: int, ref_number: str):
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT page_index, shape_path, med_width_mm, med_height_mm
            FROM master_ref_index WHERE catalog_id = ? AND ref_number = ?;
            """,
            (catalog_id, ref_number),
        )
        return cur.fetchone()


def _now_iso() -> str:
    # Matches DateTimeOffset.UtcNow.ToString("O") closely enough for round-tripping.
    return datetime.now(timezone.utc).isoformat()


def compute_file_hash(path: str) -> str:
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def find_catalog_by_hash(file_hash: str):
    with connect() as conn:
        cur = conn.execute(
            "SELECT id, name, status FROM catalogs WHERE file_hash = ?;", (file_hash,)
        )
        return cur.fetchone()


def get_all_catalogs():
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT c.id, c.name, c.status, c.created_at,
                   COUNT(ca.id) AS total_arts,
                   SUM(CASE WHEN ca.review_status = 'Approved' THEN 1 ELSE 0 END) AS approved_arts,
                   SUM(CASE WHEN ca.reference IS NOT NULL THEN 1 ELSE 0 END) AS arts_with_reference,
                   c.published_at
            FROM catalogs c
            LEFT JOIN catalog_arts ca ON ca.catalog_id = c.id
            GROUP BY c.id
            ORDER BY COALESCE(c.display_order, 999999), c.created_at DESC;
            """
        )
        return cur.fetchall()


def get_all_public_catalogs():
    """Same as get_all_catalogs but excludes is_private catalogs -- for pages
    that only deal with publicly-listed catalogs (Catálogos page, order pages)."""
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT c.id, c.name, c.status, c.created_at,
                   COUNT(ca.id) AS total_arts,
                   SUM(CASE WHEN ca.review_status = 'Approved' THEN 1 ELSE 0 END) AS approved_arts,
                   SUM(CASE WHEN ca.reference IS NOT NULL THEN 1 ELSE 0 END) AS arts_with_reference,
                   c.published_at
            FROM catalogs c
            LEFT JOIN catalog_arts ca ON ca.catalog_id = c.id
            WHERE (c.is_private = 0 OR c.is_private IS NULL)
            GROUP BY c.id
            ORDER BY COALESCE(c.display_order, 999999), c.created_at DESC;
            """
        )
        return cur.fetchall()


def get_all_private_catalogs():
    """Returns only is_private=1 catalogs -- for the Catálogo Personalizado page."""
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT c.id, c.name, c.status, c.created_at,
                   COUNT(ca.id) AS total_arts,
                   SUM(CASE WHEN ca.review_status = 'Approved' THEN 1 ELSE 0 END) AS approved_arts,
                   SUM(CASE WHEN ca.reference IS NOT NULL THEN 1 ELSE 0 END) AS arts_with_reference,
                   c.published_at
            FROM catalogs c
            LEFT JOIN catalog_arts ca ON ca.catalog_id = c.id
            WHERE c.is_private = 1
            GROUP BY c.id
            ORDER BY COALESCE(c.display_order, 999999), c.created_at DESC;
            """
        )
        return cur.fetchall()


def set_catalog_private(catalog_id: int, is_private: bool) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE catalogs SET is_private = ? WHERE id = ?;",
            (1 if is_private else 0, catalog_id),
        )
        conn.commit()


def rename_catalog(catalog_id: int, new_name: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE catalogs SET name = ? WHERE id = ?;", (new_name, catalog_id))
        conn.commit()


def catalog_name_exists(name: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM catalogs WHERE name = ?;", (name,)
        ).fetchone()
        return row is not None


def get_catalog_is_private(catalog_id: int) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT is_private FROM catalogs WHERE id = ?;", (catalog_id,)
        ).fetchone()
        return bool(row and row[0])


def swap_catalog_display_order(catalog_id_a: int, catalog_id_b: int) -> None:
    """Swaps two catalogs' places in the display order -- the primitive
    behind the "mover" buttons (each moves one catalog past its immediate
    neighbor in the currently-shown, already-sorted list, so a swap is
    always between two adjacent display_order values)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, display_order FROM catalogs WHERE id IN (?, ?);", (catalog_id_a, catalog_id_b)
        ).fetchall()
        order_by_id = dict(rows)
        conn.execute(
            "UPDATE catalogs SET display_order = ? WHERE id = ?;", (order_by_id[catalog_id_b], catalog_id_a))
        conn.execute(
            "UPDATE catalogs SET display_order = ? WHERE id = ?;", (order_by_id[catalog_id_a], catalog_id_b))
        conn.commit()


def reorder_catalogs(ordered_catalog_ids: list[int]) -> None:
    """Rewrites every catalog's display_order to match ordered_catalog_ids'
    position (0, 1, 2, ...) -- the primitive behind dragging a catalog card
    to an arbitrary new spot (unlike swap_catalog_display_order, which only
    ever swaps two neighbors): a drag can move a card several places at
    once, so the whole list needs renumbering, not just two rows."""
    with connect() as conn:
        conn.executemany(
            "UPDATE catalogs SET display_order = ? WHERE id = ?;",
            [(order, catalog_id) for order, catalog_id in enumerate(ordered_catalog_ids)],
        )
        conn.commit()


def mark_catalog_published(catalog_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE catalogs SET published_at = ? WHERE id = ?;", (_now_iso(), catalog_id))
        conn.commit()


def get_catalog_name(catalog_id: int) -> str | None:
    with connect() as conn:
        cur = conn.execute("SELECT name FROM catalogs WHERE id = ?;", (catalog_id,))
        row = cur.fetchone()
        return row[0] if row else None


def get_catalog_default_size(catalog_id: int) -> tuple[float, float] | None:
    """Some catalogs' master files don't record a per-REF size at all (no
    "MED WxHMM" in the caption) -- every design in them is meant to print at
    one same size. Rather than asking for that size on every single item
    forever, it can be set once here and reused automatically."""
    with connect() as conn:
        cur = conn.execute(
            "SELECT default_width_mm, default_height_mm FROM catalogs WHERE id = ?;", (catalog_id,))
        row = cur.fetchone()
        if row is None or row[0] is None or row[1] is None:
            return None
        return row[0], row[1]


def set_catalog_default_size(catalog_id: int, width_mm: float, height_mm: float) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE catalogs SET default_width_mm = ?, default_height_mm = ? WHERE id = ?;",
            (width_mm, height_mm, catalog_id))
        conn.commit()


def get_max_reference_number() -> int:
    """Highest numeric REF used anywhere across every catalog -- so a
    catalog built from scratch (see pa.do_create_catalog_from_images) can
    number its own pieces starting right after it and never collide with
    an existing REF, no matter which real catalog it happens to belong
    to. 0 when there are no references at all yet (a fresh database)."""
    with connect() as conn:
        cur = conn.execute("SELECT reference FROM catalog_arts WHERE reference IS NOT NULL;")
        highest = 0
        for (reference,) in cur.fetchall():
            match = re.search(r"(\d+)", reference)
            if match:
                highest = max(highest, int(match.group(1)))
        return highest


def insert_catalog(name: str, pdf_path: str, file_hash: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO catalogs (name, pdf_path, file_hash, status, created_at)
            VALUES (?, ?, ?, 'Processing', ?);
            """,
            (name, pdf_path, file_hash, _now_iso()),
        )
        conn.commit()
        return cur.lastrowid


def delete_abandoned_empty_catalogs() -> list[tuple[int, str]]:
    """Catalogs still 'Processing' with ZERO arts: an import that died before
    saving anything (app closed / crashed / CorelDRAW frozen mid-import). Only
    safe to call at app startup, when no import can be running in this
    process yet. Returns [(id, name)] of what was removed."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.name FROM catalogs c
            WHERE c.status = 'Processing'
              AND NOT EXISTS (SELECT 1 FROM catalog_arts a WHERE a.catalog_id = c.id);
            """
        ).fetchall()
    for catalog_id, _name in rows:
        delete_catalog(catalog_id)
    return [(r[0], r[1]) for r in rows]


def update_catalog_status(catalog_id: int, status: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE catalogs SET status = ? WHERE id = ?;", (status, catalog_id))
        conn.commit()


def delete_catalog(catalog_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM ai_feedback_log WHERE catalog_id = ?;", (catalog_id,))
        conn.execute(
            "DELETE FROM production_queue_items WHERE catalog_art_id IN "
            "(SELECT id FROM catalog_arts WHERE catalog_id = ?);",
            (catalog_id,),
        )
        conn.execute(
            "DELETE FROM production_items WHERE catalog_art_id IN "
            "(SELECT id FROM catalog_arts WHERE catalog_id = ?);",
            (catalog_id,),
        )
        conn.execute("DELETE FROM catalog_arts WHERE catalog_id = ?;", (catalog_id,))
        conn.execute("DELETE FROM catalogs WHERE id = ?;", (catalog_id,))
        conn.commit()


def insert_catalog_art(
    catalog_id: int, reference, page_number: int, original_image_path: str,
    preview_path: str, width_px: int, height_px: int, source_type: str,
    embedding_bytes: bytes, review_status: str = "Pending",
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO catalog_arts (
                catalog_id, reference, page_number, is_composite, original_image_path, preview_path,
                width_px, height_px, source_type, embedding, review_status, created_at)
            VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (catalog_id, reference, page_number, original_image_path, preview_path,
             width_px, height_px, source_type, embedding_bytes, review_status, _now_iso()),
        )
        conn.commit()
        return cur.lastrowid


def set_catalog_master_cdr_path(catalog_id: int, master_cdr_path: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE catalogs SET master_cdr_path = ? WHERE id = ?;", (master_cdr_path, catalog_id)
        )
        conn.commit()


def get_catalog_master_cdr_path(catalog_id: int) -> str | None:
    with connect() as conn:
        cur = conn.execute("SELECT master_cdr_path FROM catalogs WHERE id = ?;", (catalog_id,))
        row = cur.fetchone()
        return row[0] if row else None


def get_catalog_pdf_path(catalog_id: int) -> str | None:
    with connect() as conn:
        cur = conn.execute("SELECT pdf_path FROM catalogs WHERE id = ?;", (catalog_id,))
        row = cur.fetchone()
        return row[0] if row else None


def delete_arts_for_page(catalog_id: int, page_number: int) -> list[tuple[str | None, str | None]]:
    """Deletes every catalog_arts row for one page of one catalog (used to redo a
    single page whose vision-extracted crops came out wrong), returning the
    (original_image_path, preview_path) pairs so the caller can delete the files too."""
    with connect() as conn:
        cur = conn.execute(
            "SELECT original_image_path, preview_path FROM catalog_arts WHERE catalog_id = ? AND page_number = ?;",
            (catalog_id, page_number),
        )
        image_paths = cur.fetchall()
        conn.execute(
            "DELETE FROM catalog_arts WHERE catalog_id = ? AND page_number = ?;",
            (catalog_id, page_number),
        )
        conn.commit()
        return image_paths


def delete_catalog_art(catalog_art_id: int) -> tuple[str | None, str | None]:
    """Permanently deletes ONE design (not a whole catalog/page) -- for
    pulling a single bad piece via "Ver desenhos" without touching the rest.
    Returns (original_image_path, preview_path) so the caller can delete the
    files too; (None, None) if that id didn't exist."""
    with connect() as conn:
        cur = conn.execute(
            "SELECT catalog_id, reference, original_image_path, preview_path "
            "FROM catalog_arts WHERE id = ?;",
            (catalog_art_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None, None
        catalog_id, reference, original_path, preview_path = row

        conn.execute("DELETE FROM production_queue_items WHERE catalog_art_id = ?;", (catalog_art_id,))
        conn.execute("DELETE FROM production_items WHERE catalog_art_id = ?;", (catalog_art_id,))
        conn.execute(
            "DELETE FROM ai_feedback_log WHERE suggested_art_id = ? OR correct_art_id = ?;",
            (catalog_art_id, catalog_art_id),
        )
        if reference:
            conn.execute(
                "DELETE FROM master_ref_index WHERE catalog_id = ? AND ref_number = ?;",
                (catalog_id, _normalize_reference(reference)),
            )
        conn.execute("DELETE FROM catalog_arts WHERE id = ?;", (catalog_art_id,))
        conn.commit()
        return original_path, preview_path


# Orders by the REF's actual number (REF 2 before REF 10), not insertion
# order -- rows get inserted in whatever order build_ref_index's
# closest-pair-first matching happened to resolve captions in (see
# master_artwork._match_captions_to_shapes), which has no relation to the
# REF sequence, so id/page_number order came out looking shuffled even
# though the source file lists everything in order. Falls back to
# page_number/id for the rare row with no REF at all.
_ORDER_BY_REF_NUMBER = """
    ORDER BY CASE WHEN reference LIKE 'REF %' THEN CAST(SUBSTR(reference, 5) AS INTEGER) END,
             page_number, id
"""


def get_arts_by_catalog_id(catalog_id: int):
    with connect() as conn:
        cur = conn.execute(
            f"""
            SELECT id, reference, page_number, preview_path, review_status
            FROM catalog_arts WHERE catalog_id = ? {_ORDER_BY_REF_NUMBER};
            """,
            (catalog_id,),
        )
        return cur.fetchall()


def get_arts_with_paths_by_catalog_id(catalog_id: int):
    """Like get_arts_by_catalog_id, plus each art's original_image_path --
    for the batch image enhancer, which needs to read and overwrite the
    actual file on disk, not just show the preview."""
    with connect() as conn:
        cur = conn.execute(
            f"""
            SELECT id, reference, page_number, original_image_path, preview_path, review_status
            FROM catalog_arts WHERE catalog_id = ? {_ORDER_BY_REF_NUMBER};
            """,
            (catalog_id,),
        )
        return cur.fetchall()


def mark_art_enhanced(catalog_art_id: int, backup_tag: str) -> None:
    """Records that this figure already went through the batch image
    enhancer -- lets a stopped/closed batch resume later without redoing
    figures it already paid the OpenAI API for."""
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO enhanced_catalog_arts (catalog_art_id, enhanced_at, backup_tag)
            VALUES (?, ?, ?)
            ON CONFLICT(catalog_art_id) DO UPDATE SET enhanced_at = excluded.enhanced_at, backup_tag = excluded.backup_tag;
            """,
            (catalog_art_id, _now_iso(), backup_tag),
        )
        conn.commit()


def get_enhanced_art_ids(catalog_id: int) -> set[int]:
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT eca.catalog_art_id FROM enhanced_catalog_arts eca
            JOIN catalog_arts ca ON ca.id = eca.catalog_art_id
            WHERE ca.catalog_id = ?;
            """,
            (catalog_id,),
        )
        return {row[0] for row in cur.fetchall()}


def get_arts_with_sizes_by_catalog_id(catalog_id: int):
    """Like get_arts_by_catalog_id, plus each art's manual size override (if
    any) -- for the "ver desenhos do catálogo" browser/editor."""
    with connect() as conn:
        cur = conn.execute(
            f"""
            SELECT id, reference, page_number, preview_path, review_status,
                   override_width_mm, override_height_mm
            FROM catalog_arts WHERE catalog_id = ? {_ORDER_BY_REF_NUMBER};
            """,
            (catalog_id,),
        )
        return cur.fetchall()


def set_art_size_override(catalog_art_id: int, width_mm: float, height_mm: float) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE catalog_arts SET override_width_mm = ?, override_height_mm = ? WHERE id = ?;",
            (width_mm, height_mm, catalog_art_id))
        conn.commit()


def get_art_size_override(catalog_art_id: int) -> tuple[float, float] | None:
    with connect() as conn:
        cur = conn.execute(
            "SELECT override_width_mm, override_height_mm FROM catalog_arts WHERE id = ?;",
            (catalog_art_id,))
        row = cur.fetchone()
        if row is None or row[0] is None or row[1] is None:
            return None
        return row[0], row[1]


def get_catalog_available_sizes(catalog_id: int) -> list[str]:
    """Customer-facing sizes this catalog's figures sell in (e.g. ["29cm",
    "35cm"]) -- same list for every REF in the catalog (see
    ensure_schema_extensions). Empty list means the site shows no size picker
    for any figure in this catalog."""
    with connect() as conn:
        cur = conn.execute("SELECT available_sizes FROM catalogs WHERE id = ?;", (catalog_id,))
        row = cur.fetchone()
        if row is None or not row[0]:
            return []
        return [size.strip() for size in row[0].split(",") if size.strip()]


def set_catalog_available_sizes(catalog_id: int, sizes: list[str]) -> None:
    csv_value = ",".join(size.strip() for size in sizes if size.strip()) or None
    with connect() as conn:
        conn.execute("UPDATE catalogs SET available_sizes = ? WHERE id = ?;", (csv_value, catalog_id))
        conn.commit()


def get_catalog_categoria_site(catalog_id: int) -> str | None:
    """'aplique' | 'faixa' | None (ver ensure_schema_extensions)."""
    with connect() as conn:
        row = conn.execute("SELECT categoria_site FROM catalogs WHERE id = ?;", (catalog_id,)).fetchone()
        return row[0] if row and row[0] else None


def set_catalog_categoria_site(catalog_id: int, categoria: str | None) -> None:
    with connect() as conn:
        conn.execute("UPDATE catalogs SET categoria_site = ? WHERE id = ?;", (categoria or None, catalog_id))
        conn.commit()


def get_art_pixel_size(catalog_art_id: int) -> tuple[int, int] | None:
    """(width_px, height_px) of the art's saved image -- only used to know an
    art's proportion/orientation when it has no recorded physical size."""
    with connect() as conn:
        row = conn.execute(
            "SELECT width_px, height_px FROM catalog_arts WHERE id = ?;", (catalog_art_id,)).fetchone()
        if row and row[0] and row[1]:
            return int(row[0]), int(row[1])
        return None


def get_catalog_ids_by_name(name: str) -> list[int]:
    with connect() as conn:
        return [r[0] for r in conn.execute("SELECT id FROM catalogs WHERE name = ?;", (name,)).fetchall()]


def get_catalog_tipo_produto(catalog_id: int) -> tuple[str | None, str | None]:
    """(tipo_produto, material) -- both None if this catalog was never
    classified (see set_catalog_tipo_produto). Used by do_generate_budget to
    pick the right product_prices row for every REF in this catalog."""
    with connect() as conn:
        cur = conn.execute("SELECT tipo_produto, material FROM catalogs WHERE id = ?;", (catalog_id,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)


def set_catalog_tipo_produto(catalog_id: int, tipo_produto: str, material: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE catalogs SET tipo_produto = ?, material = ? WHERE id = ?;",
            (tipo_produto, material, catalog_id),
        )
        conn.commit()


def set_catalog_material(catalog_id: int, material: str) -> None:
    """Like set_catalog_tipo_produto, but touches ONLY material -- the "Tipo" button now asks just
    this (Têxtil Termocolante / Adesivo UV), never the free-text tipo_produto field anymore, so a
    catalog's existing tipo_produto (still used by do_generate_budget for whichever catalog had it
    set before) is never overwritten by this button."""
    with connect() as conn:
        conn.execute("UPDATE catalogs SET material = ? WHERE id = ?;", (material, catalog_id))
        conn.commit()


def get_approved_arts_by_catalogs(catalog_ids: list[int]):
    """Approved, referenced arts across one or more catalogs -- the sampling
    pool for "Gerar Pedido" (pick N pieces at random across selected
    catalogs)."""
    if not catalog_ids:
        return []
    with connect() as conn:
        placeholders = ",".join("?" for _ in catalog_ids)
        cur = conn.execute(
            f"""
            SELECT id, reference, catalog_id
            FROM catalog_arts
            WHERE review_status = 'Approved' AND reference IS NOT NULL
                  AND catalog_id IN ({placeholders});
            """,
            catalog_ids,
        )
        return cur.fetchall()


def get_all_approved_arts_with_reference():
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT id, reference, preview_path
            FROM catalog_arts
            WHERE review_status = 'Approved' AND reference IS NOT NULL
            ORDER BY catalog_id, id;
            """
        )
        return cur.fetchall()


def approve_all_with_reference(catalog_id: int) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            UPDATE catalog_arts SET review_status = 'Approved'
            WHERE catalog_id = ? AND reference IS NOT NULL AND review_status != 'Approved';
            """,
            (catalog_id,),
        )
        conn.commit()
        return cur.rowcount


def _normalize_reference(reference: str) -> str:
    # Digits only (leading zeros stripped) -- matches
    # master_artwork.normalize_ref_number's convention, so typing the bare
    # number ("23") matches a stored reference of "REF 23" ("REF23" if
    # letters were kept would never match plain "23"). "REF 2217/1" keeps
    # its "/1" as part of the key too (same as normalize_ref_number) --
    # this used to blindly concatenate EVERY digit found anywhere in the
    # string ("REF 2217/1" -> "22171"), which no real search term could
    # ever match: typing "2217" found nothing (customer/operator has no way
    # to ask for "either size"), and typing "2217/1" fared no better since
    # the digits-only strip destroys the "/" that made it a variant in the
    # first place, producing the exact same "22171" as the crude 4+1 would
    # instead of "2217/1" -- both real REF pairs (see master_artwork.
    # REF_CAPTION_PATTERN) became permanently unsearchable in Montar
    # Pedido, Buscar Produto and site order validation alike.
    match = re.search(r"(\d+)(?:\s*/\s*0*(\d+))?", reference)
    if not match:
        return ""
    base = match.group(1).lstrip("0") or "0"
    if match.group(2):
        return f"{base}/{match.group(2).lstrip('0') or '0'}"
    return base


def find_approved_arts_by_reference(reference: str, catalog_ids: list[int] | None = None):
    """Exact-ish match (ignoring case/punctuation/spacing) against approved arts'
    reference field -- much more reliable than visual similarity when the
    customer's photo has the REF number legibly printed on it.
    catalog_ids restricts the search to those catalogs -- disambiguates
    REF numbers that repeat across different catalogs; None/empty means
    search every catalog, same as before."""
    normalized_target = _normalize_reference(reference)
    if not normalized_target:
        return []

    query = """
        SELECT ca.id, c.name, ca.reference, ca.preview_path
        FROM catalog_arts ca
        JOIN catalogs c ON c.id = ca.catalog_id
        WHERE ca.review_status = 'Approved' AND ca.reference IS NOT NULL
    """
    params: tuple = ()
    if catalog_ids:
        placeholders = ",".join("?" for _ in catalog_ids)
        query += f" AND ca.catalog_id IN ({placeholders})"
        params = tuple(catalog_ids)

    with connect() as conn:
        cur = conn.execute(query, params)
        return [
            row for row in cur.fetchall()
            if _normalize_reference(row[2]) == normalized_target
        ]


def get_setting(key: str, default: str | None = None) -> str | None:
    with connect() as conn:
        cur = conn.execute("SELECT value FROM settings WHERE key = ?;", (key,))
        row = cur.fetchone()
        return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
            (key, value),
        )
        conn.commit()


def get_default_profile():
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT id, name, width_mm, height_mm, margin_left_mm, margin_right_mm,
                   margin_top_mm, margin_bottom_mm, spacing_h_mm, spacing_v_mm, material
            FROM production_profiles WHERE is_default = 1 LIMIT 1;
            """
        )
        return cur.fetchone()


def get_all_profiles():
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT id, name, width_mm, height_mm, margin_left_mm, margin_right_mm,
                   margin_top_mm, margin_bottom_mm, spacing_h_mm, spacing_v_mm, material
            FROM production_profiles ORDER BY id;
            """
        )
        return cur.fetchall()


def get_profiles_by_material(material: str):
    """Every profile tagged with this material ("Textil"/"UV") -- 0, 1 or more rows. Lets the
    caller tell apart "nobody marked this material yet" from "more than one profile shares it"
    (ambiguous -- see gui_page_queue.py), instead of collapsing both into the same None."""
    with connect() as conn:
        return conn.execute(
            """
            SELECT id, name, width_mm, height_mm, margin_left_mm, margin_right_mm,
                   margin_top_mm, margin_bottom_mm, spacing_h_mm, spacing_v_mm, material
            FROM production_profiles WHERE material = ?;
            """,
            (material,),
        ).fetchall()


def get_profile_by_material(material: str):
    """The one profile tagged with this material -- None if there's no such profile, or if more
    than one is tagged the same way (ambiguous; caller falls back to asking the operator to pick
    by name instead). Lets "Gerar produção" ask just the MATERIAL question and find the right
    profile on its own (see gui_page_queue.py)."""
    rows = get_profiles_by_material(material)
    return rows[0] if len(rows) == 1 else None


def insert_profile(
    name: str, width_mm: float, height_mm: float,
    margin_left_mm: float = 0, margin_right_mm: float = 0,
    margin_top_mm: float = 0, margin_bottom_mm: float = 0,
    spacing_h_mm: float = 0, spacing_v_mm: float = 0, make_default: bool = False,
    material: str | None = None,
) -> int:
    with connect() as conn:
        if make_default:
            conn.execute("UPDATE production_profiles SET is_default = 0;")
        cur = conn.execute(
            """
            INSERT INTO production_profiles (
                name, width_mm, height_mm, margin_left_mm, margin_right_mm,
                margin_top_mm, margin_bottom_mm, spacing_h_mm, spacing_v_mm,
                keep_aspect_ratio_default, is_default, material)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?);
            """,
            (name, width_mm, height_mm, margin_left_mm, margin_right_mm,
             margin_top_mm, margin_bottom_mm, spacing_h_mm, spacing_v_mm, 1 if make_default else 0, material),
        )
        conn.commit()
        return cur.lastrowid


def update_profile(
    profile_id: int, name: str, width_mm: float, height_mm: float,
    margin_left_mm: float, margin_right_mm: float,
    margin_top_mm: float, margin_bottom_mm: float,
    spacing_h_mm: float, spacing_v_mm: float, material: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE production_profiles SET
                name = ?, width_mm = ?, height_mm = ?, margin_left_mm = ?, margin_right_mm = ?,
                margin_top_mm = ?, margin_bottom_mm = ?, spacing_h_mm = ?, spacing_v_mm = ?, material = ?
            WHERE id = ?;
            """,
            (name, width_mm, height_mm, margin_left_mm, margin_right_mm,
             margin_top_mm, margin_bottom_mm, spacing_h_mm, spacing_v_mm, material, profile_id),
        )
        conn.commit()


def set_default_profile(profile_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE production_profiles SET is_default = 0;")
        conn.execute("UPDATE production_profiles SET is_default = 1 WHERE id = ?;", (profile_id,))
        conn.commit()


def delete_profile(profile_id: int) -> None:
    with connect() as conn:
        row = conn.execute(
            "SELECT is_default FROM production_profiles WHERE id = ?;", (profile_id,)).fetchone()
        was_default = bool(row[0]) if row else False
        conn.execute("DELETE FROM production_profiles WHERE id = ?;", (profile_id,))
        if was_default:
            # Keep the "there's always a default" invariant do_generate_production
            # relies on -- promote whatever profile is left, if any.
            next_row = conn.execute("SELECT id FROM production_profiles ORDER BY id LIMIT 1;").fetchone()
            if next_row:
                conn.execute("UPDATE production_profiles SET is_default = 1 WHERE id = ?;", (next_row[0],))
        conn.commit()


def get_art_by_id(catalog_art_id: int):
    with connect() as conn:
        cur = conn.execute(
            "SELECT id, reference, catalog_id FROM catalog_arts WHERE id = ?;", (catalog_art_id,)
        )
        return cur.fetchone()


def new_order_batch_id() -> int:
    """One fresh id per LOGICAL order (one pedido do site, one 'Lista de REFs', one 'Gerar de
    novo', one add manual) -- every item.queue added for that same order shares it, so Fila de
    Produção can group/produzir um pedido de cada vez sem arrastar peça esquecida de outro pedido
    pendente do mesmo cliente junto (era o bug: "Gerar de novo" de 49 peças aparecendo com peças a
    mais, ou faixa sendo produzida nos pedidos que não tinham faixa). Baseado no relógio (ms) --
    essa app roda local e só um pedido é criado por vez, então não precisa de uma tabela/sequência
    separada só pra isso."""
    import time
    return int(time.time() * 1000)


def add_to_production_queue(
    catalog_art_id: int, width_mm: float, height_mm: float, aspect_mode: str = "KeepAspectRatio",
    client_name: str | None = None, client_phone: str | None = None, quantity: int | None = None,
    client_representative: str | None = None, replaces_production_id: int | None = None,
    medida_texto: str | None = None, order_batch_id: int | None = None,
) -> int:
    """quantity=None (default) fills one row with as many copies as fit the
    profile's width -- same as always. A real number places exactly that
    many copies, across as many rows as needed."""
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO production_queue_items
                (catalog_art_id, width_mm, height_mm, aspect_mode, status, client_name, client_phone, quantity,
                 client_representative, replaces_production_id, medida_texto, order_batch_id, created_at)
            VALUES (?, ?, ?, ?, 'Pending', ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (catalog_art_id, width_mm, height_mm, aspect_mode, client_name, client_phone, quantity,
             client_representative, replaces_production_id, medida_texto, order_batch_id, _now_iso()),
        )
        conn.commit()
        return cur.lastrowid


def set_queue_items_client(queue_ids: list[int], client_name: str | None, client_phone: str | None) -> None:
    """Moves a whole group of pending queue rows to a different client name/phone at once -- for
    fixing a group added without a client (Buscar Produto) or with a wrong/typo'd name, straight
    from Fila de Produção, without deleting and re-adding each row (see gui_page_queue.py)."""
    if not queue_ids:
        return
    with connect() as conn:
        placeholders = ",".join("?" for _ in queue_ids)
        conn.execute(
            f"UPDATE production_queue_items SET client_name = ?, client_phone = ? WHERE id IN ({placeholders});",
            (client_name, client_phone, *queue_ids),
        )
        conn.commit()


def get_production_kinds() -> dict[int, str]:
    """{production_id: 'aplique' | 'faixa' | 'misto'} -- what each past production is made of, by the site
    category of its figures' catalogs (no category counts as aplique). For the "Produções anteriores" label:
    an order that mixes faixa and aplique is produced in TWO runs, both under the client's name."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT pi.production_id,
                   MAX(CASE WHEN c.categoria_site = 'faixa' THEN 1 ELSE 0 END),
                   MAX(CASE WHEN c.categoria_site = 'faixa' THEN 0 ELSE 1 END)
            FROM production_items pi
            JOIN catalog_arts a ON a.id = pi.catalog_art_id
            JOIN catalogs c ON c.id = a.catalog_id
            GROUP BY pi.production_id;
            """
        ).fetchall()
    kinds = {}
    for production_id, has_faixa, has_aplique in rows:
        kinds[production_id] = "misto" if has_faixa and has_aplique else ("faixa" if has_faixa else "aplique")
    return kinds


def get_queue_categories(queue_item_ids: list[int]) -> dict[int, str | None]:
    """{queue_id: 'aplique' | 'faixa' | None} -- the site category of each queue item's catalog."""
    if not queue_item_ids:
        return {}
    with connect() as conn:
        placeholders = ",".join("?" for _ in queue_item_ids)
        rows = conn.execute(
            f"""
            SELECT q.id, c.categoria_site
            FROM production_queue_items q
            JOIN catalog_arts a ON a.id = q.catalog_art_id
            JOIN catalogs c ON c.id = a.catalog_id
            WHERE q.id IN ({placeholders});
            """,
            queue_item_ids,
        ).fetchall()
        return {r[0]: r[1] for r in rows}


def get_queue_medida_texts(queue_item_ids: list[int]) -> dict[int, str]:
    """{queue_id: "Termocolante · 110 x 100 mm"} only for the given queue items whose
    size is a customer's choice from the site (see ensure_schema_extensions)."""
    if not queue_item_ids:
        return {}
    with connect() as conn:
        placeholders = ",".join("?" for _ in queue_item_ids)
        rows = conn.execute(
            f"SELECT id, medida_texto FROM production_queue_items "
            f"WHERE id IN ({placeholders}) AND medida_texto IS NOT NULL AND medida_texto <> '';",
            queue_item_ids,
        ).fetchall()
        return {r[0]: r[1] for r in rows}


def is_art_already_pending_for_client(catalog_art_id: int, client_name: str | None, client_phone: str | None) -> bool:
    """True if this same figure is already waiting in the queue for this same
    client -- used so clicking "Gerar de novo" twice on one production doesn't
    queue the whole set twice (which showed up as the same client repeated
    with double/triple the pieces)."""
    with connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM production_queue_items
            WHERE status = 'Pending' AND catalog_art_id = ?
              AND COALESCE(client_name, '') = COALESCE(?, '')
              AND COALESCE(client_phone, '') = COALESCE(?, '')
            LIMIT 1;
            """,
            (catalog_art_id, client_name, client_phone),
        ).fetchone()
        return row is not None


def get_replaced_production_ids(queue_item_ids: list[int]) -> set[int]:
    """Old productions these queue items were re-queued from ("Gerar de novo")."""
    if not queue_item_ids:
        return set()
    with connect() as conn:
        placeholders = ",".join("?" for _ in queue_item_ids)
        rows = conn.execute(
            f"SELECT DISTINCT replaces_production_id FROM production_queue_items "
            f"WHERE id IN ({placeholders}) AND replaces_production_id IS NOT NULL;",
            queue_item_ids,
        ).fetchall()
        return {r[0] for r in rows}


def count_pending_items_replacing(production_id: int) -> int:
    with connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM production_queue_items WHERE status = 'Pending' AND replaces_production_id = ?;",
            (production_id,),
        ).fetchone()[0]


def get_pending_queue_items():
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT q.id, q.catalog_art_id, ca.reference, q.width_mm, q.height_mm, ca.original_image_path, c.name,
                   ca.preview_path, q.client_name, q.client_phone, q.quantity, q.client_representative,
                   q.order_batch_id, q.created_at
            FROM production_queue_items q
            JOIN catalog_arts ca ON ca.id = q.catalog_art_id
            JOIN catalogs c ON c.id = ca.catalog_id
            WHERE q.status = 'Pending'
            ORDER BY q.id;
            """
        )
        return cur.fetchall()


def mark_queue_items_produced(queue_item_ids: list[int]) -> None:
    if not queue_item_ids:
        return
    with connect() as conn:
        placeholders = ",".join("?" for _ in queue_item_ids)
        conn.execute(
            f"UPDATE production_queue_items SET status = 'Produced' WHERE id IN ({placeholders});",
            queue_item_ids,
        )
        conn.commit()


def delete_queue_item(queue_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM production_queue_items WHERE id = ?;", (queue_id,))
        conn.commit()

def insert_production(
    profile_id: int, cdr_file_path: str | None, status: str,
    client_name: str | None = None, client_phone: str | None = None,
    client_representative: str | None = None,
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO productions
                (created_at, operator, profile_id, cdr_file_path, status, client_name, client_phone,
                 client_representative)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (_now_iso(), None, profile_id, cdr_file_path, status, client_name, client_phone,
             client_representative),
        )
        conn.commit()
        return cur.lastrowid


def get_all_productions():
    """Every past production run that actually placed pieces, newest first,
    with its profile's name and item count -- for "Produções anteriores"
    (re-queue and regenerate with a different profile, since a produced
    run's queue items are gone from get_pending_queue_items). Empty runs
    (failed before placing anything, or leftover test runs) are left out --
    nothing to re-queue from those anyway."""
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT p.id, p.created_at, p.status, p.client_name, p.client_phone,
                   pp.name, p.cdr_file_path, COUNT(pi.id) AS item_count, p.client_representative,
                   SUM(pi.quantity) AS total_figuras, COUNT(DISTINCT ca.catalog_id) AS catalog_count
            FROM productions p
            LEFT JOIN production_profiles pp ON pp.id = p.profile_id
            JOIN production_items pi ON pi.production_id = p.id
            JOIN catalog_arts ca ON ca.id = pi.catalog_art_id
            GROUP BY p.id
            ORDER BY p.created_at DESC;
            """
        )
        return cur.fetchall()


def delete_production(production_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM production_items WHERE production_id = ?;", (production_id,))
        conn.execute("DELETE FROM productions WHERE id = ?;", (production_id,))
        conn.commit()


def get_production(production_id: int):
    with connect() as conn:
        cur = conn.execute(
            "SELECT id, client_name, client_phone, client_representative FROM productions WHERE id = ?;",
            (production_id,),
        )
        return cur.fetchone()


def get_production_items(production_id: int):
    """One row per REF, quantity SUMMED across every production_items row
    for it (a REF can appear more than once -- split across pages by
    pa.do_generate_production's by_catalog mode, or just page overflow --
    each such row only holds that page's share, see pa.py's per-page
    grouping when it writes these rows). Without the SUM, do_requeue_production
    used to silently drop the quantity entirely (defaulting to "fill the row
    automatically" instead of the client's actual chosen amount) -- confirmed
    live on a real order: 5 "Gerar de novo" runs of the same 69-REF order
    produced 5 different, all-wrong totals (805, 484, 490, 630, 639) instead
    of the correct 805 every time."""
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT catalog_art_id, reference, SUM(quantity) AS quantity
            FROM production_items WHERE production_id = ?
            GROUP BY catalog_art_id, reference;
            """,
            (production_id,),
        )
        return cur.fetchall()


def get_production_items_with_catalog(production_id: int):
    """[(catalog_name, reference, total_quantity)] -- one row per catalog+REF
    of that production, quantity SUMMED across every page/row it was split
    into (same reason as get_production_items). For the WebPedido link of a
    past production, which must show exactly what was produced."""
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT c.name, pi.reference, SUM(pi.quantity)
            FROM production_items pi
            JOIN catalog_arts a ON a.id = pi.catalog_art_id
            JOIN catalogs c ON c.id = a.catalog_id
            WHERE pi.production_id = ? AND pi.reference IS NOT NULL AND pi.reference <> ''
            GROUP BY c.name, pi.reference
            ORDER BY MIN(pi.id);
            """,
            (production_id,),
        )
        return cur.fetchall()


def get_production_items_for_display(production_id: int):
    """One row per figura+tamanho+medida de uma produção já gerada (quantidade somada entre
    páginas), com nome do catálogo e imagem -- pro "Ver itens" de um card de Produções anteriores
    (ver gui_page_queue.py), mesma ideia do "Ver itens" da fila pendente."""
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT pi.catalog_art_id, pi.reference,
                   ROUND(COALESCE(pi.nominal_width_mm, pi.width_mm), 1),
                   ROUND(COALESCE(pi.nominal_height_mm, pi.height_mm), 1),
                   pi.medida_texto, SUM(pi.quantity), c.name, ca.preview_path
            FROM production_items pi
            JOIN catalog_arts ca ON ca.id = pi.catalog_art_id
            JOIN catalogs c ON c.id = ca.catalog_id
            WHERE pi.production_id = ?
            GROUP BY pi.catalog_art_id, pi.reference,
                     ROUND(COALESCE(pi.nominal_width_mm, pi.width_mm), 1),
                     ROUND(COALESCE(pi.nominal_height_mm, pi.height_mm), 1), pi.medida_texto
            ORDER BY MIN(pi.id);
            """,
            (production_id,),
        )
        return cur.fetchall()


def get_production_items_for_budget(production_id: int):
    """One row per REF (quantity summed across pages/catalogs -- see
    pa.do_generate_production's by_catalog mode, which can split one REF's
    copies across more than one production_items row), with the catalog's
    tipo_produto/material for do_generate_budget's price lookup. Deliberately
    doesn't use production_items.width_mm/height_mm for that lookup -- those
    can be stretched (see production._stretch_row_to_fill) or overridden for
    layout purposes, not the nominal size printed in the catalog."""
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT pi.catalog_art_id, pi.reference, SUM(pi.quantity) AS quantity,
                   c.tipo_produto, c.material
            FROM production_items pi
            JOIN catalog_arts ca ON ca.id = pi.catalog_art_id
            JOIN catalogs c ON c.id = ca.catalog_id
            WHERE pi.production_id = ?
            GROUP BY pi.catalog_art_id, pi.reference, c.tipo_produto, c.material
            ORDER BY MIN(pi.id);
            """,
            (production_id,),
        )
        return cur.fetchall()


def list_product_prices():
    with connect() as conn:
        cur = conn.execute(
            "SELECT id, tipo, material, largura_cm, altura_cm, valor "
            "FROM product_prices ORDER BY tipo, material, largura_cm, altura_cm;"
        )
        return cur.fetchall()


def list_distinct_price_types() -> list[str]:
    """Every "tipo" already used in the price table (e.g. "Aplique Baby",
    "Faixa Digital") -- populates the dropdown in gui_page_catalogs.py's
    "Definir tipo" dialog so the operator picks an existing one instead of
    retyping it (and risking a typo that would never match on lookup)."""
    with connect() as conn:
        cur = conn.execute("SELECT DISTINCT tipo FROM product_prices ORDER BY tipo;")
        return [row[0] for row in cur.fetchall()]


def add_product_price(tipo: str, material: str, largura_cm: float, altura_cm: float, valor: float) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO product_prices (tipo, material, largura_cm, altura_cm, valor) VALUES (?, ?, ?, ?, ?);",
            (tipo, material, largura_cm, altura_cm, valor),
        )
        conn.commit()
        return cur.lastrowid


def update_product_price(
    price_id: int, tipo: str, material: str, largura_cm: float, altura_cm: float, valor: float,
) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE product_prices SET tipo = ?, material = ?, largura_cm = ?, altura_cm = ?, valor = ? "
            "WHERE id = ?;",
            (tipo, material, largura_cm, altura_cm, valor, price_id),
        )
        conn.commit()


def delete_product_price(price_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM product_prices WHERE id = ?;", (price_id,))
        conn.commit()


def find_product_price(tipo: str | None, material: str | None, largura_cm: float, altura_cm: float) -> float | None:
    """Exact match on tipo+material+size (rounded to 1 decimal cm -- the
    price table is keyed by the nominal size printed in each catalog, e.g.
    "9x8.5", so float noise from a mm->cm conversion shouldn't ever cause a
    near-miss). None (no match, or tipo/material not set on the catalog) --
    the caller must not silently guess a price, just flag it for the
    operator to fill in by hand."""
    if not tipo or not material:
        return None
    with connect() as conn:
        cur = conn.execute(
            "SELECT valor FROM product_prices WHERE tipo = ? AND material = ? "
            "AND ROUND(largura_cm, 1) = ROUND(?, 1) AND ROUND(altura_cm, 1) = ROUND(?, 1);",
            (tipo, material, largura_cm, altura_cm),
        )
        row = cur.fetchone()
        return row[0] if row else None


def insert_production_item(
    production_id: int, catalog_art_id: int, reference, width_mm: float, height_mm: float,
    orientation: str, quantity: int, page_number: int, medida_texto: str | None = None,
    nominal_width_mm: float | None = None, nominal_height_mm: float | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO production_items (
                production_id, catalog_art_id, reference, width_mm, height_mm, orientation, quantity, page_number,
                medida_texto, nominal_width_mm, nominal_height_mm)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (production_id, catalog_art_id, reference, width_mm, height_mm, orientation, quantity, page_number,
             medida_texto, nominal_width_mm, nominal_height_mm),
        )
        conn.commit()


def get_production_items_for_requeue(production_id: int):
    """(catalog_art_id, reference, width_mm, height_mm, medida_texto, total_quantity) -- one row per
    figure + size + customer measure, quantity SUMMED across pages. width/height are the NOMINAL size
    (before the sheet stretched the row) when it was recorded. For "Gerar de novo": rows with a
    medida_texto keep the size the customer chose; rows without one go back at the catalog size."""
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT catalog_art_id, reference,
                   ROUND(COALESCE(nominal_width_mm, width_mm), 1), ROUND(COALESCE(nominal_height_mm, height_mm), 1),
                   medida_texto, SUM(quantity)
            FROM production_items WHERE production_id = ?
            GROUP BY catalog_art_id, reference, ROUND(COALESCE(nominal_width_mm, width_mm), 1),
                     ROUND(COALESCE(nominal_height_mm, height_mm), 1), medida_texto
            ORDER BY MIN(id);
            """,
            (production_id,),
        )
        return cur.fetchall()


def get_approved_search_entries():
    """Mirrors SqliteCatalogArtSearchIndex.GetApprovedEntries()."""
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT ca.id, c.name, ca.reference, ca.preview_path, ca.embedding
            FROM catalog_arts ca
            JOIN catalogs c ON c.id = ca.catalog_id
            WHERE ca.review_status = 'Approved' AND ca.embedding IS NOT NULL;
            """
        )
        return cur.fetchall()
