"""Own tables for this tool's reference/barcode data, layered on the exact
same database automacao_producao/db.py uses (see shared/paths.py). Reads
catalogs/catalog_arts read-only -- this tool never writes to them, the same
way gerador_catalogos.py never touches the database at all. label_batches
and label_references below don't exist anywhere else; nothing here
duplicates automacao_producao/db.py's tables or functions.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import paths

import ean13

# GS1's "restricted circulation number" range (200-299) is reserved for
# internal/in-store use -- any standard retail scanner reads it fine, but it
# isn't guaranteed globally unique the way a paid GS1 company prefix is.
# That's the right fit here: no GS1 registration, but still scannable at a
# checkout. 2 prefix digits + 10 sequence digits = 12, +1 check digit = 13.
EAN13_PREFIX = "20"
EAN13_SEQUENCE_DIGITS = 10

MODE_POR_DESENHO = "por_desenho"
MODE_POR_TAMANHO = "por_tamanho"

_ORDER_BY_REF_NUMBER = """
    ORDER BY CASE WHEN ca.reference LIKE 'REF %' THEN CAST(SUBSTR(ca.reference, 5) AS INTEGER) END,
             ca.page_number, ca.id
"""


@contextmanager
def connect():
    conn = sqlite3.connect(paths.DATABASE_FILE_PATH)
    try:
        yield conn
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS label_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                catalog_id INTEGER NOT NULL REFERENCES catalogs(id),
                mode TEXT NOT NULL,
                client_name TEXT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS label_references (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                catalog_art_id INTEGER NOT NULL REFERENCES catalog_arts(id),
                mode TEXT NOT NULL,
                width_mm REAL NULL,
                height_mm REAL NULL,
                sequence_number INTEGER NOT NULL UNIQUE,
                ean13_code TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                UNIQUE (catalog_art_id, mode, width_mm, height_mm)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS label_batch_items (
                batch_id INTEGER NOT NULL REFERENCES label_batches(id),
                label_reference_id INTEGER NOT NULL REFERENCES label_references(id),
                PRIMARY KEY (batch_id, label_reference_id)
            );
            """
        )
        conn.commit()


def get_catalogs_with_approved_arts():
    """Only catalogs that actually have at least one approved figure -- an
    empty catalog has nothing to put on a label."""
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT c.id, c.name, COUNT(ca.id) AS approved_count
            FROM catalogs c
            JOIN catalog_arts ca ON ca.catalog_id = c.id AND ca.review_status = 'Approved'
            GROUP BY c.id
            ORDER BY c.name;
            """
        )
        return cur.fetchall()


def get_arts_for_catalog(catalog_id: int):
    """Approved figures of one catalog, each with the size it's known at
    today (art-level override if set, else the catalog's default) -- the
    starting point offered when the user adds size variants in modo
    por_tamanho."""
    with connect() as conn:
        cur = conn.execute(
            f"""
            SELECT ca.id, ca.reference, ca.preview_path,
                   COALESCE(ca.override_width_mm, c.default_width_mm) AS width_mm,
                   COALESCE(ca.override_height_mm, c.default_height_mm) AS height_mm
            FROM catalog_arts ca
            JOIN catalogs c ON c.id = ca.catalog_id
            WHERE ca.catalog_id = ? AND ca.review_status = 'Approved'
            {_ORDER_BY_REF_NUMBER};
            """,
            (catalog_id,),
        )
        return cur.fetchall()


def get_or_create_reference(catalog_art_id: int, mode: str, width_mm: float | None, height_mm: float | None):
    """Idempotent: the same figure (+ size, in modo por_tamanho) always gets
    back the same reference/barcode instead of a new one every time a batch
    is regenerated. Returns (label_reference_id, sequence_number, ean13_code)."""
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT id, sequence_number, ean13_code FROM label_references
            WHERE catalog_art_id = ? AND mode = ? AND width_mm IS ? AND height_mm IS ?;
            """,
            (catalog_art_id, mode, width_mm, height_mm),
        )
        row = cur.fetchone()
        if row is not None:
            return row

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence_number), -1) + 1 FROM label_references;"
        ).fetchone()[0]
        code = ean13.build_ean13(EAN13_PREFIX, next_sequence, EAN13_SEQUENCE_DIGITS)

        conn.execute(
            """
            INSERT INTO label_references
                (catalog_art_id, mode, width_mm, height_mm, sequence_number, ean13_code, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (catalog_art_id, mode, width_mm, height_mm, next_sequence, code, _now_iso()),
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid();").fetchone()[0]
        return (new_id, next_sequence, code)


def create_batch(catalog_id: int, mode: str, client_name: str | None, label_reference_ids: list[int]) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO label_batches (catalog_id, mode, client_name, created_at) VALUES (?, ?, ?, ?);",
            (catalog_id, mode, client_name or None, _now_iso()),
        )
        batch_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO label_batch_items (batch_id, label_reference_id) VALUES (?, ?);",
            [(batch_id, ref_id) for ref_id in label_reference_ids],
        )
        conn.commit()
        return batch_id
