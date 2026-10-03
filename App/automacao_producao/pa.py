"""Terminal CLI for the production-automation workflow: import a catalog directly
from the designer's master .cdr file (real vector art + REF captions -- no PDF,
no vision AI needed for this step anymore), and identify a product from one or
more customer photos. Reuses the same database/storage/model/API key as the WPF
app (see paths.py) so nothing done here is lost when we go back to the GUI.

Run with no arguments for a step-by-step interactive menu:
    python pa.py

Or use direct commands for scripting:
    python pa.py import-master "C:\\path\\to\\catalogo.cdr" "Nome do Catalogo"
    python pa.py list
    python pa.py identify "C:\\foto1.jpg" "C:\\foto2.jpg"
    python pa.py delete <catalog_id>
"""
import argparse
import datetime
import io
import os
import random
import shutil
import sys
import tempfile
import time
import traceback
import uuid

import openpyxl
from openpyxl.styles import Border, Font, PatternFill, Side
from PIL import Image

import clip_embedding
import coreldraw_service
import db
import file_picker
import image_storage
import master_artwork
import paths
import production
import production_generator
import vision_scanner
import website_sync


# ---------------------------------------------------------------------------
# Core actions (plain functions, used by both the argparse commands below and
# the interactive menu -- no argparse.Namespace involved here on purpose, so
# both entry points share the exact same behavior).
# ---------------------------------------------------------------------------

def _import_curve_captioned_refs(corel, master_document, ref_index: dict, api_key: str) -> int:
    """See master_artwork.find_curve_caption_products: most catalogs now
    arrive as a page full of finished raster pieces with each one's "ref
    NNN" caption converted to curves instead of live text -- build_ref_index
    (regex against live text) can't read those at all. This finds every
    such piece not already claimed by a live-text REF (some pages mix
    both), reads its caption's number via OpenAI vision (a small,
    high-contrast, few-word crop -- reads essentially perfectly), and adds
    it into ref_index in the exact same shape build_ref_index produces, so
    the rest of do_import_from_master (export/embed/save/insert below)
    handles it identically either way. These captions never carry a "MED
    WxHMM" size -- only a real vector master file does -- so every REF
    added here has none; the operator sets each piece's real production
    size afterwards via "Ver desenhos" (same as any other REF with no
    locked size). Mutates ref_index in place; returns how many were added.

    claimed_paths is keyed by (page_index, path), never by path alone: a
    shape_path is just index positions ("0,1") local to its own page, so
    page 2's first shape and page 1's first shape produce the identical
    string -- keying on the bare path wrongly treated every page after
    the first as "already claimed" and silently dropped nearly all of
    its pieces (confirmed: an 8-page-ish catalog kept only page 1's
    pieces and skipped the rest with no warning at all)."""
    claimed_paths = set()
    for entry in ref_index.values():
        entry_page_index = entry["page_index"]
        claimed_paths.update(
            (entry_page_index, p) for p in master_artwork.iter_shape_paths(entry["shape_path"]))

    added = 0
    for page_index in range(1, master_document.Pages.Count + 1):
        for candidate in master_artwork.find_curve_caption_products(master_document, page_index):
            if (page_index, candidate["artwork_shape_path"]) in claimed_paths:
                continue

            crop_path = os.path.join(tempfile.gettempdir(), f"pa_caption_{uuid.uuid4().hex}.png")
            try:
                master_artwork.export_shape_to_png(
                    corel, master_document, page_index, candidate["caption_shape_path"], crop_path)
                with open(crop_path, "rb") as f:
                    caption_bytes = f.read()
                ref_number = vision_scanner.read_caption_number(caption_bytes, api_key)
            except Exception as ex:
                print(f"  AVISO: não consegui ler a legenda de uma peça (página {page_index}): {ex}")
                continue
            finally:
                if os.path.isfile(crop_path):
                    os.remove(crop_path)

            if not ref_number:
                print(f"  AVISO: não consegui ler o número de uma legenda (página {page_index}) -- "
                      f"peça ficou de fora, confira manualmente depois.")
                continue
            ref_number = str(int(ref_number))  # normaliza sem zero a esquerda, igual normalize_ref_number

            if ref_number in ref_index:
                print(f"  AVISO: legenda lida como REF {ref_number} já existe (de outra peça) -- "
                      f"ignorando essa pra não sobrescrever.")
                continue

            ref_index[ref_number] = {
                "shape_path": candidate["artwork_shape_path"],
                "caption_shape_path": candidate["caption_shape_path"],
                "page_index": page_index,
                "med_width_mm": None,
                "med_height_mm": None,
            }
            claimed_paths.add((page_index, candidate["artwork_shape_path"]))
            added += 1
    return added


def do_import_from_master(input_path: str, name: str | None) -> int | None:
    """Creates a catalog directly from the designer's master .cdr file --
    no PDF, no vision AI involved. Every REF's caption ("REF NNN MED WxHMM")
    is matched to its nearest artwork shape (same proximity idea as the old
    PdfPigArtExtractor.FindClosestReference, just against a live CorelDRAW
    document instead of a PDF), that shape is exported as a clean transparent
    PNG straight from the vector source (no cropping guesswork, no caption
    bleed, no neighbor bleed -- the whole class of bugs the PDF+vision
    pipeline had), embedded for photo identification, and everything is
    auto-approved: there's no uncertain AI reading left to double-check.
    Accepts a .cdr file, an already-extracted folder of one, or a .zip in
    either form (see master_artwork.ensure_valid_cdr_file). Returns the new
    catalog's id on success (even a zero-REF import still creates one), or
    None if nothing was created at all."""
    input_path = input_path.strip().strip('"')
    if not os.path.exists(input_path):
        print(f"ERRO: não encontrado: {input_path}")
        return

    name = (name or "").strip() or os.path.splitext(os.path.basename(input_path.rstrip("/\\")))[0]

    with tempfile.TemporaryDirectory() as tmp_dir:
        staged_path = os.path.join(tmp_dir, "staged.cdr")
        try:
            master_artwork.ensure_valid_cdr_file(input_path, staged_path)
        except ValueError as ex:
            print(f"ERRO: {ex}")
            return

        print("Calculando hash do arquivo...")
        file_hash = db.compute_file_hash(staged_path)
        existing = db.find_catalog_by_hash(file_hash)
        if existing is not None:
            print(f"Este catálogo já foi importado: id={existing[0]}, nome='{existing[1]}', status={existing[2]}")
            print("Exclua esse catálogo primeiro se quiser reimportar.")
            return

        catalog_id = db.insert_catalog(name, input_path, file_hash)
        print(f"Catálogo criado: id={catalog_id}, nome='{name}'")

        stored_path = os.path.join(paths.STORAGE_FOLDER, "catalogs", str(catalog_id), "master.cdr")
        os.makedirs(os.path.dirname(stored_path), exist_ok=True)
        shutil.copyfile(staged_path, stored_path)

    master_document = None
    try:
        corel = coreldraw_service.CorelDrawService()
        corel.connect()
        print("Abrindo o arquivo e mapeando REF -> arte original (lê todas as páginas)...")
        master_document = corel.open_document(stored_path)
        corel.set_units(master_document)

        ref_index = master_artwork.build_ref_index(master_document)

        try:
            vision_api_key = paths.read_openai_api_key()
        except OSError:
            vision_api_key = None
        if vision_api_key:
            added = _import_curve_captioned_refs(corel, master_document, ref_index, vision_api_key)
            if added:
                print(f"{added} referência(s) adicional(is) lida(s) por IA (legendas convertidas em curva).")

        total = len(ref_index)
        print(f"{total} referência(s) encontrada(s).")

        if total == 0:
            # Nao salva nem deixa "Ready" -- um catalogo sem nenhuma REF
            # legivel nao serve pra nada (nao tem o que aprovar/publicar),
            # e antes disso ficava marcado como sucesso e o chamador
            # publicava automaticamente um catalogo vazio no site.
            print("AVISO: nenhuma legenda 'REF ... MED ...' encontrada -- confira se é o arquivo certo.")
            print("Esse arquivo nao vai ser salvo como catalogo (0 referencias, nada pra aprovar/publicar).")
            db.delete_catalog(catalog_id)
            return None

        import_start = time.time()
        imported_refs = {}
        failed_refs = []
        for i, (ref_number, entry) in enumerate(ref_index.items(), start=1):
            print(f"  REF {ref_number}...", end=" ", flush=True)

            # CorelDRAW's COM automation occasionally throws a bare, transient
            # "unexpected error" on a single shape (seen live: Copy() failing
            # once then working fine when retried moments later on the exact
            # same shape) -- without a retry, that one hiccup used to abort
            # the entire import and lose every other REF's already-completed
            # work too. Retries absorb that; a REF that still fails after all
            # of them gets skipped (not the whole batch). 6 tries with a
            # growing wait (2/4/8/16/24s) instead of the original 3 short
            # ones (1.5/3s) -- seen live on a big/heavy master file (lots of
            # memory pressure) that 3 quick retries weren't always enough to
            # ride out whatever CorelDRAW was doing, but waiting longer was.
            last_error = None
            RETRY_WAITS_S = (2, 4, 8, 16, 24)
            for attempt in range(1 + len(RETRY_WAITS_S)):
                try:
                    # ref_number pode ter "/" (REF.2212/1, REF.2212/2 -- ver
                    # master_artwork.REF_CAPTION_PATTERN) -- usado cru aqui
                    # virava separador de pasta no caminho do arquivo
                    # temporário e o export falhava com "arquivo não
                    # encontrado" (a pasta "..._2212" nunca existiu).
                    safe_ref = ref_number.replace("/", "-")
                    export_tmp = os.path.join(
                        tempfile.gettempdir(), f"pa_master_export_{catalog_id}_{safe_ref}.png")
                    master_artwork.export_shape_to_png(
                        corel, master_document, entry["page_index"], entry["shape_path"], export_tmp)

                    with open(export_tmp, "rb") as f:
                        image_bytes = f.read()
                    os.remove(export_tmp)

                    embedding = clip_embedding.generate_embedding(image_bytes)
                    embedding_bytes = clip_embedding.embedding_to_bytes(embedding)

                    with Image.open(io.BytesIO(image_bytes)) as im:
                        width_px, height_px = im.size

                    original_path, preview_path = image_storage.save_art_images(
                        catalog_id, entry["page_index"], i, image_bytes)

                    db.insert_catalog_art(
                        catalog_id, f"REF {ref_number}", entry["page_index"], original_path, preview_path,
                        width_px, height_px, "MasterCdrShape", embedding_bytes, review_status="Approved")
                    imported_refs[ref_number] = entry
                    last_error = None
                    break
                except Exception as ex:
                    last_error = ex
                    if attempt < len(RETRY_WAITS_S):
                        time.sleep(RETRY_WAITS_S[attempt])

            if last_error is not None:
                failed_refs.append(ref_number)
                print(f"FALHOU ({last_error}) -- pulando essa REF, continuando as demais.")
            else:
                print("ok")
            _print_progress(i, total, import_start)

        db.replace_master_ref_index(catalog_id, imported_refs)
        db.set_catalog_master_cdr_path(catalog_id, stored_path)
        db.update_catalog_status(catalog_id, "Ready")

        print(f"\nImportação concluída: catálogo id={catalog_id}, {len(imported_refs)}/{total} arte(s) "
              f"importada(s), todas aprovadas automaticamente.")
        if failed_refs:
            print(f"AVISO: {len(failed_refs)} REF(s) falharam mesmo após tentar de novo e ficaram de fora: "
                  f"{', '.join(failed_refs)}. Tente reimportar o mesmo arquivo se quiser essas também.")

        return catalog_id

    except Exception:
        db.update_catalog_status(catalog_id, "Failed")
        raise

    finally:
        # Nunca fechava o documento depois de importar -- num app onde a
        # pessoa importa vários catálogos seguidos pela tela, isso ia
        # empilhando arquivo aberto em cima de arquivo aberto no mesmo
        # CorelDRAW (alguns de GBs), deixando tudo cada vez mais pesado e
        # lento pro proximo import. Fecha sem salvar (Documents.Close ja
        # descarta mudancas nao commitadas) assim que este import termina,
        # com sucesso, 0 referencias ou erro -- em qualquer um desses casos
        # o arquivo original ja foi copiado pra stored_path antes disso.
        if master_document is not None:
            try:
                master_document.Close()
            except Exception:
                pass


def _rmtree_with_retry(path: str) -> None:
    """Deletes a temp directory, retrying through the brief window right
    after it's written where Windows Defender/Search can still hold a
    scan lock on a file inside it -- seen in practice on the SECOND file
    of a multi-file import, when the first file's export loop (30+ PNG
    exports via CorelDRAW COM) keeps the scanner busy on the Temp folder
    long enough that it's still catching up when the next file's own
    tiny staged.cdr gets created and immediately deleted. A transient
    race, not a real failure, so it's logged and skipped rather than
    crashing an otherwise-successful import."""
    wait_times_s = (0.5, 1, 2, 4)
    for wait_s in wait_times_s:
        try:
            shutil.rmtree(path)
            return
        except (PermissionError, OSError):
            time.sleep(wait_s)
    try:
        shutil.rmtree(path)
    except (PermissionError, OSError) as ex:
        print(f"AVISO: não consegui limpar a pasta temporária '{path}' ({ex}) -- ignorando.")


def do_import_from_multiple_masters(input_paths: list[str], name: str) -> int | None:
    """Wrapper: if the import blows up (CorelDRAW frozen/closed, unreadable
    file, ...) before a single art was saved, the empty "Processing" catalog
    row it already created is removed instead of being left behind as a
    zero-figure card in "Catálogos". Catalogs that already got some arts are
    kept -- the operator decides what to do with a partial one."""
    created: dict = {}
    try:
        return _import_from_multiple_masters(input_paths, name, created)
    except BaseException:
        catalog_id = created.get("id")
        if catalog_id is not None and not db.get_arts_with_paths_by_catalog_id(catalog_id):
            db.delete_catalog(catalog_id)
            image_storage.delete_catalog_images(catalog_id)
            print(f"Importação interrompida antes de importar qualquer figura -- "
                  f"catálogo vazio {catalog_id} removido.")
        raise


def _import_from_multiple_masters(input_paths: list[str], name: str, created: dict) -> int | None:
    """Like do_import_from_master, but for SEVERAL designer master files
    at once, all landing in ONE new catalog instead of one catalog per
    file -- "escolher vários arquivos no computador e importar tudo num
    catálogo só", not picking among catalogs already in the system.

    Same REF-reading per file as a single import (build_ref_index, then
    the curve-caption vision fallback -- see _import_curve_captioned_refs)
    -- but a REF that repeats across two of the chosen files (each file's
    own numbering can collide by coincidence) only enters once: whichever
    file supplied it first is kept, same "first one wins" rule
    do_merge_catalogs already uses for the same reason.

    Unlike a single-file import, this catalog has no ONE master .cdr of
    its own (there are several here, so set_catalog_master_cdr_path/
    replace_master_ref_index are deliberately never called) -- each art's
    real size (from its own file's "MED WxHMM" caption when present, or
    measured straight off the vector shape otherwise -- get_shape_bbox_size,
    same fallback gerador_catalogos.py already uses) is saved directly as
    a manual size override instead, so get_locked_size_for_art still finds
    a real size either way. Production later re-exports from the already-
    saved PNG for these arts (the same "kind": "file" fallback already
    used for any catalog with no master file at all), not by reopening
    any of the original designer files again.

    Returns the new catalog's id, or None if nothing was imported from
    any of the files at all (no catalog is left behind in that case)."""
    valid_paths = []
    for raw_path in input_paths:
        clean_path = raw_path.strip().strip('"')
        if not os.path.exists(clean_path):
            print(f"AVISO: não encontrado, ignorando: {clean_path}")
            continue
        valid_paths.append(clean_path)
    if not valid_paths:
        print("ERRO: nenhum arquivo válido informado.")
        return None

    name = (name or "").strip() or "Catálogo importado"
    unique_marker = f"merged-import-{uuid.uuid4().hex}"
    catalog_id = db.insert_catalog(name, valid_paths[0], unique_marker)
    created["id"] = catalog_id
    print(f"Catálogo criado: id={catalog_id}, nome='{name}'")

    corel = coreldraw_service.CorelDrawService()
    corel.connect()

    claimed_references: set[str] = set()
    next_index = 0
    total_imported = 0
    total_failed = 0
    RETRY_WAITS_S = (2, 4, 8, 16, 24)

    for file_number, input_path in enumerate(valid_paths, start=1):
        print(f"\n=== Arquivo {file_number}/{len(valid_paths)}: '{os.path.basename(input_path)}' ===")
        master_document = None
        try:
            tmp_dir = tempfile.mkdtemp()
            try:
                staged_path = os.path.join(tmp_dir, "staged.cdr")
                try:
                    master_artwork.ensure_valid_cdr_file(input_path, staged_path)
                except ValueError as ex:
                    print(f"ERRO: {ex} -- pulando esse arquivo.")
                    continue

                stored_path = os.path.join(
                    paths.STORAGE_FOLDER, "catalogs", str(catalog_id), f"master_{file_number}.cdr")
                os.makedirs(os.path.dirname(stored_path), exist_ok=True)
                shutil.copyfile(staged_path, stored_path)
            finally:
                _rmtree_with_retry(tmp_dir)

            master_document = corel.open_document(stored_path)
            corel.set_units(master_document)

            ref_index = master_artwork.build_ref_index(master_document)
            try:
                vision_api_key = paths.read_openai_api_key()
            except OSError:
                vision_api_key = None
            if vision_api_key:
                added = _import_curve_captioned_refs(corel, master_document, ref_index, vision_api_key)
                if added:
                    print(f"{added} referência(s) adicional(is) lida(s) por IA (legendas convertidas em curva).")

            print(f"{len(ref_index)} referência(s) encontrada(s) nesse arquivo.")

            for ref_number, entry in ref_index.items():
                reference = f"REF {ref_number}"
                if reference in claimed_references:
                    print(f"  {reference}: já existe nesse catálogo (de outro arquivo) -- ignorando essa.")
                    continue

                width_mm, height_mm = entry["med_width_mm"], entry["med_height_mm"]
                if width_mm is None or height_mm is None:
                    try:
                        width_mm, height_mm = master_artwork.get_shape_bbox_size(
                            master_document, entry["page_index"], entry["shape_path"])
                    except Exception:
                        width_mm = height_mm = None

                next_index += 1
                print(f"  {reference}...", end=" ", flush=True)
                last_error = None
                for attempt in range(1 + len(RETRY_WAITS_S)):
                    try:
                        export_tmp = os.path.join(
                            tempfile.gettempdir(), f"pa_multi_import_{catalog_id}_{next_index}.png")
                        master_artwork.export_shape_to_png(
                            corel, master_document, entry["page_index"], entry["shape_path"], export_tmp)
                        with open(export_tmp, "rb") as f:
                            image_bytes = f.read()
                        os.remove(export_tmp)

                        embedding = clip_embedding.generate_embedding(image_bytes)
                        embedding_bytes = clip_embedding.embedding_to_bytes(embedding)
                        with Image.open(io.BytesIO(image_bytes)) as im:
                            width_px, height_px = im.size

                        original_path, preview_path = image_storage.save_art_images(
                            catalog_id, entry["page_index"], next_index, image_bytes)

                        art_id = db.insert_catalog_art(
                            catalog_id, reference, entry["page_index"], original_path, preview_path,
                            width_px, height_px, "MasterCdrShape", embedding_bytes, review_status="Approved")
                        if width_mm is not None and height_mm is not None:
                            db.set_art_size_override(art_id, width_mm, height_mm)
                        claimed_references.add(reference)
                        total_imported += 1
                        last_error = None
                        break
                    except Exception as ex:
                        last_error = ex
                        if attempt < len(RETRY_WAITS_S):
                            time.sleep(RETRY_WAITS_S[attempt])

                if last_error is not None:
                    total_failed += 1
                    print(f"FALHOU ({last_error}) -- pulando essa REF.")
                else:
                    print("ok")
        finally:
            if master_document is not None:
                try:
                    master_document.Close()
                except Exception:
                    pass

    if total_imported == 0:
        db.delete_catalog(catalog_id)
        print("\nNenhuma referência foi importada de nenhum arquivo -- catálogo não foi criado.")
        return None

    db.update_catalog_status(catalog_id, "Ready")
    print(f"\nImportação concluída: catálogo id={catalog_id} '{name}', {total_imported} arte(s) importada(s) "
          f"de {len(valid_paths)} arquivo(s).")
    if total_failed:
        print(f"AVISO: {total_failed} REF(s) falharam e ficaram de fora.")
    return catalog_id


def do_add_new_arts_to_catalog(catalog_id: int, input_path: str) -> tuple[int, int] | None:
    """Adds only the REFs from input_path's master .cdr that catalog_id
    doesn't already have -- any REF already present in the catalog is left
    completely untouched (never re-imported, never overwritten). For a
    designer's working file that keeps growing over time: pick the updated
    file again and only what's actually new comes in, instead of a full
    separate catalog per update or a manual side-by-side comparison.

    Same REF-reading pipeline as do_import_from_master (build_ref_index +
    vision curve-caption fallback), landing in the EXISTING catalog_id
    instead of a new one. New arts get their size saved as a manual
    override (like do_import_from_multiple_masters) rather than replacing
    this catalog's own master_cdr_path/ref index -- the catalog likely
    already has its own separate master file from its original import, and
    overwriting that here would break re-export for the arts already in it.

    Returns (added, skipped) counts, or None if the catalog doesn't exist or
    the file couldn't be read at all."""
    catalog_row = next((row for row in db.get_all_catalogs() if row[0] == catalog_id), None)
    if catalog_row is None:
        print(f"ERRO: catálogo {catalog_id} não encontrado.")
        return None

    input_path = input_path.strip().strip('"')
    if not os.path.exists(input_path):
        print(f"ERRO: não encontrado: {input_path}")
        return None

    existing_arts = db.get_arts_with_paths_by_catalog_id(catalog_id)
    existing_refs = {reference for _id, reference, *_rest in existing_arts if reference}
    # Starts well past any index this catalog's original import could have
    # used for its own image filenames (see image_storage.save_art_images --
    # filename is "p{page_number}-{index}", and this new file's own page
    # numbers restart at 1, so only the index half is relied on to avoid
    # silently overwriting an existing art's picture on disk).
    next_file_index = len(existing_arts) + 100000

    with tempfile.TemporaryDirectory() as tmp_dir:
        staged_path = os.path.join(tmp_dir, "staged.cdr")
        try:
            master_artwork.ensure_valid_cdr_file(input_path, staged_path)
        except ValueError as ex:
            print(f"ERRO: {ex}")
            return None

        added_master_path = os.path.join(
            paths.STORAGE_FOLDER, "catalogs", str(catalog_id), f"added_{uuid.uuid4().hex[:8]}.cdr")
        os.makedirs(os.path.dirname(added_master_path), exist_ok=True)
        shutil.copyfile(staged_path, added_master_path)

    master_document = None
    corel = coreldraw_service.CorelDrawService()
    corel.connect()
    added = 0
    skipped = 0
    failed_refs = []
    try:
        master_document = corel.open_document(added_master_path)
        corel.set_units(master_document)

        ref_index = master_artwork.build_ref_index(master_document)
        try:
            vision_api_key = paths.read_openai_api_key()
        except OSError:
            vision_api_key = None
        if vision_api_key:
            extra = _import_curve_captioned_refs(corel, master_document, ref_index, vision_api_key)
            if extra:
                print(f"{extra} referência(s) adicional(is) lida(s) por IA (legendas convertidas em curva).")

        print(f"{len(ref_index)} referência(s) encontrada(s) no arquivo escolhido.")

        RETRY_WAITS_S = (2, 4, 8, 16, 24)
        for ref_number, entry in ref_index.items():
            reference = f"REF {ref_number}"
            if reference in existing_refs:
                print(f"  {reference}: já existe nesse catálogo -- ignorando.")
                skipped += 1
                continue

            width_mm, height_mm = entry["med_width_mm"], entry["med_height_mm"]
            if width_mm is None or height_mm is None:
                try:
                    width_mm, height_mm = master_artwork.get_shape_bbox_size(
                        master_document, entry["page_index"], entry["shape_path"])
                except Exception:
                    width_mm = height_mm = None

            print(f"  {reference}...", end=" ", flush=True)
            last_error = None
            for attempt in range(1 + len(RETRY_WAITS_S)):
                try:
                    # ref_number pode ter "/" (REF.2212/1 -- ver master_artwork.
                    # REF_CAPTION_PATTERN); cru aqui viraria separador de pasta
                    # no caminho do arquivo temporário.
                    safe_ref = ref_number.replace("/", "-")
                    export_tmp = os.path.join(
                        tempfile.gettempdir(), f"pa_add_arts_{catalog_id}_{safe_ref}.png")
                    master_artwork.export_shape_to_png(
                        corel, master_document, entry["page_index"], entry["shape_path"], export_tmp)
                    with open(export_tmp, "rb") as f:
                        image_bytes = f.read()
                    os.remove(export_tmp)

                    embedding = clip_embedding.generate_embedding(image_bytes)
                    embedding_bytes = clip_embedding.embedding_to_bytes(embedding)
                    with Image.open(io.BytesIO(image_bytes)) as im:
                        width_px, height_px = im.size

                    next_file_index += 1
                    original_path, preview_path = image_storage.save_art_images(
                        catalog_id, entry["page_index"], next_file_index, image_bytes)

                    art_id = db.insert_catalog_art(
                        catalog_id, reference, entry["page_index"], original_path, preview_path,
                        width_px, height_px, "MasterCdrShape", embedding_bytes, review_status="Approved")
                    if width_mm is not None and height_mm is not None:
                        db.set_art_size_override(art_id, width_mm, height_mm)
                    existing_refs.add(reference)
                    added += 1
                    last_error = None
                    break
                except Exception as ex:
                    last_error = ex
                    if attempt < len(RETRY_WAITS_S):
                        time.sleep(RETRY_WAITS_S[attempt])

            if last_error is not None:
                failed_refs.append(ref_number)
                print(f"FALHOU ({last_error}) -- pulando essa REF.")
            else:
                print("ok")
    finally:
        if master_document is not None:
            try:
                master_document.Close()
            except Exception:
                pass

    print(f"\nConcluído: {added} REF(s) nova(s) adicionada(s), {skipped} já existiam e foram ignoradas.")
    if failed_refs:
        print(f"AVISO: {len(failed_refs)} REF(s) falharam e ficaram de fora: {', '.join(failed_refs)}.")
    return added, skipped


def _print_progress(current: int, total: int, start_time: float) -> None:
    width = 30
    filled = int(width * current / total) if total else 0
    bar = "#" * filled + "-" * (width - filled)
    pct = (current / total * 100) if total else 0

    elapsed = time.time() - start_time
    avg_per_page = elapsed / current if current else 0
    remaining = max(0, total - current)
    eta_seconds = int(avg_per_page * remaining)
    eta_txt = f"{eta_seconds // 60}min{eta_seconds % 60:02d}s" if eta_seconds > 0 else "quase lá"

    print(f"  [{bar}] {current}/{total} ({pct:.0f}%) -- tempo restante estimado: {eta_txt}")


def do_create_catalog_from_images(
    name: str, image_paths: list[str],
    target_long_side_mm: float | None = None,
    fixed_width_mm: float | None = None, fixed_height_mm: float | None = None,
    start_reference_number: int | None = None,
) -> int:
    """Builds a brand-new catalog straight from loose figure files -- no
    master .cdr, no REF captions to read (unlike do_import_from_master):
    for a batch of AI-generated/separated figures (see figure_generator.py,
    separador_figuras.py) that never went through a real catalog at all.

    Sizing is exactly one of two modes (the GUI page only ever offers one
    or the other, never both):
    - target_long_side_mm: each figure's own pixel aspect ratio decides
      its size, scaled so its longer side becomes this value (same "fix
      one dimension, the other follows its own proportion" rule used
      everywhere else in this app -- gerador_catalogos.py's batch-apply,
      pa._scale_to_long_side).
    - fixed_width_mm + fixed_height_mm: every figure gets this exact same
      size regardless of its own native aspect ratio (a deliberate
      stretch/squash -- for a batch that's actually meant to print at one
      uniform size, e.g. same-size stickers).
    Either way, these files have no physical size of their own to read,
    unlike a real master file's "MED WxHMM" caption.

    REF numbers are made up here (there's no real reference to read).
    start_reference_number, when given, is the first one used (typed in
    by the operator -- "what was the last catalog's REF?" -- so numbering
    continues from wherever they say it should); None (the default) falls
    back to one higher than the highest REF used ANYWHERE across every
    catalog already in the database (db.get_max_reference_number),
    guaranteed to never collide with a real REF from an actual designer
    file either way.

    Every art lands "Approved" (same as a real import -- there's no
    uncertain caption-reading step here to double-check) with its size
    saved as a manual override (db.set_art_size_override), since that's
    exactly the mechanism that already exists for "no master file, size
    set directly" -- get_locked_size_for_art already checks it first.
    Returns the new catalog's id."""
    unique_marker = f"scratch-{uuid.uuid4().hex}"
    catalog_id = db.insert_catalog(name, "(sem arquivo original -- catálogo criado do zero)", unique_marker)

    next_ref_number = start_reference_number if start_reference_number is not None \
        else db.get_max_reference_number() + 1
    added = 0
    for i, image_path in enumerate(image_paths, start=1):
        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            with Image.open(io.BytesIO(image_bytes)) as im:
                width_px, height_px = im.size

            if fixed_width_mm is not None and fixed_height_mm is not None:
                width_mm, height_mm = fixed_width_mm, fixed_height_mm
            elif width_px >= height_px:
                width_mm = target_long_side_mm
                height_mm = target_long_side_mm * height_px / width_px
            else:
                height_mm = target_long_side_mm
                width_mm = target_long_side_mm * width_px / height_px

            reference = f"REF {next_ref_number}"
            next_ref_number += 1

            original_path, preview_path = image_storage.save_art_images(catalog_id, 1, i, image_bytes)
            embedding = clip_embedding.generate_embedding(image_bytes)
            embedding_bytes = clip_embedding.embedding_to_bytes(embedding)

            art_id = db.insert_catalog_art(
                catalog_id, reference, 1, original_path, preview_path,
                width_px, height_px, "Scratch", embedding_bytes, review_status="Approved")
            db.set_art_size_override(art_id, width_mm, height_mm)
            added += 1
            print(f"  {reference}: {os.path.basename(image_path)} "
                  f"({width_mm:.0f}mm x {height_mm:.0f}mm) -- ok")
        except Exception as ex:
            print(f"  AVISO: falhou em '{os.path.basename(image_path)}': {ex} -- pulando essa.")

    if added == 0:
        db.delete_catalog(catalog_id)
        raise RuntimeError("Nenhuma figura foi importada com sucesso -- catálogo não foi criado.")

    db.update_catalog_status(catalog_id, "Ready")
    print(f"\nCatálogo '{name}' criado: id={catalog_id}, {added}/{len(image_paths)} figura(s) importada(s).")
    return catalog_id


def do_merge_catalogs(new_name: str, source_catalog_ids: list[int]) -> int:
    """Copies every APPROVED art from several existing catalogs into one
    brand-new one -- for grouping REFs that are scattered across different
    real catalogs into a single themed catalog of their own, without
    touching the originals (they keep every one of their own arts;
    nothing is moved or removed from them).

    Each art keeps its OWN real reference and OWN real locked size (read
    once via get_locked_size_for_art, then saved on the new art as a
    manual override -- the new catalog has no master .cdr of its own for
    get_locked_size_for_art to find a size in later, so this is what makes
    the copy keep the same production size as the original). Both the
    original image file and its CLIP embedding are copied fresh into the
    new catalog's own storage, not just referenced in place -- so deleting
    a SOURCE catalog later can never break the merged one.

    Two different source catalogs sometimes reuse the same REF number by
    coincidence (confirmed to happen for real elsewhere in this app,
    see finalizar.php's catalogo_nome+referencia matching) -- inside one
    single catalog that REF has to be unique, so only the first
    occurrence (source catalogs kept in the order given) is copied; every
    later duplicate is skipped and reported, not silently overwritten or
    renamed on its own. Returns the new catalog's id."""
    unique_marker = f"scratch-{uuid.uuid4().hex}"
    catalog_id = db.insert_catalog(
        new_name, "(sem arquivo original -- catálogo criado juntando outros catálogos)", unique_marker)

    seen_references = set()
    skipped_duplicates = []
    added = 0
    next_index = 0
    for source_catalog_id in source_catalog_ids:
        for art_id, reference, _page_number, original_image_path, _preview_path, review_status \
                in db.get_arts_with_paths_by_catalog_id(source_catalog_id):
            if review_status != "Approved" or not original_image_path:
                continue
            label = reference or f"id={art_id}"
            if label in seen_references:
                skipped_duplicates.append(label)
                continue
            seen_references.add(label)

            next_index += 1
            try:
                size = get_locked_size_for_art(art_id)
                with open(original_image_path, "rb") as f:
                    image_bytes = f.read()
                with Image.open(io.BytesIO(image_bytes)) as im:
                    width_px, height_px = im.size

                new_original_path, new_preview_path = image_storage.save_art_images(
                    catalog_id, 1, next_index, image_bytes)
                embedding = clip_embedding.generate_embedding(image_bytes)
                embedding_bytes = clip_embedding.embedding_to_bytes(embedding)

                new_art_id = db.insert_catalog_art(
                    catalog_id, reference, 1, new_original_path, new_preview_path,
                    width_px, height_px, "Merged", embedding_bytes, review_status="Approved")
                if size is not None:
                    db.set_art_size_override(new_art_id, size[0], size[1])
                added += 1
                print(f"  {label}: copiado do catálogo {source_catalog_id} -- ok")
            except Exception as ex:
                print(f"  AVISO: falhou em '{label}' (catálogo {source_catalog_id}): {ex} -- pulando essa.")

    if added == 0:
        db.delete_catalog(catalog_id)
        raise RuntimeError("Nenhuma figura foi copiada -- catálogo não foi criado.")

    db.update_catalog_status(catalog_id, "Ready")
    if skipped_duplicates:
        print(f"\nAVISO: {len(skipped_duplicates)} REF(s) já tinha(m) aparecido em outro catálogo escolhido "
              f"e foram ignoradas (mantida só a primeira): {', '.join(skipped_duplicates)}")
    print(f"\nCatálogo '{new_name}' criado: id={catalog_id}, {added} figura(s) copiada(s) "
          f"de {len(source_catalog_ids)} catálogo(s).")
    return catalog_id


# Same "reserve room for the caption text, not just the figure" idea as
# gerador_catalogos.py's _slot_width_mm -- kept separate (not imported from
# there) so this stays usable from the plain CLI too, without depending on
# a different tool's own sys.path setup (gerador_catalogos.py lives in a
# sibling top-level folder, only ever added to sys.path by gui_app.py).
_PREVIEW_CAPTION_HEIGHT_MM = 7.0
_PREVIEW_CAPTION_FONT_SIZE_PT = 16.0
_PREVIEW_CAPTION_CHAR_WIDTH_MM = _PREVIEW_CAPTION_FONT_SIZE_PT * 0.3528 * 0.62


def _preview_slot_width_mm(item: dict) -> float:
    caption_text = f"{item['reference']} MED {round(item['height_mm'])}X{round(item['width_mm'])}MM"
    return max(item["width_mm"], len(caption_text) * _PREVIEW_CAPTION_CHAR_WIDTH_MM)


def do_export_catalog_preview(
    catalog_id: int, save_path: str, page_width_mm: float = 270.0, profile_id: int | None = None,
) -> None:
    """Builds an actual CorelDRAW document showing every art in this
    catalog laid out in a grid with its own "REF MED WxHMM" caption below
    it (same look as a printed catalog page), saves it to save_path, and
    leaves it open in CorelDRAW to look at -- for reviewing a catalog
    that only exists in the database so far (see
    do_create_catalog_from_images) before deciding whether to publish it
    to the site at all. Never touches the website itself.

    Without profile_id: a single tall page (page_width_mm wide, height
    computed from the content) with fixed 10mm margins / 5mm spacing --
    meant to be looked at, not printed as-is.

    With profile_id: the chosen production profile drives the layout, same
    as an actual production run -- its width_mm is the page width, its four
    margins and its horizontal/vertical spacing are used as-is, and pages
    are profile.height_mm tall (a new page is added when the next row
    wouldn't fit above the bottom margin)."""
    arts = db.get_arts_with_paths_by_catalog_id(catalog_id)
    if not arts:
        raise RuntimeError(f"Catálogo {catalog_id} não tem nenhuma arte.")

    if profile_id is not None:
        profile = _load_profile(profile_id)
        page_width_mm = profile.width_mm
        margin_left_mm, margin_right_mm = profile.margin_left_mm, profile.margin_right_mm
        margin_top_mm, margin_bottom_mm = profile.margin_top_mm, profile.margin_bottom_mm
        spacing_h_mm, spacing_v_mm = profile.spacing_h_mm, profile.spacing_v_mm
        fixed_page_height_mm: float | None = profile.height_mm
        print(f"Perfil '{profile.name}': página {profile.width_mm:g}mm x {profile.height_mm:g}mm, "
              f"margens E{margin_left_mm:g}/D{margin_right_mm:g}/T{margin_top_mm:g}/B{margin_bottom_mm:g}mm, "
              f"espaçamento H{spacing_h_mm:g}/V{spacing_v_mm:g}mm.")
    else:
        margin_left_mm = margin_right_mm = margin_top_mm = margin_bottom_mm = 10.0
        spacing_h_mm = spacing_v_mm = 5.0
        fixed_page_height_mm = None
    usable_width_mm = page_width_mm - margin_left_mm - margin_right_mm

    items = []
    for art_id, reference, _page_number, original_image_path, _preview_path, _review_status in arts:
        size = get_locked_size_for_art(art_id)
        width_mm, height_mm = size if size else (60.0, 60.0)
        items.append({
            "reference": reference or f"id={art_id}", "image_path": original_image_path,
            "width_mm": width_mm, "height_mm": height_mm,
        })

    rows: list[list[dict]] = []
    row: list[dict] = []
    row_width_mm = 0.0
    for item in items:
        slot_mm = _preview_slot_width_mm(item)
        candidate_width_mm = slot_mm if not row else row_width_mm + spacing_h_mm + slot_mm
        if row and candidate_width_mm > usable_width_mm + 5.0:
            rows.append(row)
            row, row_width_mm = [], 0.0
            candidate_width_mm = slot_mm
        row.append(item)
        row_width_mm = candidate_width_mm
    if row:
        rows.append(row)

    # Each row's vertical footprint = tallest figure + its caption line.
    def _row_height_mm(one_row: list[dict]) -> float:
        return max(item["height_mm"] for item in one_row)

    # pages = [(rows_on_that_page, page_height_mm)]
    pages: list[tuple[list[list[dict]], float]] = []
    if fixed_page_height_mm is None:
        row_heights_mm = [_row_height_mm(r) for r in rows]
        total_height_mm = (
            margin_top_mm + margin_bottom_mm + sum(row_heights_mm)
            + len(rows) * _PREVIEW_CAPTION_HEIGHT_MM + max(0, len(rows) - 1) * spacing_v_mm)
        pages.append((rows, total_height_mm))
    else:
        page_rows: list[list[dict]] = []
        used_mm = margin_top_mm
        for one_row in rows:
            footprint_mm = _row_height_mm(one_row) + _PREVIEW_CAPTION_HEIGHT_MM
            needed_mm = footprint_mm + (spacing_v_mm if page_rows else 0.0)
            if page_rows and used_mm + needed_mm > fixed_page_height_mm - margin_bottom_mm:
                pages.append((page_rows, fixed_page_height_mm))
                page_rows, used_mm = [], margin_top_mm
                needed_mm = footprint_mm
            page_rows.append(one_row)
            used_mm += needed_mm
        if page_rows:
            pages.append((page_rows, fixed_page_height_mm))
    print(f"Layout: {len(items)} figura(s) em {len(rows)} linha(s), {len(pages)} página(s).")

    corel = coreldraw_service.CorelDrawService()
    corel.connect()
    document = corel.create_production_document()
    corel.set_units(document)

    for page_number, (page_rows, page_height_mm) in enumerate(pages):
        page = corel.get_active_page(document) if page_number == 0 else corel.add_page(document)
        corel.set_page_size(page, page_width_mm, page_height_mm)
        layer = corel.create_layer(page, "PREVIEW")

        top_y_mm = margin_top_mm
        for one_row in page_rows:
            row_height_mm = _row_height_mm(one_row)
            x_mm = margin_left_mm
            for item in one_row:
                slot_mm = _preview_slot_width_mm(item)
                item_x_mm = x_mm + (slot_mm - item["width_mm"]) / 2

                shape = corel.import_artwork(layer, item["image_path"])
                corel.resize_artwork(shape, item["width_mm"], item["height_mm"])
                corel.position_artwork(shape, item_x_mm, page_height_mm - top_y_mm)

                caption_text = f"{item['reference']} MED {round(item['height_mm'])}X{round(item['width_mm'])}MM"
                caption_bottom_from_top = top_y_mm + row_height_mm + _PREVIEW_CAPTION_HEIGHT_MM
                caption_shape = corel.create_text(
                    layer, item_x_mm, page_height_mm - caption_bottom_from_top, caption_text,
                    size_pt=_PREVIEW_CAPTION_FONT_SIZE_PT, bold=True)
                caption_width_mm, _caption_height_mm = corel.get_shape_size(caption_shape)
                centered_x_mm = item_x_mm + (item["width_mm"] - caption_width_mm) / 2
                _current_x_mm, current_top_y_mm = corel.get_shape_position(caption_shape)
                corel.position_artwork(caption_shape, centered_x_mm, current_top_y_mm)

                x_mm += slot_mm + spacing_h_mm

            top_y_mm += row_height_mm + _PREVIEW_CAPTION_HEIGHT_MM + spacing_v_mm

    corel.save_document(document, save_path, get_target_corel_version())
    print(f"Prévia salva e aberta no CorelDRAW: {save_path}")


def do_list() -> None:
    rows = db.get_all_catalogs()
    if not rows:
        print("Nenhum catálogo importado ainda.")
        return
    for catalog_id, name, status, created_at, total_arts, approved_arts, arts_with_reference, published_at in rows:
        published_txt = f"publicado_em={published_at}" if published_at else "não publicado no site"
        print(f"id={catalog_id}  \"{name}\"  status={status}  "
              f"artes={total_arts or 0}  com_ref={arts_with_reference or 0}  aprovadas={approved_arts or 0}  "
              f"criado_em={created_at}  {published_txt}")


def do_identify(photo_paths: list[str], top: int = 5) -> list[dict]:
    """Returns one result dict per photo: {photo_path, error, exact_match, candidates}.
    exact_match is a single (art_id, catalog_name, reference, preview_path) tuple when the
    REF was read directly off the photo; candidates is the visual-similarity top-N list,
    populated only when there was no exact match. The interactive menu uses the return
    value to offer "add this to the queue?" right away -- see _menu_identify."""
    results = []

    entries = db.get_approved_search_entries()
    if not entries:
        print("Nenhuma arte aprovada no banco ainda -- aprove um catálogo primeiro (opção 3).")
        return results

    api_key = None
    try:
        api_key = paths.read_openai_api_key()
    except OSError:
        pass

    for photo_path in photo_paths:
        photo_path = photo_path.strip().strip('"')
        print(f"\n=== Foto: {photo_path} ===")
        result = {"photo_path": photo_path, "error": None, "exact_match": None, "candidates": None}

        if not os.path.isfile(photo_path):
            print(f"ERRO: arquivo não encontrado: {photo_path}")
            result["error"] = "arquivo não encontrado"
            results.append(result)
            continue

        with open(photo_path, "rb") as f:
            photo_bytes = f.read()

        if api_key:
            try:
                reading = vision_scanner.read_customer_photo(photo_bytes, api_key)
            except Exception as ex:
                print(f"  (não consegui ler a foto com a IA de visão: {ex} -- usando só comparação visual)")
                reading = None

            if reading:
                if reading["note"]:
                    print(f"  IA: {reading['note']}")

                if not reading["produto_visivel"]:
                    print("  Essa foto não parece mostrar nenhum produto -- pulando a busca por "
                          "semelhança visual (ela só teria como comparar contra algo que não está lá).")
                    result["error"] = "foto não mostra nenhum produto"
                    results.append(result)
                    continue

                references = reading["references"]
                if len(references) > 1:
                    print(f"  AVISO: essa foto mostra VÁRIOS produtos ao mesmo tempo "
                          f"(REFs visíveis: {', '.join(references)}). Não dá pra saber qual o "
                          f"cliente quer -- peça pra ele mandar uma foto de UM produto só.")
                elif len(references) == 1:
                    matches = db.find_approved_arts_by_reference(references[0])
                    if matches:
                        print(f"  ENCONTRADO PELA REF IMPRESSA NA FOTO (\"{references[0]}\") -- match direto, alta confiança:")
                        for art_id, catalog_name, reference, preview_path in matches:
                            print(f"    {reference}  ({catalog_name})  [id={art_id}]  {preview_path}")
                        result["exact_match"] = matches[0]
                        results.append(result)
                        continue  # skip the visual-similarity fallback, we already have a certain answer

        query_embedding = clip_embedding.generate_embedding(photo_bytes)

        scored = []
        for art_id, catalog_name, reference, preview_path, embedding_blob in entries:
            candidate_embedding = clip_embedding.embedding_from_bytes(embedding_blob)
            score = clip_embedding.cosine_similarity(query_embedding, candidate_embedding)
            scored.append((score, art_id, catalog_name, reference, preview_path))

        scored.sort(key=lambda row: row[0], reverse=True)
        top_candidates = scored[:top]

        print(f"  Top {min(top, len(scored))} candidato(s) por semelhança visual:")
        for score, art_id, catalog_name, reference, preview_path in top_candidates:
            ref_display = reference if reference else "(sem REF)"
            print(f"    {score:.1%}  {ref_display}  ({catalog_name})  [id={art_id}]  {preview_path}")

        result["candidates"] = top_candidates
        results.append(result)

    return results


def sync_catalog_order_to_site() -> None:
    """Makes the site list the catalogs in EXACTLY the order the Catálogos page shows them.
    Why this exists: a catalog nobody ever dragged has no position in the app (it just shows after the
    numbered ones, newest first) while the site sorts every catalog WITHOUT a position alphabetically --
    so each import/delete/rename made the two lists drift apart until the next manual drag. This numbers
    EVERY catalog (0, 1, 2...) in the order shown, saves that locally too (so a new catalog lands last in
    both places) and sends the full list to the site."""
    rows = db.get_all_public_catalogs()
    db.reorder_catalogs([row[0] for row in rows])
    website_sync.definir_ordem_catalogos({row[1]: index for index, row in enumerate(rows)})


def do_rename_catalog_on_site(catalog_id: int, old_name: str, new_name: str) -> str:
    """After a catalog was renamed LOCALLY: makes the site use the new name too, then re-sends the catalog
    order (the site keeps each catalog's position under its NAME).
    Fast path: the site renames its own copy (no images re-sent). If the site had no catalog under the old
    name but this one was published, it is published again under the new name.
    Returns "renomeado" (site renamed), "republicado" (published again under the new name) or
    "nao_publicado" (this catalog was never on the site -- nothing to update there)."""
    outcome = "nao_publicado"
    renamed = website_sync.renomear_catalogo(old_name, new_name)
    # renomear_catalogo.php também renomeia figuras JÁ DESATIVADAS (catálogo que o site tinha apagado):
    # "renomeou algo" não basta -- só vale se o catálogo agora aparece ATIVO no site com o nome novo.
    if renamed > 0 and new_name in website_sync.list_published_catalog_names():
        outcome = "renomeado"
    else:
        row = next((r for r in db.get_all_catalogs() if r[0] == catalog_id), None)
        published_at = row[7] if row else None
        if published_at:
            do_publish_catalog(catalog_id)
            outcome = "republicado"
    _sync_catalog_order_quietly()
    return outcome


def _sync_catalog_order_quietly() -> None:
    try:
        sync_catalog_order_to_site()
    except Exception as ex:
        print(f"AVISO: não consegui atualizar a ordem dos catálogos no site agora ({ex}).")


def do_delete(catalog_id: int) -> None:
    all_rows = db.get_all_catalogs()
    catalog_row = next((row for row in all_rows if row[0] == catalog_id), None)
    catalog_name = catalog_row[1] if catalog_row else None

    # Attempted regardless of the local published_at flag -- that flag lives on THIS catalog row,
    # so it's blank on a catalog that was deleted and reimported after an earlier publish, even
    # though the site still has that earlier publish's products live under the same name.
    # excluir_catalogo.php is a no-op if nothing on the site matches the name.
    #
    # BUT skipped when another local catalog still has this exact same name (two catalogs sharing
    # a name is itself a data problem, but it does happen -- a stray unpublished duplicate left
    # over from an import that ran twice) -- the site's excluir_catalogo matches by NAME ONLY, so
    # deleting the duplicate that was NEVER published would otherwise take the other, actually-
    # published, same-named catalog down with it. Confirmed live: deleting one such duplicate
    # wiped its published twin off the site until both were manually republished.
    other_id_with_same_name = next(
        (row[0] for row in all_rows if row[0] != catalog_id and row[1] == catalog_name), None)
    if catalog_name and other_id_with_same_name is None:
        print(f"Removendo \"{catalog_name}\" do site (se estiver publicado)...")
        try:
            website_sync.excluir_catalogo(catalog_name)
        except Exception as ex:
            print(f"AVISO: não consegui remover do site agora ({ex}). "
                  f"O catálogo será excluído localmente mesmo assim -- tente remover do site depois.")
    elif other_id_with_same_name is not None:
        print(f"AVISO: catálogo {other_id_with_same_name} tem o mesmo nome (\"{catalog_name}\") -- "
              f"NÃO mexendo no site pra não apagar o dele por engano.")

    db.delete_catalog(catalog_id)
    image_storage.delete_catalog_images(catalog_id)
    print(f"Catálogo {catalog_id} excluído (banco + imagens).")
    _sync_catalog_order_quietly()


def get_locked_size_for_art(catalog_art_id: int) -> tuple[float, float] | None:
    """If the art's catalog has a master .cdr file configured, the designer
    already recorded the correct production size for this REF right in that
    file (the "REF NNN MED WxHMM" caption) -- that size is fixed, per the
    business rule: a design can't be stretched or shrunk to squeeze more
    copies into a row. Falls back to the catalog's default size (see
    set_catalog_default_size) when the master file has no per-REF size at
    all. Returns (width_mm, height_mm), or None if neither is set (caller
    falls back to asking). A manual override set via "Ver desenhos" (see
    db.set_art_size_override) always wins over either of those -- it exists
    specifically to correct a wrong caption/default for one piece."""
    override = db.get_art_size_override(catalog_art_id)
    if override is not None:
        return override

    art = db.get_art_by_id(catalog_art_id)
    if art is None:
        return None
    _id, reference, catalog_id = art

    if reference:
        normalized_ref = master_artwork.normalize_ref_number(reference)
        entry = db.get_master_ref_entry(catalog_id, normalized_ref)
        if entry is not None:
            _page_index, _shape_path, med_width_mm, med_height_mm = entry
            if med_width_mm is not None and med_height_mm is not None:
                return med_width_mm, med_height_mm

    return db.get_catalog_default_size(catalog_id)


def do_backfill_sizes_from_master(catalog_id: int) -> tuple[int, int]:
    """Fills in a size for every REF in this catalog that still has none,
    straight from the shape's own bounding box in the master .cdr -- for a
    catalog imported before the designer's file had a "REF NNN MED WxHMM"
    caption next to every piece (build_ref_index found the REF but no size
    text beside it, so get_locked_size_for_art keeps returning None for all
    of them even though the artwork is already drawn at its real physical
    scale on the page). Same measurement (master_artwork.get_shape_bbox_size)
    do_import_from_multiple_masters already falls back to automatically at
    import time -- this is that same fallback, run after the fact for a
    catalog that was imported through do_import_from_master (single file),
    which never had it.

    Never touches a REF that already has a manual override or a caption
    size -- only fills gaps, never overwrites a value someone already set or
    trusted. Requires the catalog's own master_cdr_path to still be on
    record (a multi-file merged catalog has none of its own -- see
    do_import_from_multiple_masters's docstring -- so there's nothing to
    reopen and remeasure for one of those). Returns (filled, failed)."""
    master_cdr_path = db.get_catalog_master_cdr_path(catalog_id)
    if not master_cdr_path or not os.path.exists(master_cdr_path):
        print(f"ERRO: catálogo {catalog_id} não tem um arquivo master .cdr salvo pra remedir.")
        return 0, 0

    entries = db.get_master_ref_entries_by_catalog(catalog_id)
    if not entries:
        print("Esse catálogo não tem nenhuma REF mapeada no arquivo original.")
        return 0, 0

    arts_by_ref_number = {}
    for art_id, reference, _page, _preview, _status in db.get_arts_by_catalog_id(catalog_id):
        if reference:
            arts_by_ref_number[master_artwork.normalize_ref_number(reference)] = art_id

    to_measure = []
    for ref_number, page_index, shape_path, med_width_mm, med_height_mm in entries:
        if med_width_mm is not None and med_height_mm is not None:
            continue  # já tem tamanho da legenda -- não mexe
        art_id = arts_by_ref_number.get(ref_number)
        if art_id is None or db.get_art_size_override(art_id) is not None:
            continue  # sem arte correspondente, ou já tem correção manual -- não sobrescreve
        to_measure.append((ref_number, page_index, shape_path, art_id))

    if not to_measure:
        print("Nenhuma REF precisando remedir -- todas já têm tamanho.")
        return 0, 0

    print(f"{len(to_measure)} REF(s) sem tamanho -- reabrindo o arquivo original pra medir direto da arte...")
    corel = coreldraw_service.CorelDrawService()
    corel.connect()
    master_document = None
    filled = 0
    failed = 0
    try:
        master_document = corel.open_document(master_cdr_path)
        corel.set_units(master_document)
        for ref_number, page_index, shape_path, art_id in to_measure:
            try:
                width_mm, height_mm = master_artwork.get_shape_bbox_size(
                    master_document, page_index, shape_path)
                db.set_art_size_override(art_id, width_mm, height_mm)
                filled += 1
                print(f"  REF {ref_number}: {height_mm:.1f}mm x {width_mm:.1f}mm (altura x largura)")
            except Exception as ex:
                failed += 1
                print(f"  REF {ref_number}: FALHOU ao medir ({ex}) -- pulando.")
    finally:
        if master_document is not None:
            try:
                master_document.Close()
            except Exception:
                pass

    print(f"\n{filled} REF(s) com tamanho preenchido direto da arte, {failed} falharam.")
    return filled, failed


def do_trim_catalog_borders(catalog_id: int, art_ids: list[int] | None = None) -> tuple[int, int, int, str]:
    """Crops away any transparent/near-white padding around every figure's
    real content (see image_storage.trim_transparent_border) -- pulled out
    of gui_page_trim_borders.py's own batch loop so "Montar Pedido" can run
    the exact same fix on just the REFs going into an order, right before
    generating it, instead of requiring a separate trip to "Recortar
    Bordas Transparentes" first.

    art_ids: when given, only these catalog_art_ids are checked (e.g. just
    the handful of REFs about to be queued) instead of every approved art
    in the catalog -- much cheaper than a whole-catalog pass when only a
    few REFs are actually about to be used. None (default) checks every
    approved, referenced art in catalog_id, same as the standalone page.

    Idempotent and cheap per figure (plain local PIL/numpy work, no paid
    API) -- an already-tight figure is left untouched and costs almost
    nothing to check, so calling this on every order is fine even though
    most figures will already be trimmed from an earlier pass.

    Returns (trimmed_count, already_tight_count, fail_count, backup_tag)."""
    arts = [
        row for row in db.get_arts_with_paths_by_catalog_id(catalog_id)
        if row[1] and row[3] and (art_ids is None or row[0] in set(art_ids))
    ]
    if not arts:
        return 0, 0, 0, ""

    backup_tag = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    trimmed_count = 0
    already_tight_count = 0
    fail_count = 0
    for art_id, reference, _page_number, original_image_path, preview_path, _review_status in arts:
        try:
            with open(original_image_path, "rb") as f:
                original_bytes = f.read()
            trimmed_bytes = image_storage.trim_transparent_border(original_bytes)
            if trimmed_bytes is None:
                already_tight_count += 1
                continue
            image_storage.backup_and_replace_art_image(
                catalog_id, original_image_path, preview_path, trimmed_bytes, backup_tag)
            trimmed_count += 1
            print(f"{reference}: recortada")
        except Exception as ex:
            fail_count += 1
            print(f"{reference}: FALHOU ao recortar -- {ex}")

    return trimmed_count, already_tight_count, fail_count, backup_tag


def do_trim_art_borders(catalog_art_id: int) -> bool:
    """Trims one specific art's own transparent/near-white padding (see
    do_trim_catalog_borders) -- for when only a handful of individual REFs
    need checking (do_generate_combined_order's trim_borders option) rather
    than looping a whole catalog just to reach a few of its rows.
    Returns True if the image was actually cropped, False if it was
    already tight, had no image on file, or the crop failed (see the log
    either way)."""
    art = db.get_art_by_id(catalog_art_id)
    if art is None:
        return False
    _art_id, _reference, catalog_id = art
    row = next(
        (r for r in db.get_arts_with_paths_by_catalog_id(catalog_id) if r[0] == catalog_art_id), None)
    if row is None or not row[3]:
        return False
    _id, reference, _page_number, original_image_path, preview_path, _review_status = row

    try:
        with open(original_image_path, "rb") as f:
            original_bytes = f.read()
        trimmed_bytes = image_storage.trim_transparent_border(original_bytes)
        if trimmed_bytes is None:
            return False
        backup_tag = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        image_storage.backup_and_replace_art_image(
            catalog_id, original_image_path, preview_path, trimmed_bytes, backup_tag)
        print(f"{reference}: bordas recortadas antes de gerar o pedido.")
        return True
    except Exception as ex:
        print(f"{reference}: FALHOU ao recortar bordas -- {ex}")
        return False


def get_catalog_id_for_art(catalog_art_id: int) -> int | None:
    art = db.get_art_by_id(catalog_art_id)
    return art[2] if art else None


def do_excluir_produto_do_site(catalog_art_id: int) -> None:
    """Removes just this one art from the public showcase, by catalog + REF
    -- for a single design with an error, without touching the rest of the
    catalog (see website_sync.excluir_produto)."""
    art = db.get_art_by_id(catalog_art_id)
    if art is None:
        print(f"ERRO: não existe nenhuma arte com id={catalog_art_id}.")
        return
    _id, reference, catalog_id = art
    if not reference:
        print("ERRO: essa arte não tem REF -- não dá pra localizar no site sem isso.")
        return

    catalog_name = db.get_catalog_name(catalog_id) or f"id={catalog_id}"
    website_sync.excluir_produto(catalog_name, reference)
    print(f"REF \"{reference}\" removido do site (catálogo \"{catalog_name}\").")


def do_delete_art(catalog_art_id: int) -> None:
    """Permanently removes one design -- from this catalog's database and
    from the site (if it was published there). Distinct from do_delete
    (whole catalog): for pulling a single bad piece via "Ver desenhos"
    without touching the rest."""
    art = db.get_art_by_id(catalog_art_id)
    if art is None:
        print(f"ERRO: não existe nenhuma arte com id={catalog_art_id}.")
        return
    _id, reference, catalog_id = art
    catalog_name = db.get_catalog_name(catalog_id) or f"id={catalog_id}"

    if reference:
        try:
            website_sync.excluir_produto(catalog_name, reference)
        except Exception as ex:
            print(f"AVISO: não consegui remover do site agora ({ex}). Removendo localmente mesmo assim.")

    original_path, preview_path = db.delete_catalog_art(catalog_art_id)
    for path in (original_path, preview_path):
        if path and os.path.isfile(path):
            os.remove(path)
    print(f"\"{reference or catalog_art_id}\" excluído (banco + site + imagens).")


def do_set_catalog_default_size(catalog_id: int, width_mm: float, height_mm: float) -> None:
    db.set_catalog_default_size(catalog_id, width_mm, height_mm)
    name = db.get_catalog_name(catalog_id) or f"id={catalog_id}"
    print(f"Tamanho padrão de \"{name}\" definido: {width_mm}mm x {height_mm}mm "
          f"(vale pra toda peça desse catálogo sem tamanho próprio no arquivo original).")


def do_set_art_size_override(catalog_art_id: int, width_mm: float, height_mm: float) -> None:
    db.set_art_size_override(catalog_art_id, width_mm, height_mm)
    print(f"Tamanho de id={catalog_art_id} corrigido pra {width_mm}mm x {height_mm}mm.")


def do_set_catalog_available_sizes(catalog_id: int, sizes: list[str]) -> None:
    """sizes: customer-facing options (e.g. ["29cm", "35cm"]) this catalog's
    figures sell in -- same list applies to every REF in the catalog. Takes
    effect on the next publish of this catalog."""
    db.set_catalog_available_sizes(catalog_id, sizes)
    print(f"Medidas do catálogo id={catalog_id} definidas: {', '.join(sizes) if sizes else '(nenhuma)'}.")


def do_add_to_queue(
    catalog_art_id: int, width_mm: float | None = None, height_mm: float | None = None,
    client_name: str | None = None, client_phone: str | None = None, quantity: int | None = None,
    client_representative: str | None = None, order_batch_id: int | None = None,
) -> None:
    art = db.get_art_by_id(catalog_art_id)
    if art is None:
        print(f"ERRO: não existe nenhuma arte com id={catalog_art_id} no banco. "
              f"Esse número é o id interno (aparece como '[id=...]' no resultado da busca), "
              f"NÃO é o número de REF impresso no produto.")
        return

    locked_size = get_locked_size_for_art(catalog_art_id)
    if locked_size is not None:
        width_mm, height_mm = locked_size
        print(f"Tamanho fixo dessa peça (não pode ser mudado aqui -- vem do arquivo original ou do "
              f"tamanho padrão do catálogo): {width_mm}mm x {height_mm}mm.")
    elif width_mm is None or height_mm is None:
        print("ERRO: essa arte não tem arquivo original configurado -- informe largura/altura manualmente.")
        return
    else:
        profile_row = db.get_default_profile()
        if profile_row is not None:
            profile_width_mm, profile_height_mm = profile_row[2], profile_row[3]
            if width_mm > profile_width_mm * 0.5 or height_mm > profile_height_mm * 0.5:
                print(f"AVISO: {width_mm}mm x {height_mm}mm é um tamanho bem grande -- é mais da metade "
                      f"da área de produção inteira ({profile_width_mm}mm x {profile_height_mm}mm). "
                      f"Confirma que esse é o tamanho de UMA peça (ex: uma estampa de 10cm), e não o "
                      f"tamanho do rolo/página?")
                confirm = _ask("Continuar mesmo assim? (s/n): ")
                if confirm.lower() != "s":
                    print("Cancelado.")
                    return

    queue_id = db.add_to_production_queue(
        catalog_art_id, width_mm, height_mm, client_name=client_name, client_phone=client_phone,
        quantity=quantity, client_representative=client_representative,
        order_batch_id=order_batch_id if order_batch_id is not None else db.new_order_batch_id())
    qty_txt = f", {quantity} unidade(s)" if quantity is not None else ""
    print(f"Adicionado à fila de produção (item {queue_id}): "
          f"{art[1] or '(sem REF)'}, {width_mm}mm x {height_mm}mm{qty_txt}.")


def _sizeable_approved_pool(catalog_ids: list[int]):
    """Approved arts across `catalog_ids` that have a resolvable size --
    the actual pool "Gerar Pedido"'s random-sample mode can draw from
    without repeating a design. Returns (sizeable_pool, skipped_no_size)."""
    pool = db.get_approved_arts_by_catalogs(catalog_ids)
    sizeable_pool = [
        (art_id, reference, catalog_id) for art_id, reference, catalog_id in pool
        if get_locked_size_for_art(art_id) is not None
    ]
    skipped_no_size = len(pool) - len(sizeable_pool)
    return sizeable_pool, skipped_no_size


def do_count_available_for_random_order(catalog_ids: list[int]) -> int:
    """How many distinct approved, sizeable arts are available across
    `catalog_ids` -- the ceiling for do_generate_combined_order's random
    fill, since it never repeats a design. Used by the GUI to show/validate
    the requested quantity before generating."""
    sizeable_pool, _skipped_no_size = _sizeable_approved_pool(catalog_ids)
    return len(sizeable_pool)


def do_generate_combined_order(
    catalog_ids: list[int], design_count: int | None, exact_entries: list[tuple[str, int]],
    client_name: str | None = None, client_phone: str | None = None, trim_borders: bool = False,
    client_representative: str | None = None,
    medida_rule: dict | None = None,
    quantity_min: int | None = None,
) -> dict:
    """"Gerar Pedido"'s single unified flow -- ONE order for ONE client,
    combining an optional exact list (specific quantities for specific
    REFs, e.g. "4 of REF 5") with an optional random draw of
    `design_count` DISTINCT designs from `catalog_ids`. Previously these
    were two separate buttons that each queued their own batch under the
    same client name, which looked like two separate orders in the
    production queue -- this is the fix, so combining them becomes one
    queuing pass for one client.

    Each randomly drawn design gets quantity=None, i.e. it fills its own
    row with as many copies as fit the profile's width (the classic
    behavior -- one design repeats across a row until it doesn't fit
    anymore, then the next design starts the row below). This is
    deliberately NOT a total piece count: an earlier version queued each
    random pick as exactly 1 physical piece so the numbers would add up
    to a literal total, but that meant a single unrepeated copy per row,
    which isn't how a real production sheet is supposed to look ("cada
    figura repete a linha toda, como antes" -- her words). Exact-list
    entries are the one place an explicit, guaranteed quantity still
    applies -- they get their stated quantity exactly, spanning multiple
    rows if needed. A design can be drawn randomly AND also be in the
    exact list; that just gives it its own extra full row on top of its
    reserved quantity, which is fine since she explicitly asked for more
    of it.

    design_count=None means "no random draw, just the exact list" (the
    old "Lista exata" standalone behavior). catalog_ids also scopes the
    exact list's REF lookups when given (disambiguates a REF number that
    repeats across different catalogs) -- empty/None searches every
    catalog. Raises ValueError (message is meant to be shown to the user
    as-is) if there aren't enough distinct sizeable designs in
    catalog_ids to satisfy design_count.

    trim_borders: when True, every art actually going into this order
    (both the exact list and the random draw -- never the whole catalog,
    just the handful of REFs used here) gets its own transparent/near-
    white padding trimmed first (see do_trim_art_borders), so "Montar
    Pedido" can do that fix and queue the order in one click instead of
    a separate trip to "Recortar Bordas Transparentes" beforehand.
    Skipped for an art already trimmed -- cheap to check either way.

    Returns {"exact_queued", "random_queued", "queued_refs",
    "skipped_refs", "trimmed_count"}."""
    if design_count is None and not exact_entries:
        raise ValueError("Preenche a quantidade de desenhos pra sortear, a lista exata, ou os dois.")

    resolved_exact = []  # (art_id, width_mm, height_mm, quantity, reference)
    skipped_refs = []
    medida_texto = medida_rule.get("rotulo") if medida_rule else None
    for reference, quantity in exact_entries:
        # catalog_ids scopes the search when given -- disambiguates a REF
        # number that repeats across different catalogs; empty means
        # search every catalog, same as before catalog selection existed
        # here.
        matches = db.find_approved_arts_by_reference(reference, catalog_ids)
        if not matches:
            skipped_refs.append(f"REF \"{reference}\" não encontrada (ou não aprovada)")
            continue
        art_id = matches[0][0]
        if medida_rule:
            locked_size = get_locked_size_for_art(art_id)
            px_size = db.get_art_pixel_size(art_id)
            computed = _size_for_measure_rule(medida_rule, locked_size, px_size)
            if computed is None:
                skipped_refs.append(f"REF \"{reference}\" não tem tamanho definido para calcular a medida")
                continue
            width_mm, height_mm = computed
        else:
            locked_size = get_locked_size_for_art(art_id)
            if locked_size is None:
                skipped_refs.append(f"REF \"{reference}\" não tem tamanho definido")
                continue
            width_mm, height_mm = locked_size
        final_qty = max(quantity, quantity_min) if quantity_min else quantity
        resolved_exact.append((art_id, width_mm, height_mm, final_qty, reference))

    chosen = []
    if design_count is not None and design_count > 0:
        if not catalog_ids:
            raise ValueError("Marca pelo menos um catálogo pra sortear os desenhos.")
        sizeable_pool, _skipped_no_size = _sizeable_approved_pool(catalog_ids)
        if design_count > len(sizeable_pool):
            raise ValueError(
                f"Pediu {design_count} desenho(s) diferentes, mas os catálogos escolhidos só têm "
                f"{len(sizeable_pool)} com tamanho definido -- a quantidade não pode passar disso, senão "
                f"repetiria desenho no sorteio. Diminui a quantidade ou marca mais catálogos.")
        # drawn from the FULL pool -- may coincide with a REF already in
        # the exact list, which just adds an extra full row for it.
        chosen = random.sample(sizeable_pool, design_count)

    trimmed_count = 0
    if trim_borders:
        for art_id, _w, _h, _qty, _reference in resolved_exact:
            if do_trim_art_borders(art_id):
                trimmed_count += 1
        for art_id, _reference, _catalog_id in chosen:
            if do_trim_art_borders(art_id):
                trimmed_count += 1

    # Tudo que esse pedido cria compartilha UM order_batch_id -- é o que deixa a Fila de
    # Produção separar esse pedido de outro pedido pendente do mesmo cliente (ver
    # db.new_order_batch_id).
    order_batch_id = db.new_order_batch_id()

    created_queue_ids = []
    for art_id, width_mm, height_mm, quantity, _reference in resolved_exact:
        qid = db.add_to_production_queue(
            art_id, width_mm, height_mm, client_name=client_name, client_phone=client_phone,
            quantity=quantity, client_representative=client_representative,
            medida_texto=medida_texto, order_batch_id=order_batch_id)
        created_queue_ids.append(qid)

    for art_id, _reference, _catalog_id in chosen:
        if medida_rule:
            locked_size = get_locked_size_for_art(art_id)
            px_size = db.get_art_pixel_size(art_id)
            computed = _size_for_measure_rule(medida_rule, locked_size, px_size)
            width_mm, height_mm = computed if computed else get_locked_size_for_art(art_id)
        else:
            width_mm, height_mm = get_locked_size_for_art(art_id)
        qid = db.add_to_production_queue(
            art_id, width_mm, height_mm, client_name=client_name, client_phone=client_phone,
            quantity=quantity_min, client_representative=client_representative,
            medida_texto=medida_texto, order_batch_id=order_batch_id)
        created_queue_ids.append(qid)

    return {
        "exact_queued": len(resolved_exact),
        "random_queued": len(chosen),
        "queued_refs": [reference for _art_id, _w, _h, _qty, reference in resolved_exact],
        "skipped_refs": skipped_refs,
        "trimmed_count": trimmed_count,
        "queue_ids": created_queue_ids,
    }


def do_list_queue() -> None:
    rows = db.get_pending_queue_items()
    if not rows:
        print("Fila de produção vazia.")
        return
    for queue_id, catalog_art_id, reference, width_mm, height_mm, original_image_path, catalog_name, \
            preview_path, client_name, client_phone, quantity, client_representative, \
            order_batch_id, created_at in rows:
        ref_display = reference or "(sem REF)"
        client_txt = f"  cliente={client_name}" if client_name else ""
        qty_txt = f"  qtd={quantity}" if quantity is not None else ""
        print(f"  fila_id={queue_id}  art_id={catalog_art_id}  {ref_display}  "
              f"({catalog_name})  {width_mm}mm x {height_mm}mm{qty_txt}{client_txt}")


def do_delete_queue_item(queue_id: int) -> None:
    db.delete_queue_item(queue_id)
    print(f"Item {queue_id} removido da fila de produção.")


def do_delete_queue_items(queue_ids: list[int]) -> int:
    """Removes several queue items at once -- for excluding a whole
    client's group from "Fila de Produção" in one click instead of hitting
    "Excluir" on each REF one at a time. Returns how many were removed."""
    for queue_id in queue_ids:
        db.delete_queue_item(queue_id)
    print(f"{len(queue_ids)} item(ns) removido(s) da fila de produção.")
    return len(queue_ids)


def do_list_profiles() -> None:
    profiles = db.get_all_profiles()
    if not profiles:
        print("Nenhum perfil de produção cadastrado.")
        return
    default_row = db.get_default_profile()
    default_id = default_row[0] if default_row else None
    for profile_id, name, width_mm, height_mm, ml, mr, mt, mb, sh, sv, material in profiles:
        marker = " (padrão)" if profile_id == default_id else ""
        material_txt = f"  material={material}" if material else ""
        print(f"  id={profile_id}  \"{name}\"{marker}  {width_mm}mm x {height_mm}mm  "
              f"margens(E/D/C/B)={ml}/{mr}/{mt}/{mb}mm  espaçamento(H/V)={sh}/{sv}mm{material_txt}")


def do_create_profile(
    name: str, width_mm: float, height_mm: float,
    margin_left_mm: float = 0, margin_right_mm: float = 0,
    margin_top_mm: float = 0, margin_bottom_mm: float = 0,
    spacing_h_mm: float = 0, spacing_v_mm: float = 0, make_default: bool = False,
    material: str | None = None,
) -> None:
    profile_id = db.insert_profile(
        name, width_mm, height_mm, margin_left_mm, margin_right_mm,
        margin_top_mm, margin_bottom_mm, spacing_h_mm, spacing_v_mm, make_default, material)
    print(f"Perfil criado: id={profile_id} \"{name}\" ({width_mm}mm x {height_mm}mm)"
          f"{' [padrão]' if make_default else ''}.")


def do_edit_profile(
    profile_id: int, name: str, width_mm: float, height_mm: float,
    margin_left_mm: float, margin_right_mm: float, margin_top_mm: float, margin_bottom_mm: float,
    spacing_h_mm: float, spacing_v_mm: float, material: str | None = None,
) -> None:
    db.update_profile(
        profile_id, name, width_mm, height_mm, margin_left_mm, margin_right_mm,
        margin_top_mm, margin_bottom_mm, spacing_h_mm, spacing_v_mm, material)
    print(f"Perfil {profile_id} atualizado: \"{name}\" ({width_mm}mm x {height_mm}mm), "
          f"espaçamento {spacing_h_mm}mm x {spacing_v_mm}mm.")


def do_set_default_profile(profile_id: int) -> None:
    db.set_default_profile(profile_id)
    print(f"Perfil {profile_id} agora é o padrão.")


def do_delete_profile(profile_id: int) -> None:
    db.delete_profile(profile_id)
    print(f"Perfil {profile_id} excluído.")


def _load_profile(profile_id: int | None) -> production.ProductionProfile:
    row = db.get_default_profile() if profile_id is None else next(
        (p for p in db.get_all_profiles() if p[0] == profile_id), None)
    if row is None:
        raise ValueError("Nenhum perfil de produção encontrado.")
    (_id, name, width_mm, height_mm, margin_left_mm, margin_right_mm,
     margin_top_mm, margin_bottom_mm, spacing_h_mm, spacing_v_mm, _material) = row
    return production.ProductionProfile(
        name, width_mm, height_mm, margin_left_mm, margin_right_mm,
        margin_top_mm, margin_bottom_mm, spacing_h_mm, spacing_v_mm)


def _scale_to_long_side(width_mm: float, height_mm: float, target_long_mm: float) -> tuple[float, float]:
    """Rescales one piece so its LONGER side becomes target_long_mm, keeping
    its own aspect ratio -- same "fix one dimension, the other follows"
    rule gerador_catalogos.py's batch-apply already uses (_apply_batch
    there), just applied per piece here instead of typed once per catalog."""
    if width_mm >= height_mm:
        scale = target_long_mm / width_mm if width_mm else 1.0
        return target_long_mm, height_mm * scale
    scale = target_long_mm / height_mm if height_mm else 1.0
    return width_mm * scale, target_long_mm


def do_generate_production(
    cdr_output_path: str, profile_id: int | None = None, queue_ids: list[int] | None = None,
    override_long_side_mm: float | None = None, copies_per_row: int | None = None,
    force_orientation: str | None = None, by_catalog: bool = False, keep_original_size: bool = False,
) -> None:
    """keep_original_size: True = every piece keeps EXACTLY its catalog width/height; False (old default) lets
    production.calculate_layout stretch each row's pieces wider (up to 20%) to fill the sheet width.
    queue_ids: when given, generates only these queue items (e.g. just one
    client's designs) instead of everything pending -- the rest of the queue
    is left untouched for a later run. override_long_side_mm: when given,
    EVERY piece is rescaled so its own longer side becomes this value (see
    _scale_to_long_side) instead of using each piece's size as recorded in
    the queue -- the "mudar a medida" choice offered before generating,
    as opposed to "usar tamanho original do catálogo" (None, the default).
    copies_per_row: when given, each figure's copies never share a row with
    a different figure's, and at most this many appear per row (see
    production.LayoutRequestItem.max_per_row). None (default) = pack freely.

    force_orientation: None (default) keeps every piece in whatever
    orientation it's recorded with in the catalog (landscape stays
    landscape, portrait stays portrait) -- right for a normal mixed queue.
    "vertical" or "horizontal" instead forces EVERY piece to stand that
    way: width_mm/height_mm are swapped here (before calculate_layout,
    so the row/page packing math itself accounts for the rotated
    footprint -- swapping only the visual artwork later, in
    production_generator.generate_unified, without also swapping the
    dimensions fed into the layout would leave rows planned for the
    UNROTATED size while the actual printed piece came out rotated,
    landing the wrong shape in the wrong spot). Was added for "faixa"
    pieces recorded landscape (e.g. 488x111mm) that don't fit a narrow
    roll profile's width side by side without overlapping -- rotated
    vertical, each one only needs 111mm of width instead of 488mm.

    by_catalog: False (default) lays out the whole queue as one mixed plan
    (figures from different catalogs can share a row/page). True instead
    calls calculate_layout once per catalog and concatenates the resulting
    pages (renumbered sequentially) -- each catalog gets its own page(s),
    never mixed with another catalog's pieces, still one .cdr document."""
    queue_rows = db.get_pending_queue_items()
    if queue_ids is not None:
        wanted = set(queue_ids)
        queue_rows = [row for row in queue_rows if row[0] in wanted]
    if not queue_rows:
        print("Fila de produção vazia -- nada para gerar.")
        return

    profile = _load_profile(profile_id)
    print(f"Usando perfil '{profile.name}' ({profile.width_mm}mm x {profile.height_mm}mm).")

    # All rows share one client in practice (the only caller groups by
    # client already) -- recorded on the production so a past run can be
    # re-queued under the same client later (see do_requeue_production), and
    # so a budget can be generated from it afterward (see do_generate_budget).
    production_client_name = queue_rows[0][8]
    production_client_phone = queue_rows[0][9]
    production_client_representative = queue_rows[0][11]

    items = []
    items_by_catalog: dict[str, list[production.LayoutRequestItem]] = {}
    queue_ids = []
    for queue_id, catalog_art_id, reference, width_mm, height_mm, original_image_path, catalog_name, \
            preview_path, client_name, client_phone, quantity, client_representative, \
            order_batch_id, created_at in queue_rows:
        if override_long_side_mm is not None:
            width_mm, height_mm = _scale_to_long_side(width_mm, height_mm, override_long_side_mm)
        if force_orientation == "vertical" and width_mm > height_mm:
            width_mm, height_mm = height_mm, width_mm
        elif force_orientation == "horizontal" and height_mm > width_mm:
            width_mm, height_mm = height_mm, width_mm
        # copies_per_row overrides the queue item's own quantity: place
        # exactly that many copies of each figure, packed freely into rows
        # alongside other figures (no row isolation -- max_per_row stays
        # None so the next figure fills whatever space the current one left).
        item_quantity = copies_per_row if copies_per_row is not None else quantity
        layout_item = production.LayoutRequestItem(catalog_art_id, reference, width_mm, height_mm, item_quantity)
        items.append(layout_item)
        items_by_catalog.setdefault(catalog_name, []).append(layout_item)
        queue_ids.append(queue_id)

    print(f"Calculando layout para {len(items)} item(ns) da fila...")
    try:
        if by_catalog:
            # Um calculate_layout por catálogo -- cada chamada só vê peças
            # de UM catálogo, então nunca mistura catálogos numa mesma
            # linha/página. As páginas de cada catálogo são concatenadas e
            # renumeradas em sequência (cada calculate_layout reinicia a
            # numeração em 1 -- ver production.py) pra virar um plano só,
            # ainda um documento .cdr único (generate_unified abaixo trata
            # plan.pages como uma sequência plana igual antes).
            print(f"Separando por catálogo: {len(items_by_catalog)} catálogo(s) diferentes.")
            pages = []
            for grupo_catalogo, catalog_items in items_by_catalog.items():
                catalog_plan = production.calculate_layout(
                    _sort_items_by_size(catalog_items), profile, fill_rows=not keep_original_size)
                for page in catalog_plan.pages:
                    page.page_number = len(pages) + 1
                    pages.append(page)
                print(f"  \"{grupo_catalogo}\": {len(catalog_plan.pages)} página(s).")
            plan = production.ProductionPlan(pages=pages)
        else:
            plan = production.calculate_layout(
                _sort_items_by_size(items), profile, fill_rows=not keep_original_size)
    except ValueError as ex:
        print(f"ERRO ao calcular o layout: {ex}")
        return

    print(f"Layout calculado: {len(plan.pages)} página(s), {plan.total_art_count} peça(s) no total.")
    print("Conectando ao CorelDRAW (abra o CorelDRAW antes se quiser acompanhar ao vivo)...")

    corel = coreldraw_service.CorelDrawService()
    corel.connect()

    artwork_sources_by_id = {}
    master_documents_by_path = {}
    for queue_id, catalog_art_id, reference, width_mm, height_mm, original_image_path, catalog_name, \
            preview_path, client_name, client_phone, quantity, client_representative, \
            order_batch_id, created_at in queue_rows:
        art = db.get_art_by_id(catalog_art_id)
        catalog_id = art[2] if art else None
        master_cdr_path = db.get_catalog_master_cdr_path(catalog_id) if catalog_id else None
        master_entry = db.get_master_ref_entry(catalog_id, master_artwork.normalize_ref_number(reference)) \
            if master_cdr_path and reference else None

        if master_cdr_path and master_entry:
            page_index, shape_path, _med_w, _med_h = master_entry
            if master_cdr_path not in master_documents_by_path:
                print(f"Abrindo arquivo original '{master_cdr_path}'...")
                master_documents_by_path[master_cdr_path] = _open_master_for_production(corel, master_cdr_path)
            artwork_sources_by_id[catalog_art_id] = {
                "kind": "master", "document": master_documents_by_path[master_cdr_path],
                "page_index": page_index, "shape_path": shape_path,
            }
        else:
            artwork_sources_by_id[catalog_art_id] = {"kind": "file", "path": original_image_path}

    result = production_generator.generate_unified(
        corel, plan, profile, artwork_sources_by_id, force_orientation=force_orientation is not None)
    _close_production_masters(corel, result)

    if not result.success:
        status = "PARCIAL (alguns itens foram criados antes do erro)" if result.is_partial else "FALHOU"
        print(f"Geração {status}: [{result.error_code}] {result.error_message}")
        db.insert_production(
            _profile_id_or_default(profile_id), None, "Failed",
            production_client_name, production_client_phone, production_client_representative)
        return {
            "failed": True, "status": status,
            "error_code": result.error_code, "error_message": result.error_message,
        }

    if result.validation_warning:
        print(f"AVISO: {result.validation_warning} (não travou a produção -- só registro).")

    # Peça com problema (arte sumida, CorelDRAW recusou essa figura específica) não derruba o
    # pedido inteiro -- fica de fora dessa produção E continua pendente na fila (não marcada como
    # produzida) pra corrigir e gerar depois; o resto do pedido sai normal.
    if result.skipped_pieces:
        linhas = "\n".join(
            f"  • {ref or f'id={cat_id}'}: {motivo}" for cat_id, ref, motivo in result.skipped_pieces)
        print(f"AVISO: {len(result.skipped_pieces)} peça(s) NÃO entraram nessa produção (ficaram "
              f"pendentes na fila pra corrigir e gerar depois):\n{linhas}")

    try:
        corel.save_document(result.document, cdr_output_path, get_target_corel_version())
    except Exception as ex:
        print(f"AVISO: geração concluída no CorelDRAW mas falhou ao salvar em '{cdr_output_path}': {ex}")
        print("Salve manualmente pelo CorelDRAW (Ctrl+S).")
        cdr_output_path = None
    else:
        print(f"Arquivo salvo em: {cdr_output_path}")

    production_id = db.insert_production(
        _profile_id_or_default(profile_id), cdr_output_path, "Completed",
        production_client_name, production_client_phone, production_client_representative)
    # One row can now mix pieces from several different figures (see
    # production.calculate_layout), so this groups by piece (art/ref/size/
    # orientation) within each page instead of assuming a whole row is one
    # figure -- same one-insert-per-group shape as before otherwise.
    # Medida escolhida pela cliente (texto da fila), por figura + tamanho -- vai junto pra
    # produção pra "Gerar de novo" poder devolver a peça na MESMA medida.
    # (com "mudar a medida de todas" a medida da cliente deixou de valer -- não grava)
    measure_info = {} if override_long_side_mm is not None else _measure_info_by_piece_height(
        queue_rows, items, db.get_queue_medida_texts(queue_ids))

    for page in plan.pages:
        groups: dict[tuple, int] = {}
        for row in page.rows:
            for piece in row.pieces:
                key = (piece.catalog_art_id, piece.reference, piece.width_mm, piece.height_mm, piece.orientation)
                groups[key] = groups.get(key, 0) + 1
        for (catalog_art_id, reference, width_mm, height_mm, orientation), qty in groups.items():
            info = measure_info.get((catalog_art_id, round(height_mm, 1)))
            db.insert_production_item(
                production_id, catalog_art_id, reference, width_mm, height_mm, orientation, qty, page.page_number,
                medida_texto=info[0] if info else None,
                nominal_width_mm=info[1] if info else None, nominal_height_mm=info[2] if info else None)

    # Peça pulada (ver result.skipped_pieces acima) não é marcada como produzida -- continua
    # pendente na fila pra corrigir e gerar depois, em vez de sumir sem nunca ter sido gerada.
    skipped_art_ids = {cat_id for cat_id, _ref, _motivo in result.skipped_pieces}
    produced_queue_ids = [
        qid for qid, item in zip(queue_ids, items) if item.catalog_art_id not in skipped_art_ids]

    replaced_ids = db.get_replaced_production_ids(produced_queue_ids)
    db.mark_queue_items_produced(produced_queue_ids)
    # "Gerar de novo": a produção nova SUBSTITUI o card antigo no histórico
    # (só o registro -- o .cdr antigo continua no disco), em vez de deixar o
    # mesmo cliente repetido na lista. Só some quando TODAS as peças que
    # vieram dela já foram geradas; se sobrou alguma na fila, o card fica.
    for old_id in replaced_ids:
        if old_id != production_id and db.count_pending_items_replacing(old_id) == 0:
            db.delete_production(old_id)
            print(f"Produção antiga {old_id} substituída por esta (removida do histórico; o arquivo .cdr dela "
                  f"continua no disco).")
    print(f"Produção {production_id} concluída: {result.pages_created} página(s), "
          f"{result.shapes_created} forma(s) criada(s) no CorelDRAW.")
    return {"skipped_pieces": result.skipped_pieces}


def do_generate_production_mixed(
    cdr_output_path: str, profile_id: int, aplique_queue_ids: list[int], faixa_queue_ids: list[int],
    override_long_side_mm: float | None = None, copies_per_row: int | None = None,
    force_orientation_aplique: str | None = None, by_catalog: bool = False, keep_original_size: bool = False,
) -> dict | None:
    """Pedido com aplique E faixa misturados: gera as duas partes numa produção SÓ -- um arquivo
    .cdr, um card em "Produções anteriores" -- em vez de duas produções separadas perguntando
    Material/Perfil duas vezes. Cada parte ainda usa sua própria passada de layout (faixa sempre
    em pé, aplique na orientação normal/escolhida -- a física das duas não muda), só que
    desenhadas no MESMO documento do CorelDRAW antes de salvar uma vez só (ver
    production_generator.generate_unified, document=.../page_number_offset=...)."""
    all_queue_ids = aplique_queue_ids + faixa_queue_ids
    wanted = set(all_queue_ids)
    all_rows = [row for row in db.get_pending_queue_items() if row[0] in wanted]
    if not all_rows:
        print("Fila de produção vazia -- nada para gerar.")
        return None

    profile = _load_profile(profile_id)
    print(f"Usando perfil '{profile.name}' ({profile.width_mm}mm x {profile.height_mm}mm).")

    production_client_name = all_rows[0][8]
    production_client_phone = all_rows[0][9]
    production_client_representative = all_rows[0][11]
    rows_by_id = {row[0]: row for row in all_rows}

    def build_items(ids, force_orientation):
        items, items_by_catalog, ordered_ids = [], {}, []
        for qid in ids:
            row = rows_by_id.get(qid)
            if row is None:
                continue
            _qid, catalog_art_id, reference, width_mm, height_mm, _orig, catalog_name, \
                _preview, _cn, _cp, quantity, _crep, _batch, _created = row
            if override_long_side_mm is not None:
                width_mm, height_mm = _scale_to_long_side(width_mm, height_mm, override_long_side_mm)
            if force_orientation == "vertical" and width_mm > height_mm:
                width_mm, height_mm = height_mm, width_mm
            elif force_orientation == "horizontal" and height_mm > width_mm:
                width_mm, height_mm = height_mm, width_mm
            item_quantity = copies_per_row if copies_per_row is not None else quantity
            layout_item = production.LayoutRequestItem(catalog_art_id, reference, width_mm, height_mm, item_quantity)
            items.append(layout_item)
            items_by_catalog.setdefault(catalog_name, []).append(layout_item)
            ordered_ids.append(qid)
        return items, items_by_catalog, ordered_ids

    def build_plan(items, items_by_catalog):
        if not items:
            return production.ProductionPlan(pages=[])
        if by_catalog:
            pages = []
            for grupo_catalogo, catalog_items in items_by_catalog.items():
                catalog_plan = production.calculate_layout(
                    _sort_items_by_size(catalog_items), profile, fill_rows=not keep_original_size)
                for page in catalog_plan.pages:
                    page.page_number = len(pages) + 1
                    pages.append(page)
                print(f"  \"{grupo_catalogo}\": {len(catalog_plan.pages)} página(s).")
            return production.ProductionPlan(pages=pages)
        return production.calculate_layout(_sort_items_by_size(items), profile, fill_rows=not keep_original_size)

    aplique_items, aplique_by_catalog, aplique_ordered_ids = build_items(aplique_queue_ids, force_orientation_aplique)
    faixa_items, faixa_by_catalog, faixa_ordered_ids = build_items(faixa_queue_ids, "vertical")

    print(f"Calculando layout: {len(aplique_items)} aplique(s), {len(faixa_items)} faixa(s)...")
    try:
        aplique_plan = build_plan(aplique_items, aplique_by_catalog)
        faixa_plan = build_plan(faixa_items, faixa_by_catalog)
    except ValueError as ex:
        print(f"ERRO ao calcular o layout: {ex}")
        return None

    print(f"Layout calculado: {len(aplique_plan.pages)} página(s) de aplique, {len(faixa_plan.pages)} de faixa.")
    print("Conectando ao CorelDRAW (abra o CorelDRAW antes se quiser acompanhar ao vivo)...")

    corel = coreldraw_service.CorelDrawService()
    corel.connect()

    artwork_sources_by_id = {}
    master_documents_by_path = {}
    for _qid, catalog_art_id, reference, _w, _h, original_image_path, _cat, _prev, _cn, _cp, _q, _cr, _b, _c in all_rows:
        art = db.get_art_by_id(catalog_art_id)
        catalog_id = art[2] if art else None
        master_cdr_path = db.get_catalog_master_cdr_path(catalog_id) if catalog_id else None
        master_entry = db.get_master_ref_entry(catalog_id, master_artwork.normalize_ref_number(reference)) \
            if master_cdr_path and reference else None
        if master_cdr_path and master_entry:
            page_index, shape_path, _med_w, _med_h = master_entry
            if master_cdr_path not in master_documents_by_path:
                print(f"Abrindo arquivo original '{master_cdr_path}'...")
                master_documents_by_path[master_cdr_path] = _open_master_for_production(corel, master_cdr_path)
            artwork_sources_by_id[catalog_art_id] = {
                "kind": "master", "document": master_documents_by_path[master_cdr_path],
                "page_index": page_index, "shape_path": shape_path,
            }
        else:
            artwork_sources_by_id[catalog_art_id] = {"kind": "file", "path": original_image_path}

    combined_skipped, combined_warnings = [], []
    document, pages_so_far, total_shapes = None, 0, 0

    if aplique_plan.pages:
        result1 = production_generator.generate_unified(
            corel, aplique_plan, profile, artwork_sources_by_id,
            force_orientation=force_orientation_aplique is not None)
        document = result1.document
        pages_so_far += result1.pages_created
        total_shapes += result1.shapes_created
        combined_skipped += result1.skipped_pieces
        if result1.validation_warning:
            combined_warnings.append(result1.validation_warning)
        if not result1.success:
            _close_production_masters(corel, result1)
            status = "PARCIAL (alguns itens foram criados antes do erro)" if result1.is_partial else "FALHOU"
            print(f"Geração {status}: [{result1.error_code}] {result1.error_message}")
            db.insert_production(
                _profile_id_or_default(profile_id), None, "Failed",
                production_client_name, production_client_phone, production_client_representative)
            return {
                "failed": True, "status": status,
                "error_code": result1.error_code, "error_message": result1.error_message,
            }

    if faixa_plan.pages:
        result2 = production_generator.generate_unified(
            corel, faixa_plan, profile, artwork_sources_by_id,
            force_orientation=True, document=document, page_number_offset=pages_so_far)
        document = result2.document
        pages_so_far += result2.pages_created
        total_shapes += result2.shapes_created
        combined_skipped += result2.skipped_pieces
        if result2.validation_warning:
            combined_warnings.append(result2.validation_warning)
        if not result2.success:
            _close_production_masters(corel, result2)
            status = "PARCIAL (alguns itens foram criados antes do erro)" if result2.is_partial else "FALHOU"
            print(f"Geração {status}: [{result2.error_code}] {result2.error_message}")
            # Os apliques já foram desenhados no mesmo documento -- fica aberto no CorelDRAW pra
            # conferir/salvar manualmente; nada aqui é marcado como produzido.
            db.insert_production(
                _profile_id_or_default(profile_id), None, "Failed",
                production_client_name, production_client_phone, production_client_representative)
            return {
                "failed": True, "status": status,
                "error_code": result2.error_code, "error_message": result2.error_message,
            }

    _close_production_masters(corel)

    for warning in combined_warnings:
        print(f"AVISO: {warning} (não travou a produção -- só registro).")
    if combined_skipped:
        linhas = "\n".join(
            f"  • {ref or f'id={cat_id}'}: {motivo}" for cat_id, ref, motivo in combined_skipped)
        print(f"AVISO: {len(combined_skipped)} peça(s) NÃO entraram nessa produção (ficaram "
              f"pendentes na fila pra corrigir e gerar depois):\n{linhas}")

    try:
        corel.save_document(document, cdr_output_path, get_target_corel_version())
    except Exception as ex:
        print(f"AVISO: geração concluída no CorelDRAW mas falhou ao salvar em '{cdr_output_path}': {ex}")
        print("Salve manualmente pelo CorelDRAW (Ctrl+S).")
        cdr_output_path = None
    else:
        print(f"Arquivo salvo em: {cdr_output_path}")

    production_id = db.insert_production(
        _profile_id_or_default(profile_id), cdr_output_path, "Completed",
        production_client_name, production_client_phone, production_client_representative)

    all_ordered_ids = aplique_ordered_ids + faixa_ordered_ids
    all_items = aplique_items + faixa_items
    ordered_rows = [rows_by_id[qid] for qid in all_ordered_ids]
    measure_info = {} if override_long_side_mm is not None else _measure_info_by_piece_height(
        ordered_rows, all_items, db.get_queue_medida_texts(all_ordered_ids))

    for plan in (aplique_plan, faixa_plan):
        for page in plan.pages:
            groups: dict[tuple, int] = {}
            for row in page.rows:
                for piece in row.pieces:
                    key = (piece.catalog_art_id, piece.reference, piece.width_mm, piece.height_mm, piece.orientation)
                    groups[key] = groups.get(key, 0) + 1
            for (catalog_art_id, reference, width_mm, height_mm, orientation), qty in groups.items():
                info = measure_info.get((catalog_art_id, round(height_mm, 1)))
                db.insert_production_item(
                    production_id, catalog_art_id, reference, width_mm, height_mm, orientation, qty, page.page_number,
                    medida_texto=info[0] if info else None,
                    nominal_width_mm=info[1] if info else None, nominal_height_mm=info[2] if info else None)

    skipped_art_ids = {cat_id for cat_id, _ref, _motivo in combined_skipped}
    produced_queue_ids = [
        qid for qid, item in zip(all_ordered_ids, all_items) if item.catalog_art_id not in skipped_art_ids]

    replaced_ids = db.get_replaced_production_ids(produced_queue_ids)
    db.mark_queue_items_produced(produced_queue_ids)
    for old_id in replaced_ids:
        if old_id != production_id and db.count_pending_items_replacing(old_id) == 0:
            db.delete_production(old_id)
            print(f"Produção antiga {old_id} substituída por esta (removida do histórico; o arquivo .cdr dela "
                  f"continua no disco).")

    print(f"Produção {production_id} concluída: {pages_so_far} página(s), "
          f"{total_shapes} forma(s) criada(s) no CorelDRAW.")
    return {"skipped_pieces": combined_skipped}


def do_generate_production_for_whole_catalog(
    catalog_id: int, cdr_output_path: str, profile_id: int | None = None,
    copies_per_row: int | None = None, force_orientation: str | None = None,
) -> None:
    """Like do_generate_production_for_catalog, but skips typing a current/
    new size pair entirely -- "escolher o catálogo inteiro e montar" as one
    click, every REF at its OWN already-recorded size (get_locked_size_for_art,
    same size Montar Pedido/Gerar Produção already use), not one shared size
    forced onto everything. A REF with no locked size at all is skipped
    (with a warning) rather than guessed -- fix it in "Ver desenhos" and
    run again if it needs to be included.

    copies_per_row: None (default) packs the queue-style way, mixing
    figures freely into whatever width is left in a row; a number gives
    every figure exactly that many copies, never sharing a row with a
    different figure's (see production.LayoutRequestItem.max_per_row).
    force_orientation: None keeps each piece in its own recorded
    orientation; "vertical"/"horizontal" forces all of them the same way
    (see do_generate_production's own docstring for why width/height are
    swapped here, before calculate_layout, instead of only at render time)."""
    arts = [
        row for row in db.get_arts_with_paths_by_catalog_id(catalog_id)
        if row[1] and row[5] == "Approved"
    ]
    if not arts:
        print(f"Catálogo {catalog_id} não tem nenhuma REF aprovada -- nada para gerar.")
        return

    profile = _load_profile(profile_id)
    print(f"Usando perfil '{profile.name}' ({profile.width_mm}mm x {profile.height_mm}mm).")

    items = []
    skipped_refs = []
    for catalog_art_id, reference, _page_number, _original_image_path, _preview_path, _review_status in arts:
        locked_size = get_locked_size_for_art(catalog_art_id)
        if locked_size is None:
            skipped_refs.append(reference or f"id={catalog_art_id}")
            continue
        width_mm, height_mm = locked_size
        if force_orientation == "vertical" and width_mm > height_mm:
            width_mm, height_mm = height_mm, width_mm
        elif force_orientation == "horizontal" and height_mm > width_mm:
            width_mm, height_mm = height_mm, width_mm
        items.append(production.LayoutRequestItem(
            catalog_art_id, reference, width_mm, height_mm,
            quantity=copies_per_row, max_per_row=copies_per_row))

    if skipped_refs:
        print(f"AVISO: {len(skipped_refs)} REF(s) sem tamanho definido, ficaram de fora: "
              f"{', '.join(skipped_refs)}. Defina o tamanho em \"Ver desenhos\" e gere de novo se quiser incluí-las.")

    if not items:
        print("Nenhuma REF com tamanho definido nesse catálogo -- nada para gerar.")
        return

    print(f"Calculando layout para {len(items)} peça(s)...")
    try:
        plan = production.calculate_layout(items, profile)
    except ValueError as ex:
        print(f"ERRO ao calcular o layout: {ex}")
        return

    print(f"Layout calculado: {len(plan.pages)} página(s), {plan.total_art_count} peça(s) no total.")
    print("Conectando ao CorelDRAW (abra o CorelDRAW antes se quiser acompanhar ao vivo)...")

    corel = coreldraw_service.CorelDrawService()
    corel.connect()

    master_cdr_path = db.get_catalog_master_cdr_path(catalog_id)
    artwork_sources_by_id = {}
    master_document = None
    for catalog_art_id, reference, _page_number, original_image_path, _preview_path, _review_status in arts:
        master_entry = db.get_master_ref_entry(catalog_id, master_artwork.normalize_ref_number(reference)) \
            if master_cdr_path and reference else None

        if master_cdr_path and master_entry:
            page_index, shape_path, _med_w, _med_h = master_entry
            if master_document is None:
                print(f"Abrindo arquivo original '{master_cdr_path}'...")
                master_document = _open_master_for_production(corel, master_cdr_path)
            artwork_sources_by_id[catalog_art_id] = {
                "kind": "master", "document": master_document,
                "page_index": page_index, "shape_path": shape_path,
            }
        else:
            artwork_sources_by_id[catalog_art_id] = {"kind": "file", "path": original_image_path}

    result = production_generator.generate_unified(
        corel, plan, profile, artwork_sources_by_id, force_orientation=force_orientation is not None)
    _close_production_masters(corel, result)

    if not result.success:
        status = "PARCIAL (alguns itens foram criados antes do erro)" if result.is_partial else "FALHOU"
        print(f"Geração {status}: [{result.error_code}] {result.error_message}")
        db.insert_production(_profile_id_or_default(profile_id), None, "Failed", None, None)
        return

    if result.validation_warning:
        print(f"AVISO: {result.validation_warning} (não travou a produção -- só registro).")

    if result.skipped_pieces:
        linhas = "\n".join(
            f"  • {ref or f'id={cat_id}'}: {motivo}" for cat_id, ref, motivo in result.skipped_pieces)
        print(f"AVISO: {len(result.skipped_pieces)} peça(s) NÃO entraram nessa produção:\n{linhas}")

    try:
        corel.save_document(result.document, cdr_output_path, get_target_corel_version())
    except Exception as ex:
        print(f"AVISO: geração concluída no CorelDRAW mas falhou ao salvar em '{cdr_output_path}': {ex}")
        print("Salve manualmente pelo CorelDRAW (Ctrl+S).")
        cdr_output_path = None
    else:
        print(f"Arquivo salvo em: {cdr_output_path}")

    production_id = db.insert_production(_profile_id_or_default(profile_id), cdr_output_path, "Completed", None, None)
    for page in plan.pages:
        groups: dict[tuple, int] = {}
        for row in page.rows:
            for piece in row.pieces:
                key = (piece.catalog_art_id, piece.reference, piece.width_mm, piece.height_mm, piece.orientation)
                groups[key] = groups.get(key, 0) + 1
        for (catalog_art_id, reference, piece_width_mm, piece_height_mm, orientation), qty in groups.items():
            db.insert_production_item(
                production_id, catalog_art_id, reference, piece_width_mm, piece_height_mm, orientation, qty,
                page.page_number)

    print(f"Produção {production_id} concluída: {result.pages_created} página(s), "
          f"{result.shapes_created} forma(s) criada(s) no CorelDRAW.")


def find_arts_by_current_size(
    catalog_id: int, current_width_mm: float, current_height_mm: float, tolerance_mm: float = 3.0,
    width_is_proportional: bool = False,
) -> list[tuple]:
    """Every approved, referenced art in this catalog whose OWN current
    size (get_locked_size_for_art -- the master file's recorded MED, the
    catalog's default, or a manual override, whichever applies) matches
    current_width_mm x current_height_mm within tolerance_mm. Either
    orientation counts as a match (a piece locked at 90x60 matches a
    search for 60x90 too) -- "medida atual" here means the pair of
    numbers on the piece, not which one happens to be labeled width vs
    height. Built for isolating just the REFs at one particular size out
    of a catalog that mixes several, before applying one NEW size to
    only those (see do_generate_production_for_arts) -- a real catalog
    routinely has, say, most pieces at 60x90mm and a handful at 70x100mm,
    and only one of those groups should get resized/produced at a time.

    width_is_proportional: some catalogs only keep ONE side fixed across
    every REF (the height, say) while the other side varies per piece to
    keep its own native proportion -- there current_width_mm has no real
    shared value to search for at all (confirmed live: searching "290x60"
    found nothing because every piece's actual width differed slightly,
    even though they all really do share the same 290mm height). When
    True, current_width_mm is ignored entirely and a piece matches as
    long as EITHER of its own two recorded numbers is within
    tolerance_mm of current_height_mm.

    A REF with NO locked size at all (get_locked_size_for_art returns
    None -- confirmed live as the actual reason a whole catalog imported
    via curve-caption vision reading matched nothing, no matter what was
    searched: that import path never records a MED size for anything, on
    purpose, since a curve-converted caption has no size to read at all)
    falls back to measuring its REAL artwork bbox straight from the
    master .cdr file (needs CorelDRAW open -- can be slow for a big
    catalog) instead of being silently skipped out of the search.

    Returns rows in the same shape as db.get_arts_with_paths_by_catalog_id."""
    arts = [
        row for row in db.get_arts_with_paths_by_catalog_id(catalog_id)
        if row[1] and row[5] == "Approved"
    ]
    master_cdr_path = db.get_catalog_master_cdr_path(catalog_id)
    corel = None
    master_document = None
    matches = []
    try:
        for row in arts:
            catalog_art_id, reference = row[0], row[1]
            size = get_locked_size_for_art(catalog_art_id)
            if size is None:
                master_entry = db.get_master_ref_entry(
                    catalog_id, master_artwork.normalize_ref_number(reference)) \
                    if master_cdr_path and reference else None
                if master_entry is None:
                    continue
                page_index, shape_path, _med_w, _med_h = master_entry
                if master_document is None:
                    corel = coreldraw_service.CorelDrawService()
                    corel.connect()
                    master_document = corel.open_document(master_cdr_path)
                    corel.set_units(master_document)
                try:
                    size = master_artwork.get_shape_bbox_size(master_document, page_index, shape_path)
                except Exception:
                    continue

            width_mm, height_mm = size
            if width_is_proportional:
                matched = (
                    abs(width_mm - current_height_mm) <= tolerance_mm
                    or abs(height_mm - current_height_mm) <= tolerance_mm)
            else:
                direct = (
                    abs(width_mm - current_width_mm) <= tolerance_mm
                    and abs(height_mm - current_height_mm) <= tolerance_mm)
                swapped = (
                    abs(width_mm - current_height_mm) <= tolerance_mm
                    and abs(height_mm - current_width_mm) <= tolerance_mm)
                matched = direct or swapped
            if matched:
                matches.append(row)
    finally:
        if master_document is not None:
            try:
                master_document.Close()
            except Exception:
                pass
    return matches


def do_generate_production_for_catalog(
    catalog_id: int, width_mm: float, height_mm: float,
    cdr_output_path: str, profile_id: int | None = None, copies_per_row: int = 1,
) -> None:
    """Like do_generate_production, but sourced from every approved,
    referenced REF in one whole catalog instead of whatever's sitting in
    the production queue. See do_generate_production_for_arts for the
    part this shares with it (the exact-size, forced-vertical generation
    itself) -- this just supplies "every REF in the catalog" as the arts
    to generate, instead of a caller-chosen subset."""
    arts = [
        row for row in db.get_arts_with_paths_by_catalog_id(catalog_id)
        if row[1] and row[5] == "Approved"
    ]
    if not arts:
        print(f"Catálogo {catalog_id} não tem nenhuma REF aprovada -- nada para gerar.")
        return
    do_generate_production_for_arts(catalog_id, arts, width_mm, height_mm, cdr_output_path, profile_id, copies_per_row)


def do_generate_production_for_arts(
    catalog_id: int, arts: list[tuple], width_mm: float, height_mm: float,
    cdr_output_path: str, profile_id: int | None = None, copies_per_row: int = 1,
) -> None:
    """The actual generation: width_mm/height_mm is forced onto EVERY
    piece in `arts` exactly as given (no proportional scaling, and no
    per-piece locked size from the master file/catalog default the way
    do_add_to_queue would otherwise apply), unlike override_long_side_mm
    on do_generate_production. Built for "gerar essa produção com essas
    REFs numa medida nova, sem passar pela fila" as a one-shot run:
    nothing is added to (or read from) the production queue, so a
    client's order already queued separately is never touched by this.
    `arts` rows are in the same shape as
    db.get_arts_with_paths_by_catalog_id, and must all belong to
    catalog_id (needed to look up that catalog's master .cdr file, if
    any) -- see find_arts_by_current_size for one way to build that list
    (every REF currently at some OTHER size), or do_generate_production_
    for_catalog for "just use the whole catalog".

    copies_per_row: how many repeated copies of EACH figure to place --
    exactly this many side by side in one row (or split across as many
    rows as needed if that many don't fit the profile's width at once),
    never mixed with a different figure's copies in the same row (see
    production.LayoutRequestItem.max_per_row) -- "12 cópias por linha
    pra cada figura" as a uniform rule for the whole run, instead of the
    normal queue-based flow's default of packing whatever fits."""
    if not arts:
        print("Nenhuma arte para gerar.")
        return

    profile = _load_profile(profile_id)
    print(f"Usando perfil '{profile.name}' ({profile.width_mm}mm x {profile.height_mm}mm).")

    items = [
        production.LayoutRequestItem(
            catalog_art_id, reference, width_mm, height_mm,
            quantity=copies_per_row, max_per_row=copies_per_row)
        for catalog_art_id, reference, _page_number, _original_image_path, _preview_path, _review_status in arts
    ]

    print(f"Calculando layout para {len(items)} peça(s) ({copies_per_row} cópia(s) por figura, "
          f"todas em {width_mm:g}mm x {height_mm:g}mm)...")
    try:
        plan = production.calculate_layout(items, profile)
    except ValueError as ex:
        print(f"ERRO ao calcular o layout: {ex}")
        return

    print(f"Layout calculado: {len(plan.pages)} página(s), {plan.total_art_count} peça(s) no total.")
    print("Conectando ao CorelDRAW (abra o CorelDRAW antes se quiser acompanhar ao vivo)...")

    corel = coreldraw_service.CorelDrawService()
    corel.connect()

    master_cdr_path = db.get_catalog_master_cdr_path(catalog_id)
    artwork_sources_by_id = {}
    master_documents_by_path = {}
    for catalog_art_id, reference, _page_number, original_image_path, _preview_path, _review_status in arts:
        master_entry = db.get_master_ref_entry(catalog_id, master_artwork.normalize_ref_number(reference)) \
            if master_cdr_path and reference else None

        if master_cdr_path and master_entry:
            page_index, shape_path, _med_w, _med_h = master_entry
            if master_cdr_path not in master_documents_by_path:
                print(f"Abrindo arquivo original '{master_cdr_path}'...")
                master_documents_by_path[master_cdr_path] = _open_master_for_production(corel, master_cdr_path)
            artwork_sources_by_id[catalog_art_id] = {
                "kind": "master", "document": master_documents_by_path[master_cdr_path],
                "page_index": page_index, "shape_path": shape_path,
            }
        else:
            artwork_sources_by_id[catalog_art_id] = {"kind": "file", "path": original_image_path}

    # force_orientation=True: every piece must come out vertical here
    # regardless of how it sits in the master file (explicit request --
    # unlike a normal queue-based run, which keeps each piece in its own
    # native orientation).
    result = production_generator.generate_unified(corel, plan, profile, artwork_sources_by_id, force_orientation=True)
    _close_production_masters(corel, result)

    if not result.success:
        status = "PARCIAL (alguns itens foram criados antes do erro)" if result.is_partial else "FALHOU"
        print(f"Geração {status}: [{result.error_code}] {result.error_message}")
        db.insert_production(_profile_id_or_default(profile_id), None, "Failed", None, None)
        return

    if result.validation_warning:
        print(f"AVISO: {result.validation_warning} (não travou a produção -- só registro).")

    if result.skipped_pieces:
        linhas = "\n".join(
            f"  • {ref or f'id={cat_id}'}: {motivo}" for cat_id, ref, motivo in result.skipped_pieces)
        print(f"AVISO: {len(result.skipped_pieces)} peça(s) NÃO entraram nessa produção:\n{linhas}")

    try:
        corel.save_document(result.document, cdr_output_path, get_target_corel_version())
    except Exception as ex:
        print(f"AVISO: geração concluída no CorelDRAW mas falhou ao salvar em '{cdr_output_path}': {ex}")
        print("Salve manualmente pelo CorelDRAW (Ctrl+S).")
        cdr_output_path = None
    else:
        print(f"Arquivo salvo em: {cdr_output_path}")

    production_id = db.insert_production(_profile_id_or_default(profile_id), cdr_output_path, "Completed", None, None)
    # Same one-insert-per-piece-group shape as do_generate_production.
    for page in plan.pages:
        groups: dict[tuple, int] = {}
        for row in page.rows:
            for piece in row.pieces:
                key = (piece.catalog_art_id, piece.reference, piece.width_mm, piece.height_mm, piece.orientation)
                groups[key] = groups.get(key, 0) + 1
        for (catalog_art_id, reference, piece_width_mm, piece_height_mm, orientation), qty in groups.items():
            db.insert_production_item(
                production_id, catalog_art_id, reference, piece_width_mm, piece_height_mm, orientation, qty,
                page.page_number)

    print(f"Produção {production_id} concluída: {result.pages_created} página(s), "
          f"{result.shapes_created} forma(s) criada(s) no CorelDRAW.")


def _fmt_cm(value: float) -> str:
    """9.0 -> "9", 8.5 -> "8,5" -- vírgula decimal (padrão BR), sem zero à
    toa, pra bater com o jeito que a medida já aparece nos catálogos."""
    return f"{value:g}".replace(".", ",")


_BUDGET_CURRENCY_FORMAT = 'R$ #,##0.00'


def do_generate_budget(production_id: int, output_path: str) -> list[str]:
    """Builds an editable .xlsx quote from a past production run, in the
    same shape as the store's own paper template: header with client name/
    phone/representative/date (CNPJ, e-mail, payment terms, frete and
    address left blank -- the operator fills those in by hand, see
    gui_page_queue.py), one line per REF with quantity and unit price looked
    up from the price table (product_prices, matched by the REF's catalog's
    tipo_produto+material and its nominal size -- see db.find_product_price
    and db.set_catalog_tipo_produto), and a totals block using real Excel
    formulas (item totals = quantity*price, frete is a manual cell, grand
    total = subtotal+frete) so editing anything in the sheet afterward keeps
    the totals correct without the operator having to redo the math.

    Returns the list of REFs whose price wasn't found in the table (left
    blank in the PREÇO/PREÇO TOTAL columns instead of guessing) -- the
    caller should tell the operator to fill those in and/or cadastrar the
    missing size in the Tabela de Preços page."""
    production_row = db.get_production(production_id)
    if production_row is None:
        raise ValueError(f"Produção {production_id} não encontrada.")
    _production_id, client_name, client_phone, client_representative = production_row

    line_items = db.get_production_items_for_budget(production_id)
    if not line_items:
        raise ValueError(f"Produção {production_id} não tem nenhuma peça registrada -- nada pra orçar.")

    green_fill = PatternFill("solid", fgColor="D6E4BC")
    yellow_fill = PatternFill("solid", fgColor="FFFF00")
    thin_side = Side(style="thin", color="999999")
    border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    bold_font = Font(bold=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Orçamento"
    ws.column_dimensions["A"].width = 24
    for col in "BCD":
        ws.column_dimensions[col].width = 20

    def header_field_row(row: int, label: str, value=""):
        """Label alone in column A (bold, green), value merged across B:D --
        the *LOJA/*CNPJ/*TELEFONE/... rows at the top of the template."""
        label_cell = ws.cell(row, 1, label)
        label_cell.font = bold_font
        label_cell.fill = green_fill
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
        ws.cell(row, 2, value)
        for col in range(1, 5):
            ws.cell(row, col).border = border

    header_field_row(1, "*LOJA", client_name or "")
    header_field_row(2, "*CNPJ:")
    header_field_row(3, "*TELEFONE:", client_phone or "")
    header_field_row(4, "*E-MAIL:")
    header_field_row(5, "*REPRESENTANTE:", client_representative or "")
    header_field_row(6, "*COND. PAGAMENTO:")
    header_field_row(7, "FRETE:")
    header_field_row(8, "*DATA DO PEDIDO:", datetime.date.today().strftime("%d/%m/%Y"))

    # ENDEREÇO -- same idea, but taller (3 rows) since it's normally a
    # longer text than the single-line fields above.
    address_row = 10
    ws.cell(address_row, 1, "ENDEREÇO").font = bold_font
    ws.cell(address_row, 1).fill = green_fill
    ws.merge_cells(start_row=address_row, start_column=1, end_row=address_row + 2, end_column=1)
    ws.merge_cells(start_row=address_row, start_column=2, end_row=address_row + 2, end_column=4)
    for row in range(address_row, address_row + 3):
        for col in range(1, 5):
            ws.cell(row, col).border = border

    # Row map below the address block (rows 10-12): 13 blank spacer, 14-16
    # totals, 17 blank spacer, 18 items table header, 19+ item rows.
    totals_start_row = address_row + 4
    items_header_row = totals_start_row + 4

    def totals_row(row: int, label: str, value, bold: bool = False):
        """PREÇO TOTAL / FRETE / PREÇO TOTAL block -- label spans A:C (wide,
        like the template), value alone in D. `value` can be a plain number
        or an "=..." formula string (openpyxl treats a leading "=" as a
        real formula automatically)."""
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
        label_cell = ws.cell(row, 1, label)
        label_cell.fill = green_fill
        value_cell = ws.cell(row, 4, value)
        value_cell.number_format = _BUDGET_CURRENCY_FORMAT
        if bold:
            label_cell.font = bold_font
            value_cell.font = bold_font
        for col in range(1, 5):
            ws.cell(row, col).fill = green_fill
            ws.cell(row, col).border = border

    # Header row of the items table (DESCRIÇÃO / QUANT. / PREÇO / PREÇO TOTAL).
    headers = ["DESCRIÇÃO", "QUANT.", "PREÇO", "PREÇO TOTAL"]
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(items_header_row, col, text)
        cell.font = bold_font
        cell.fill = yellow_fill
        cell.border = border

    missing_prices = []
    row = items_header_row + 1
    first_item_row = row
    for catalog_art_id, reference, quantity, tipo_produto, material in line_items:
        locked_size = get_locked_size_for_art(catalog_art_id)
        largura_cm = round(locked_size[0] / 10, 2) if locked_size else None
        altura_cm = round(locked_size[1] / 10, 2) if locked_size else None

        # Catálogo marcado como "os dois" (Têxtil + UV, ver gui_page_catalogs.py) não tem UMA
        # linha própria na Tabela de Preços -- tenta achar pelo Têxtil primeiro, depois pelo UV,
        # já que o preço final depende de qual material o cliente pediu (não dá pra saber aqui).
        materiais_a_tentar = ("Textil", "UV") if material == "TextilUV" else (material,)
        preco = None
        if largura_cm is not None and altura_cm is not None:
            for material_tentativa in materiais_a_tentar:
                preco = db.find_product_price(tipo_produto, material_tentativa, largura_cm, altura_cm)
                if preco is not None:
                    break

        tamanho_txt = f"{_fmt_cm(largura_cm)}X{_fmt_cm(altura_cm)}" if largura_cm is not None else "?"
        descricao = f"{tipo_produto or '(tipo não definido)'} MED {tamanho_txt}CM"

        ws.cell(row, 1, descricao).border = border
        ws.cell(row, 2, quantity).border = border
        preco_cell = ws.cell(row, 3, preco)
        preco_cell.border = border
        preco_cell.number_format = _BUDGET_CURRENCY_FORMAT
        total_cell = ws.cell(row, 4, f"=B{row}*C{row}" if preco is not None else None)
        total_cell.border = border
        total_cell.number_format = _BUDGET_CURRENCY_FORMAT

        if preco is None:
            missing_prices.append(reference or f"id={catalog_art_id}")
        row += 1
    last_item_row = row - 1

    totals_row(totals_start_row, "PREÇO TOTAL", f"=SUM(D{first_item_row}:D{last_item_row})")
    totals_row(totals_start_row + 1, "FRETE", 0)
    totals_row(totals_start_row + 2, "PREÇO TOTAL",
               f"=D{totals_start_row}+D{totals_start_row + 1}", bold=True)

    wb.save(output_path)
    print(f"Orçamento salvo em: {output_path}")
    if missing_prices:
        print(f"AVISO: {len(missing_prices)} peça(s) sem preço cadastrado na Tabela de Preços "
              f"(ficaram em branco -- cadastre o tamanho/tipo delas lá e edite a planilha): "
              f"{', '.join(missing_prices)}")
    return missing_prices


def do_requeue_production(production_id: int) -> int:
    """Puts a past production run's pieces back in the pending queue (same
    catalog_art_id and size actually placed, same client) -- for generating
    that same set again with a different profile, since once a run
    completes its queue items are gone from get_pending_queue_items().
    Returns how many items got re-queued."""
    production = db.get_production(production_id)
    if production is None:
        print(f"ERRO: produção {production_id} não encontrada.")
        return 0
    _id, client_name, client_phone, client_representative = production

    rows = db.get_production_items_for_requeue(production_id)
    if not rows:
        print(f"Produção {production_id} não tem nenhuma peça registrada.")
        return 0

    queued = 0
    already_queued = 0
    # Um order_batch_id só pra esse "Gerar de novo" -- sem isso, essas peças caíam agrupadas na
    # fila com QUALQUER outro pedido pendente do mesmo cliente (mesmo nome+telefone), e "Gerar
    # produção" mostrava/produzia mais peças do que as N que realmente voltaram aqui.
    order_batch_id = db.new_order_batch_id()

    # Clicar "Gerar de novo" duas vezes na mesma produção não pode enfileirar o conjunto duas vezes.
    # (Decidido ANTES de enfileirar qualquer linha: a mesma figura pode voltar em várias linhas,
    # uma por medida.)
    arts_already_pending = {
        art_id for art_id in {r[0] for r in rows}
        if db.is_art_already_pending_for_client(art_id, client_name, client_phone)}

    # Peças com MEDIDA escolhida pela cliente voltam exatamente nessa medida (uma linha por
    # figura + medida). Nunca foram esticadas (com medida escolhida a produção não estica).
    for catalog_art_id, _reference, width_mm, height_mm, medida_texto, quantity in rows:
        if not medida_texto:
            continue
        if catalog_art_id in arts_already_pending:
            already_queued += 1
            continue
        db.add_to_production_queue(
            catalog_art_id, width_mm, height_mm,
            client_name=client_name, client_phone=client_phone,
            client_representative=client_representative, quantity=quantity,
            replaces_production_id=production_id, medida_texto=medida_texto,
            order_batch_id=order_batch_id)
        queued += 1

    # As demais voltam no tamanho do catálogo, uma linha por figura (quantidades somadas).
    plain_totals: dict[int, int] = {}
    for catalog_art_id, _reference, _w, _h, medida_texto, quantity in rows:
        if not medida_texto:
            plain_totals[catalog_art_id] = plain_totals.get(catalog_art_id, 0) + quantity
    for catalog_art_id, quantity in plain_totals.items():
        if catalog_art_id in arts_already_pending:
            already_queued += 1
            continue
        # Tamanho de novo do zero (não o que ficou salvo em production_items)
        # -- esse pode ter sido esticado pra preencher a linha (ver
        # production._stretch_row_to_fill) ou girado por "forçar orientação";
        # o que volta pra fila deve ser sempre o tamanho nominal do catálogo.
        width_mm, height_mm = get_locked_size_for_art(catalog_art_id) or (None, None)
        if width_mm is None:
            print(f"AVISO: id={catalog_art_id} sem tamanho fixo no catálogo -- pulado no reenfileiramento.")
            continue
        db.add_to_production_queue(
            catalog_art_id, width_mm, height_mm,
            client_name=client_name, client_phone=client_phone,
            client_representative=client_representative, quantity=quantity,
            replaces_production_id=production_id, order_batch_id=order_batch_id)
        queued += 1

    if already_queued:
        print(f"{already_queued} figura(s) já estavam na fila pra esse cliente -- não foram duplicadas.")
    print(f"{queued} peça(s) da produção {production_id} de volta na fila "
          f"(cliente: {client_name or 'não identificado'}).")
    return queued


def do_delete_production(production_id: int) -> None:
    """Removes one entry from "Produções anteriores" (history only -- the
    .cdr file already generated on disk is untouched)."""
    db.delete_production(production_id)
    print(f"Produção {production_id} removida do histórico.")


CORELDRAW_VERSION_SETTING_KEY = "corel_target_file_version"
DEFAULT_CORELDRAW_VERSION = 22  # CorelDRAW 2020 -- the oldest version actually used to open these files


def get_target_corel_version() -> int:
    """The file-format version production .cdr files get saved as, so they
    can still be opened on whatever CorelDRAW the actual production computer
    runs -- newer CorelDRAW always reads older files fine, so this should be
    set to the OLDEST CorelDRAW version among everyone who needs to open
    these files, never newer. Configurable (menu option 8) since that oldest
    version can change."""
    return int(db.get_setting(CORELDRAW_VERSION_SETTING_KEY, str(DEFAULT_CORELDRAW_VERSION)))


def set_target_corel_version(version: int) -> None:
    db.set_setting(CORELDRAW_VERSION_SETTING_KEY, str(version))


def do_convert_cdr_version(input_path: str, output_path: str, target_version: int) -> None:
    """Opens whatever shape the file arrives in (a real .cdr, an already-
    extracted folder of one, or a .zip in either form -- see
    master_artwork.ensure_valid_cdr_file) and re-saves it at
    target_version, same mechanism get_target_corel_version's setting
    already drives for production files (coreldraw_service.save_document).
    Saving DOWN to an older version is always safe (any newer CorelDRAW
    reads older files fine); saving to a version newer than what's
    actually installed on this machine isn't meaningful and isn't
    prevented here -- the caller (the GUI page) is what limits the choices
    offered to installed versions."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        staged_path = os.path.join(tmp_dir, "staged.cdr")
        master_artwork.ensure_valid_cdr_file(input_path, staged_path)

        corel = coreldraw_service.CorelDrawService()
        corel.connect()
        print(f"Abrindo '{input_path}'...")
        document = corel.open_document(staged_path)
        try:
            corel.set_units(document)
            print(f"Salvando como versão {target_version}...")
            corel.save_document(document, output_path, target_version)
        finally:
            document.Close()
    print(f"Convertido com sucesso: '{output_path}' (versão {target_version}).")


def _copy_page_into_joined_document(corel, source_document, page, page_index, new_document, layer, x_offset_mm) -> None:
    """One page's worth of shapes, copied out of source_document, pasted
    into new_document's layer, slid to x_offset_mm, then left loose and
    individually editable exactly as they were on their own original
    page. Shared by do_join_pages and do_join_pages_from_files so the
    exact same copy+paste+shift steps aren't duplicated.

    When there's more than one shape, they're grouped ONLY for the
    shift itself (one COM call moving one rigid block instead of
    hundreds of individual SetPositionEx calls -- CorelDRAW was seen
    live to struggle, slow and glitchy on redraw/zoom, moving that many
    shapes any other way) and ungrouped again right after -- the
    group is a means to move them, never part of the actual result the
    operator wants to keep."""
    shape_count = page.Shapes.Count
    if shape_count > 0:
        shapes = [page.Shapes.Item(i) for i in range(1, shape_count + 1)]
        corel.copy_shapes(source_document, shapes)
        pasted = corel.paste_shapes(new_document, layer)
        if len(pasted) > 1:
            group = corel.group_shapes(new_document, pasted)
            corel.shift_shapes([group], x_offset_mm)
            corel.ungroup_shape(group)
        else:
            corel.shift_shapes(pasted, x_offset_mm)
        print(f"  página {page_index}: {shape_count} forma(s) coladas em x={x_offset_mm:g}mm.")
    else:
        print(f"  página {page_index}: sem nada pra copiar (vazia).")


def do_fix_shape_sizes_in_active_document(
    target_sizes_mm: list[tuple[float, float]], tolerance_mm: float = 1.0,
) -> tuple[int, int]:
    """"Corrigir Tamanho": goes through EVERY page of whatever CorelDRAW document is currently open
    and active, and for each shape whose LONG side is reasonably close to one of target_sizes_mm
    (within MATCH_THRESHOLD_MM -- since a piece may be sitting either deitada or em pé, matching is
    by long side, not width/height directly) resizes it to that target size EXACTLY when it's off
    by more than tolerance_mm -- for fixing a production file where some pieces got generated at
    the wrong measure (ex: some 488x111mm faixas came out at a slightly different height). A shape
    whose long side isn't close to ANY target (a REF caption, a decorative label, anything that
    isn't one of the sizes being corrected) is left alone and doesn't count toward either total. A
    piece already within tolerance of its closest target is also left untouched. Either way, a
    shape's own top-left corner position is preserved (SetSize alone can shift it). Returns
    (fixed_count, already_ok_count)."""
    MATCH_THRESHOLD_MM = 20.0

    corel = coreldraw_service.CorelDrawService()
    corel.connect()
    document = corel._application.ActiveDocument
    if document is None:
        raise RuntimeError("Nenhum documento está aberto no CorelDRAW.")
    corel.set_units(document)

    # (comprido, curto) pra cada alvo -- não importa em que ordem width/height vieram.
    targets = [(max(w, h), min(w, h)) for w, h in target_sizes_mm]

    fixed = 0
    already_ok = 0
    for page_index in range(1, document.Pages.Count + 1):
        page = document.Pages.Item(page_index)
        for shape_index in range(1, page.Shapes.Count + 1):
            shape = page.Shapes.Item(shape_index)
            width_mm, height_mm = corel.get_shape_size(shape)
            long_mm, short_mm = max(width_mm, height_mm), min(width_mm, height_mm)
            target_long_mm, target_short_mm = min(targets, key=lambda t: abs(t[0] - long_mm))

            if abs(long_mm - target_long_mm) > MATCH_THRESHOLD_MM:
                continue  # não é uma dessas peças (ex: legenda/REF) -- não mexe

            if abs(long_mm - target_long_mm) <= tolerance_mm and abs(short_mm - target_short_mm) <= tolerance_mm:
                already_ok += 1
                continue

            is_landscape = width_mm >= height_mm
            final_width_mm = target_long_mm if is_landscape else target_short_mm
            final_height_mm = target_short_mm if is_landscape else target_long_mm

            left_mm, top_mm = corel.get_shape_position(shape)
            corel.resize_artwork(shape, final_width_mm, final_height_mm)
            corel.position_artwork(shape, left_mm, top_mm)
            fixed += 1
            print(f"Página {page_index}: peça {width_mm:.1f}x{height_mm:.1f}mm corrigida pra "
                  f"{final_width_mm:.1f}x{final_height_mm:.1f}mm (alvo: {target_long_mm:g}x{target_short_mm:g}mm).")

    print(f"Concluído: {fixed} peça(s) corrigida(s), {already_ok} já estavam certas.")
    return fixed, already_ok


def do_join_pages(save_path: str, spacing_mm: float = 0.0) -> None:
    """Takes whatever CorelDRAW document is currently open and active
    (built for the shop's continuous "faixa"/roll production files,
    which end up split into several 2000mm-tall pages even though
    they're really meant to be one long strip) and builds a brand-new
    document with a SINGLE page holding every one of the original's
    pages side by side, in the same order, each one shifted right by the
    running total of every earlier page's own width (plus spacing_mm
    between them) -- "Ajuntador de Páginas". The new page keeps the
    FIRST source page's own size exactly as-is -- it is NOT widened to
    fit every page (explicitly rejected: a wide custom page just to
    contain everything isn't wanted here), so from the second page on,
    content lands past the visible page edge on purpose; CorelDRAW
    doesn't clip anything there, and this is meant for one page/one
    canvas with everything on it, not a page whose rectangle visually
    encloses it all. The original document is only ever read from
    (copy_shapes never mutates the source) and never saved over; the
    new, joined document is what gets saved to save_path and left open
    to look at."""
    corel = coreldraw_service.CorelDrawService()
    corel.connect()
    source_document = corel._application.ActiveDocument
    if source_document is None:
        raise RuntimeError("Nenhum documento está aberto no CorelDRAW.")
    corel.set_units(source_document)

    page_count = source_document.Pages.Count
    if page_count < 2:
        raise RuntimeError(
            f"O documento aberto ('{source_document.Name}') só tem {page_count} página -- nada para juntar.")

    page_sizes = []
    for page_index in range(1, page_count + 1):
        page = source_document.Pages.Item(page_index)
        page_sizes.append((page.SizeWidth, page.SizeHeight))
    first_page_width_mm, first_page_height_mm = page_sizes[0]
    print(f"{page_count} página(s) encontrada(s) em '{source_document.Name}' -- página final fica "
          f"do mesmo tamanho da primeira ({first_page_width_mm:g}mm x {first_page_height_mm:g}mm).")

    new_document = corel.create_production_document()
    corel.set_units(new_document)
    new_page = corel.get_active_page(new_document)
    corel.set_page_size(new_page, first_page_width_mm, first_page_height_mm)
    layer = corel.create_layer(new_page, "JUNTADO")

    x_offset_mm = 0.0
    for page_index in range(1, page_count + 1):
        source_page = source_document.Pages.Item(page_index)
        page_width_mm, _page_height_mm = page_sizes[page_index - 1]
        _copy_page_into_joined_document(
            corel, source_document, source_page, page_index, new_document, layer, x_offset_mm)
        x_offset_mm += page_width_mm + spacing_mm

    corel.save_document(new_document, save_path, get_target_corel_version())
    print(f"Documento juntado salvo em: {save_path}")


def do_join_pages_from_files(input_paths: list[str], save_path: str, spacing_mm: float = 0.0) -> None:
    """Like do_join_pages, but instead of working off whatever's already
    open in CorelDRAW, opens several master .cdr files chosen straight
    from the computer (see master_artwork.ensure_valid_cdr_file for
    accepted formats) and joins EVERY page from EVERY one of them, in
    the order given, onto one single final page -- x_offset_mm keeps
    accumulating across file boundaries the exact same way it does
    across pages within one file, so the result reads as one continuous
    strip no matter how many separate catalogs it came from. The final
    page's own size is fixed from the very first page of the very first
    file (never widened to fit everything -- same rule as
    do_join_pages), so content from a later page or a later file simply
    lands past the visible edge on purpose. Each source file is opened
    only long enough to copy its pages, then closed -- unlike
    do_join_pages (which works off a document the operator is already
    looking at and leaves it exactly as found), these were never open to
    begin with and aren't left open either."""
    valid_paths = []
    for raw_path in input_paths:
        clean_path = raw_path.strip().strip('"')
        if not os.path.exists(clean_path):
            print(f"AVISO: não encontrado, ignorando: {clean_path}")
            continue
        valid_paths.append(clean_path)
    if not valid_paths:
        raise RuntimeError("Nenhum arquivo válido informado.")

    corel = coreldraw_service.CorelDrawService()
    corel.connect()

    new_document = None
    layer = None
    x_offset_mm = 0.0

    for file_number, input_path in enumerate(valid_paths, start=1):
        print(f"\n=== Arquivo {file_number}/{len(valid_paths)}: '{os.path.basename(input_path)}' ===")
        source_document = None
        try:
            staged_path = os.path.join(tempfile.gettempdir(), f"pa_join_pages_{uuid.uuid4().hex}.cdr")
            try:
                master_artwork.ensure_valid_cdr_file(input_path, staged_path)
            except ValueError as ex:
                print(f"ERRO: {ex} -- pulando esse arquivo.")
                continue

            source_document = corel.open_document(staged_path)
            corel.set_units(source_document)
            page_count = source_document.Pages.Count
            print(f"{page_count} página(s) nesse arquivo.")

            for page_index in range(1, page_count + 1):
                page = source_document.Pages.Item(page_index)
                page_width_mm, page_height_mm = page.SizeWidth, page.SizeHeight

                if new_document is None:
                    new_document = corel.create_production_document()
                    corel.set_units(new_document)
                    new_page = corel.get_active_page(new_document)
                    corel.set_page_size(new_page, page_width_mm, page_height_mm)
                    layer = corel.create_layer(new_page, "JUNTADO")
                    print(f"Página final fica do tamanho da 1ª página do 1º arquivo "
                          f"({page_width_mm:g}mm x {page_height_mm:g}mm).")

                _copy_page_into_joined_document(
                    corel, source_document, page, page_index, new_document, layer, x_offset_mm)
                x_offset_mm += page_width_mm + spacing_mm
        finally:
            if source_document is not None:
                try:
                    source_document.Close()
                except Exception:
                    pass

    if new_document is None:
        raise RuntimeError("Nenhuma página encontrada em nenhum dos arquivos.")

    corel.save_document(new_document, save_path, get_target_corel_version())
    print(f"Documento juntado salvo em: {save_path}")


def _profile_id_or_default(profile_id: int | None) -> int:
    if profile_id is not None:
        return profile_id
    row = db.get_default_profile()
    return row[0]


def do_produce_from_master(
    master_cdr_path: str, ref_number: str, width_mm: float, height_mm: float,
    cdr_output_path: str, profile_id: int | None = None,
) -> None:
    """Generates a production sheet by pulling the REAL vector artwork straight
    out of the designer's master .cdr file (see master_artwork.py), instead of
    the raster crop taken from the customer-facing PDF catalog. Standalone
    command -- doesn't touch the database -- for testing/using a REF from a
    master file that isn't hooked up to an imported catalog yet."""
    if not os.path.isfile(master_cdr_path):
        print(f"ERRO: arquivo não encontrado: {master_cdr_path}")
        return

    profile = _load_profile(profile_id)
    normalized_ref = master_artwork.normalize_ref_number(ref_number)

    corel = coreldraw_service.CorelDrawService()
    corel.connect()

    print(f"Abrindo arquivo mestre '{master_cdr_path}'...")
    master_document = corel.open_document(master_cdr_path)
    corel.set_units(master_document)

    print("Mapeando REF -> arte original (isso lê todas as páginas)...")
    ref_index = master_artwork.build_ref_index(master_document)
    print(f"{len(ref_index)} referência(s) encontrada(s) no arquivo mestre.")

    if normalized_ref not in ref_index:
        print(f"ERRO: REF '{ref_number}' não encontrada no arquivo mestre.")
        return

    entry = ref_index[normalized_ref]
    ref_to_shape_location = {normalized_ref: (entry["page_index"], entry["shape_path"])}

    item = production.LayoutRequestItem(1, normalized_ref, width_mm, height_mm)
    print(f"Calculando layout para REF {normalized_ref} ({width_mm}mm x {height_mm}mm)...")
    try:
        plan = production.calculate_layout([item], profile)
    except ValueError as ex:
        print(f"ERRO ao calcular o layout: {ex}")
        return

    print(f"Layout calculado: {len(plan.pages)} página(s), {plan.total_art_count} peça(s) no total.")
    print("Copiando a arte original e montando a produção...")

    result = production_generator.generate_from_master(corel, plan, profile, master_document, ref_to_shape_location)

    if not result.success:
        status = "PARCIAL" if result.is_partial else "FALHOU"
        print(f"Geração {status}: [{result.error_code}] {result.error_message}")
        return

    corel.save_document(result.document, cdr_output_path, get_target_corel_version())
    print(f"Arquivo salvo em: {cdr_output_path}")
    print(f"Produção concluída: {result.pages_created} página(s), {result.shapes_created} forma(s) criada(s).")


def do_publish_catalog(catalog_id: int | None = None) -> None:
    """Sends one catalog's approved arts (REF + preview image) to the public
    website as its own titled section. Each publish only replaces THAT
    catalog's section (see publicar.php's catalogo-scoped upsert) -- other
    catalogs already on the site are left alone, so multiple imports coexist
    as separate sections instead of wiping each other out. catalog_id=None
    republishes every "Ready" catalog with approved arts, one section each."""
    if catalog_id is None:
        catalog_rows = [row for row in db.get_all_catalogs() if (row[5] or 0) > 0]
    else:
        catalog_rows = [row for row in db.get_all_catalogs() if row[0] == catalog_id]
        if not catalog_rows:
            print(f"ERRO: catálogo {catalog_id} não encontrado.")
            return

    total_published = 0
    for row in catalog_rows:
        this_catalog_id, name = row[0], row[1]
        catalog_sizes = db.get_catalog_available_sizes(this_catalog_id)
        site_category = db.get_catalog_categoria_site(this_catalog_id)
        arts = [
            (art_id, reference, original_path, preview_path)
            for art_id, reference, _page_number, original_path, preview_path, review_status
            in db.get_arts_with_paths_by_catalog_id(this_catalog_id)
            if review_status == "Approved" and reference
        ]
        products = []
        for art_id, reference, original_path, preview_path in arts:
            if not (preview_path and os.path.isfile(preview_path)):
                continue
            # "nome" used to always go None -- catalog_arts has no separate
            # display name, just the REF -- so the site's card only ever
            # showed the bare reference, never the size. get_locked_size_for_art
            # is the same size the printed catalog's own "MED WxHMM" caption
            # uses (see gerador_catalogos.py), so this matches what's already
            # printed, not a different/second measurement.
            size = get_locked_size_for_art(art_id)
            nome = f"MED {round(size[1])}X{round(size[0])}MM" if size else None
            # Bigger, sharper JPEG made straight from the real original --
            # sent alongside the small preview specifically for the site's
            # zoom popup (see image_storage.generate_zoom_jpeg_bytes);
            # None just leaves that REF's existing zoom image on the site
            # untouched if this one original happens to be missing.
            grande_bytes = None
            if original_path and os.path.isfile(original_path):
                try:
                    grande_bytes = image_storage.generate_zoom_jpeg_bytes(original_path)
                except Exception:
                    grande_bytes = None
            products.append({
                "referencia": reference, "nome": nome, "imagem_path": preview_path,
                "imagem_grande_bytes": grande_bytes,
                "medidas": catalog_sizes,
            })
        if not products:
            print(f"\"{name}\": nenhuma arte aprovada com REF e imagem disponível -- pulado.")
            continue

        print(f"Publicando \"{name}\" ({len(products)} produto(s)) no site "
              f"(substitui só a seção desse catálogo)...")
        published = website_sync.publish_catalog(name, products, categoria=site_category)
        db.mark_catalog_published(this_catalog_id)
        total_published += published
        print(f"  ok: {published} produto(s) publicado(s) em \"{name}\".")

    if total_published == 0:
        print("Nenhum produto foi publicado.")
        return
    print(f"Publicado com sucesso: {total_published} produto(s) no total em https://babyluzconfeccao.com.br/")
    _sync_catalog_order_quietly()


def do_create_personalized_catalog(catalog_ids: list[int], client_name: str) -> str:
    """Generates a personalized showcase link for one specific client with
    one or more catalogs -- all included in one link, so the client sees
    every selected catalog at ?c=<codigo>. Returns the full URL.

    For private (is_private=1) catalogs: if a catalog has never been
    published, publishes it privately first. Public catalogs must already
    be published -- this does NOT re-publish them."""
    client_name = client_name.strip()
    if not client_name:
        raise RuntimeError("Nome do cliente não pode ser vazio.")
    if not catalog_ids:
        raise RuntimeError("Selecione pelo menos um catálogo.")

    all_catalogs = {r[0]: r for r in db.get_all_catalogs()}
    catalog_names = []
    for catalog_id in catalog_ids:
        row = all_catalogs.get(catalog_id)
        if row is None:
            raise RuntimeError(f"Catálogo {catalog_id} não encontrado.")
        catalog_name = row[1]
        published_at = row[7]
        is_private = bool(db.get_catalog_is_private(catalog_id))
        if is_private and not published_at:
            print(f'Catálogo privado "{catalog_name}" ainda não publicado -- publicando agora...')
            _publish_catalog_private(catalog_id, catalog_name)
        catalog_names.append(catalog_name)

    codigo = website_sync.create_personalized_catalog(catalog_names, client_name)
    return f"https://babyluzconfeccao.com.br/?c={codigo}"


def do_create_pedido_link(nome: str, telefone: str) -> str:
    """Returns the full URL for the "WebPedido" link -- a read-only page
    (pedido.html) showing everything this client (matched by exact
    nome+telefone) has ordered, merged across every separate order she's
    placed on the site. Same code every time for the same nome+telefone
    (see website_sync.criar_link_pedido)."""
    nome = nome.strip()
    telefone = telefone.strip()
    if not nome or not telefone:
        raise RuntimeError("Nome e telefone do cliente são obrigatórios.")
    codigo = website_sync.criar_link_pedido(nome, telefone)
    # pedido.php (não .html direto): mesmo conteúdo, mas com a prévia do
    # WhatsApp já personalizada com o nome da cliente -- ver site pedido.php.
    return f"https://babyluzconfeccao.com.br/pedido.php?c={codigo}"


def do_create_pedido_link_for_production(production_id: int) -> tuple[str, list[str], int]:
    """WebPedido link of one past production ("Produções anteriores"): the
    page shows exactly what THAT production produced (each catalog+REF with
    its total quantity), not every site order the client ever placed --
    those can differ (quantities adjusted before generating, old test
    orders under the same name+phone...). Same link every time for the same
    production. Returns (url, items missing on the site, how many missing)."""
    production = db.get_production(production_id)
    if production is None:
        raise RuntimeError(f"Produção {production_id} não encontrada.")
    _id, client_name, client_phone, _representative = production
    client_name, client_phone = (client_name or "").strip(), (client_phone or "").strip()
    if not client_name or not client_phone:
        raise RuntimeError("Essa produção não tem nome e telefone do cliente.")
    items = db.get_production_items_with_catalog(production_id)
    if not items:
        raise RuntimeError("Essa produção não tem nenhuma figura.")
    codigo, missing, missing_total = website_sync.criar_link_pedido_producao(
        client_name, client_phone, f"prod-{production_id}",
        [{"catalogo_nome": catalog_name, "referencia": reference, "quantidade": int(quantity)}
         for catalog_name, reference, quantity in items])
    return f"https://babyluzconfeccao.com.br/pedido.php?c={codigo}", missing, missing_total


def _publish_catalog_private(catalog_id: int, catalog_name: str) -> None:
    """Publishes one private catalog to the site with privado=True -- same
    pipeline as do_publish_catalog but for a single private catalog."""
    catalog_sizes = db.get_catalog_available_sizes(catalog_id)
    site_category = db.get_catalog_categoria_site(catalog_id)
    arts = [
        (art_id, reference, original_path, preview_path)
        for art_id, reference, _page_number, original_path, preview_path, review_status
        in db.get_arts_with_paths_by_catalog_id(catalog_id)
        if review_status == "Approved" and reference
    ]
    products = []
    for art_id, reference, original_path, preview_path in arts:
        if not (preview_path and os.path.isfile(preview_path)):
            continue
        size = get_locked_size_for_art(art_id)
        nome = f"MED {round(size[1])}X{round(size[0])}MM" if size else None
        grande_bytes = None
        if original_path and os.path.isfile(original_path):
            try:
                grande_bytes = image_storage.generate_zoom_jpeg_bytes(original_path)
            except Exception:
                pass
        products.append({
            "referencia": reference, "nome": nome, "imagem_path": preview_path,
            "imagem_grande_bytes": grande_bytes, "medidas": catalog_sizes,
        })
    if not products:
        raise RuntimeError(
            f'"{catalog_name}": nenhuma arte aprovada com REF e imagem -- '
            "importe e aprove o catálogo antes de gerar o link.")
    print(f'Publicando "{catalog_name}" ({len(products)} produto(s)) como privado...')
    published = website_sync.publish_catalog(catalog_name, products, privado=True, categoria=site_category)
    db.mark_catalog_published(catalog_id)
    print(f'  ok: {published} produto(s) publicado(s) em "{catalog_name}" (privado).')


def do_list_website_orders() -> list[dict]:
    pedidos = website_sync.list_pedidos("pendente")
    if not pedidos:
        print("Nenhum pedido pendente no site.")
        return []
    for pedido in pedidos:
        refs = ", ".join(
            f"{item['referencia']} ({item['medida']})" if item.get("medida") else item["referencia"]
            for item in pedido["itens"]
        ) or "(nenhum item)"
        print(f"  pedido_id={pedido['pedido_id']}  {pedido['nome']} ({pedido['telefone']})  "
              f"em {pedido['criado_em']}  itens: {refs}")
    return pedidos


def _find_arts_for_site_item(item: dict):
    """Approved local arts for one site order line. The same REF number exists
    in many catalogs, so when the site sent the catalog name (catalogo_nome) the
    search is restricted to the local catalog of that name first; falls back to
    every catalog (the old behavior) only if that finds nothing."""
    reference = item["referencia"]
    catalog_name = item.get("catalogo_nome")
    if catalog_name:
        catalog_ids = db.get_catalog_ids_by_name(catalog_name)
        if catalog_ids:
            matches = db.find_approved_arts_by_reference(reference, catalog_ids)
            if matches:
                return matches
    return db.find_approved_arts_by_reference(reference)


def _size_for_measure_rule(
    rule: dict, base_size: tuple[float, float] | None, pixel_size: tuple[int, int] | None,
) -> tuple[float, float] | None:
    """(width_mm, height_mm) to PRODUCE a piece at the measure the customer picked
    on the site (rule = the site's regras_medidas entry: modo, maior, menor).
    - "fixa": exactly maior x menor (long x short side), oriented like the art.
    - "proporcional": the art's long side becomes `maior`, the short side follows
      its own proportion (and is scaled down further if it would pass `menor`).
    The art's proportion/orientation comes from its recorded size, or from its
    saved image when it has none; None if neither is known."""
    reference_dims = base_size or pixel_size
    if not reference_dims:
        return None
    width0, height0 = float(reference_dims[0]), float(reference_dims[1])
    landscape = width0 >= height0
    maior = float(rule["maior"])
    menor = rule.get("menor")

    if rule.get("modo") == "fixa" and menor is not None:
        long_side, short_side = maior, float(menor)
    else:
        scale = maior / max(width0, height0)
        long_side, short_side = maior, min(width0, height0) * scale
        if menor is not None and short_side > float(menor):
            shrink = float(menor) / short_side
            long_side, short_side = long_side * shrink, float(menor)
    return (long_side, short_side) if landscape else (short_side, long_side)


def _open_master_for_production(corel, path: str):
    """Opens a catalog's original (master) .cdr so its vector art can be copied into the production.
    Remembers it (corel._masters_opened_here) ONLY when this call really opened it -- a file the operator
    already had open in CorelDRAW is reused as it is and never closed by us (it may hold unsaved work)."""
    target = os.path.normcase(os.path.abspath(path))
    for document in corel._application.Documents:
        try:
            if os.path.normcase(os.path.abspath(document.FullFileName)) == target:
                return document
        except Exception:
            continue
    document = corel.open_document(path)
    if not hasattr(corel, "_masters_opened_here"):
        corel._masters_opened_here = []
    corel._masters_opened_here.append(document)
    return document


def _close_production_masters(corel, result=None) -> None:
    """After a production is generated: closes the master files THIS run opened, so only the production
    document stays open in CorelDRAW (it used to pile up one open tab per catalog), and brings the
    production document back to the front."""
    documents = getattr(corel, "_masters_opened_here", [])
    corel._masters_opened_here = []
    for document in documents:
        try:
            document.Close()
        except Exception as ex:
            print(f"AVISO: não consegui fechar um arquivo original depois da produção ({ex}).")
    production_document = getattr(result, "document", None) if result is not None else None
    if production_document is not None:
        try:
            production_document.Activate()
        except Exception:
            pass


def split_queue_ids_by_kind(queue_ids: list[int]) -> tuple[list[int], list[int]]:
    """(aplique_ids, faixa_ids), in the order given. FAIXA (long strips) and APLIQUE go on DIFFERENT sheets,
    so an order that mixes them is produced in two runs. The kind is the catalog's site category
    (catalogs.categoria_site); a catalog with no category counts as aplique."""
    categories = db.get_queue_categories(list(queue_ids))
    faixa_ids = [qid for qid in queue_ids if categories.get(qid) == "faixa"]
    aplique_ids = [qid for qid in queue_ids if categories.get(qid) != "faixa"]
    return aplique_ids, faixa_ids


def _sort_items_by_size(layout_items: list) -> list:
    """Production goes in SIZE order -- every 90 figure, then every 110, then every 140... -- instead of
    the order the customer picked them. Smallest first (by the piece's longer side, then the shorter);
    pieces of the same size keep the order they were in. Returns a NEW list: the caller's `items` must
    stay in queue order (it is zipped with the queue rows to trace pieces back to their measure)."""
    return sorted(layout_items, key=lambda item: (
        round(max(item.width_mm, item.height_mm), 1), round(min(item.width_mm, item.height_mm), 1)))


def _measure_info_by_piece_height(queue_rows, items, measure_texts: dict) -> dict:
    """{(catalog_art_id, height_mm rounded): (medida_texto, nominal_width_mm, nominal_height_mm)} for
    the queue rows whose size is a customer's measure choice. Keyed by HEIGHT because the sheet only
    ever stretches a piece's WIDTH (production._stretch_row_to_fill), so a placed piece still has its
    layout item's height -- that's how a stretched piece is traced back to its queue row. `items` are the
    layout items in the same order as `queue_rows`."""
    info = {}
    for queue_row, item in zip(queue_rows, items):
        text = measure_texts.get(queue_row[0])
        if text:
            info[(item.catalog_art_id, round(item.height_mm, 1))] = (text, item.width_mm, item.height_mm)
    return info


def do_validate_website_order(pedido_id: int, manual_sizes: dict[str, tuple[float, float]] | None = None) -> None:
    """manual_sizes: {referencia: (width_mm, height_mm)} for REFs whose catalog has
    no locked size from the master file -- without an entry there, such REFs are
    skipped (never silently guessed). If NOTHING ends up queued, the order is
    deliberately NOT marked as validated, so it's not lost -- it stays pending
    (visible again in do_list_website_orders) until it's retried successfully."""
    manual_sizes = manual_sizes or {}
    pedidos = website_sync.list_pedidos("pendente")
    pedido = next((p for p in pedidos if p["pedido_id"] == pedido_id), None)
    if pedido is None:
        print(f"Pedido {pedido_id} não encontrado (ou já não está mais pendente).")
        return

    # Todo item desse pedido compartilha UM order_batch_id -- separa na Fila de Produção de
    # qualquer outro pedido pendente do mesmo cliente (ver db.new_order_batch_id).
    order_batch_id = db.new_order_batch_id()

    added = 0
    not_found = []
    skipped_no_size = []
    for item in pedido["itens"]:
        reference = item["referencia"]
        quantity = item.get("quantidade") or 1
        matches = _find_arts_for_site_item(item)
        if not matches:
            not_found.append(reference)
            continue
        art_id = matches[0][0]
        rule = item.get("regra")
        if rule:
            # A cliente escolheu tipo + medida no site: produz NESSA medida (e não
            # no tamanho original da figura, que é o que do_add_to_queue forçaria).
            size = _size_for_measure_rule(rule, get_locked_size_for_art(art_id), db.get_art_pixel_size(art_id))
            if size is None:
                skipped_no_size.append(reference)
                continue
            width_mm, height_mm = round(size[0], 1), round(size[1], 1)
            db.add_to_production_queue(
                art_id, width_mm, height_mm, client_name=pedido["nome"], client_phone=pedido["telefone"],
                quantity=quantity, client_representative=pedido.get("representante"),
                medida_texto=item.get("texto"), order_batch_id=order_batch_id)
            print(f"  {reference}: {item.get('texto') or ''} -> {width_mm}mm x {height_mm}mm, {quantity} un")
            added += 1
        elif get_locked_size_for_art(art_id) is not None:
            do_add_to_queue(
                art_id, client_name=pedido["nome"], client_phone=pedido["telefone"], quantity=quantity,
                client_representative=pedido.get("representante"), order_batch_id=order_batch_id)
            added += 1
        elif reference in manual_sizes:
            width_mm, height_mm = manual_sizes[reference]
            do_add_to_queue(
                art_id, width_mm, height_mm, client_name=pedido["nome"], client_phone=pedido["telefone"],
                quantity=quantity, client_representative=pedido.get("representante"), order_batch_id=order_batch_id)
            added += 1
        else:
            skipped_no_size.append(reference)

    if not_found:
        print(f"ATENÇÃO: {len(not_found)} REF(s) do pedido não foram encontradas nos catálogos locais "
              f"aprovados: {', '.join(not_found)}. Elas não entraram na fila de produção.")
    if skipped_no_size:
        print(f"ATENÇÃO: {len(skipped_no_size)} REF(s) sem tamanho definido (nem no arquivo original, "
              f"nem informado manualmente) -- NÃO entraram na fila: {', '.join(skipped_no_size)}.")

    if added == 0:
        print(f"Nenhum item entrou na fila -- pedido {pedido_id} NÃO foi marcado como validado "
              f"(continua pendente). Resolva os problemas acima e tente validar de novo.")
        return

    website_sync.validar_pedido(pedido_id)
    print(f"Pedido {pedido_id} validado -- {added} item(ns) adicionados à fila de produção.")


def do_delete_website_order(pedido_id: int) -> None:
    website_sync.excluir_pedido(pedido_id)
    print(f"Pedido {pedido_id} excluído.")


# ---------------------------------------------------------------------------
# Interactive menu -- the default when you just run "python pa.py" with no
# arguments. Walks through the workflow step by step so you never have to
# remember command syntax or quote a file path yourself.
# ---------------------------------------------------------------------------

def _ask(prompt: str) -> str:
    return input(prompt).strip()

def _ask_int(prompt: str) -> int | None:
    raw = _ask(prompt)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        print(f"'{raw}' não é um número válido.")
        return None


def _ask_float(prompt: str) -> float | None:
    raw = _ask(prompt)
    if not raw:
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        print(f"'{raw}' não é um número válido.")
        return None


def _menu_import_master():
    print("\n--- Importar arquivo original (.cdr) ---")
    print("Abrindo o gerenciador de arquivos, escolha o arquivo original do catálogo...")
    input_path = file_picker.pick_master_file()
    if not input_path:
        print("Nenhum arquivo selecionado. Cancelado.")
        return
    print(f"Selecionado: {input_path}")
    name = _ask("Nome para o catálogo (Enter para usar o nome do arquivo): ")
    do_import_from_master(input_path, name or None)


def _menu_list():
    print("\n--- Catálogos ---")
    do_list()


def _ask_size_for_art(catalog_art_id: int) -> tuple[float, float] | None:
    """Prompts for one piece's size, then offers to remember it as the whole
    catalog's default -- so an order with many un-sized REFs from the same
    catalog only asks once, not once per REF. Returns None if cancelled."""
    print("Tamanho de UMA peça impressa (não é o tamanho da área de produção -- essa parte o "
          "sistema calcula sozinho, repetindo essa peça quantas vezes couber). Ex: 100 = 10cm.")
    width_mm = _ask_float("Largura de UMA peça em mm: ")
    height_mm = _ask_float("Altura de UMA peça em mm: ")
    if width_mm is None or height_mm is None or width_mm <= 0 or height_mm <= 0:
        print("Largura e altura precisam ser números positivos. Cancelado.")
        return None

    catalog_id = get_catalog_id_for_art(catalog_art_id)
    if catalog_id is not None:
        catalog_name = db.get_catalog_name(catalog_id) or f"id={catalog_id}"
        apply_all = _ask(
            f"Usar {width_mm}mm x {height_mm}mm pra TODAS as peças de \"{catalog_name}\" "
            f"sem tamanho próprio (não perguntar de novo pra esse catálogo)? (s/n): ")
        if apply_all.lower() == "s":
            do_set_catalog_default_size(catalog_id, width_mm, height_mm)

    return width_mm, height_mm


def _menu_identify():
    print("\n--- Identificar arte pela foto do cliente ---")
    print("Abrindo o gerenciador de arquivos, escolha uma ou mais fotos (Ctrl+clique para várias)...")
    photo_paths = file_picker.pick_image_files()

    if not photo_paths:
        print("Nenhuma foto selecionada. Cancelado.")
        return

    print(f"{len(photo_paths)} foto(s) selecionada(s).")
    results = do_identify(photo_paths)

    for result in results:
        art_id = catalog_name = reference = None
        if result["exact_match"]:
            art_id, catalog_name, reference, _preview_path = result["exact_match"]
        elif result["candidates"]:
            # Offer the top visual candidate too -- just make it clear it's a guess, not a certainty.
            score, art_id, catalog_name, reference, _preview_path = result["candidates"][0]
            print(f"\n  (nenhuma REF lida com certeza nessa foto -- o candidato mais parecido foi "
                  f"{reference or '(sem REF)'} com {score:.0%} de semelhança)")

        if art_id is None:
            continue

        ref_display = reference or "(sem REF)"
        add = _ask(f"\nAdicionar \"{ref_display}\" ({catalog_name}) à fila de produção? (s/n): ")
        if add.lower() != "s":
            continue

        locked_size = get_locked_size_for_art(art_id)
        if locked_size is not None:
            do_add_to_queue(art_id)  # size comes from the master file or catalog default automatically
            continue

        size = _ask_size_for_art(art_id)
        if size is None:
            continue
        do_add_to_queue(art_id, *size)


def _menu_delete():
    print("\n--- Excluir catálogo ---")
    do_list()
    catalog_id = _ask_int("\nDigite o id do catálogo a excluir: ")
    if catalog_id is None:
        print("Cancelado.")
        return
    confirm = _ask(f"Tem certeza que quer excluir o catálogo {catalog_id}? Essa ação não pode ser desfeita (s/n): ")
    if confirm.lower() != "s":
        print("Cancelado.")
        return
    do_delete(catalog_id)


def _menu_add_to_queue():
    print("\n--- Adicionar arte à fila de produção (manual) ---")
    print("Normalmente isso já é oferecido automaticamente na opção 4 (Identificar arte).")
    print("Use esta opção só se você já sabe o id da arte de antes.")
    catalog_art_id = _ask_int(
        "Id da arte (o número interno depois de 'id=' no resultado da busca -- NÃO é o número de REF): ")
    if catalog_art_id is None:
        print("Cancelado.")
        return

    if get_locked_size_for_art(catalog_art_id) is not None:
        do_add_to_queue(catalog_art_id)  # size comes from the master file or catalog default automatically
        return

    size = _ask_size_for_art(catalog_art_id)
    if size is None:
        return
    do_add_to_queue(catalog_art_id, *size)


def _menu_list_queue():
    print("\n--- Fila de produção ---")
    do_list_queue()


def _menu_generate_production():
    print("\n--- Gerar produção no CorelDRAW ---")
    do_list_queue()
    profiles = db.get_all_profiles()
    print("\nPerfis disponíveis:")
    for profile_id, name, width_mm, height_mm, *_ in profiles:
        print(f"  id={profile_id}  {name}  ({width_mm}mm x {height_mm}mm)")
    profile_id = _ask_int("Id do perfil a usar (Enter para usar o perfil padrão): ")

    print("Abrindo o gerenciador de arquivos, escolha onde salvar o .cdr...")
    cdr_path = file_picker.pick_save_path("producao.cdr")
    if not cdr_path:
        print("Nenhum local escolhido. Cancelado.")
        return

    do_generate_production(cdr_path, profile_id)


def _ask_profile_spacing_and_margins():
    print("Espaçamento entre as peças (pra não ficarem grudadas na produção). Ex: 2 = 2mm de vão.")
    spacing_h_mm = _ask_float("Espaçamento horizontal em mm (Enter = 0): ")
    spacing_v_mm = _ask_float("Espaçamento vertical em mm (Enter = 0): ")
    print("Margens da área de produção (distância das bordas -- Enter = 0 em todas).")
    margin_left_mm = _ask_float("Margem esquerda em mm (Enter = 0): ")
    margin_right_mm = _ask_float("Margem direita em mm (Enter = 0): ")
    margin_top_mm = _ask_float("Margem superior em mm (Enter = 0): ")
    margin_bottom_mm = _ask_float("Margem inferior em mm (Enter = 0): ")
    return (
        spacing_h_mm or 0, spacing_v_mm or 0,
        margin_left_mm or 0, margin_right_mm or 0, margin_top_mm or 0, margin_bottom_mm or 0,
    )


def _menu_configure_profile():
    print("\n--- Perfis de produção (tamanho da área/tela) ---")
    do_list_profiles()
    print("\n1. Criar novo perfil")
    print("2. Definir perfil padrão")
    print("3. Editar um perfil existente (espaçamento, margens, tamanho)")
    print(f"4. Configurar versão do CorelDRAW de destino (atual: {get_target_corel_version()}, "
          f"ex: 23 = CorelDRAW 2021)")
    print("0. Voltar")
    choice = _ask("> ")

    if choice == "1":
        name = _ask("Nome do perfil: ")
        width_mm = _ask_float("Largura da área de produção em mm: ")
        height_mm = _ask_float("Altura da área de produção em mm: ")
        if not name or width_mm is None or height_mm is None or width_mm <= 0 or height_mm <= 0:
            print("Nome e dimensões válidas são obrigatórios. Cancelado.")
            return
        spacing_h, spacing_v, margin_l, margin_r, margin_t, margin_b = _ask_profile_spacing_and_margins()
        make_default = _ask("Tornar esse o perfil padrão? (s/n): ").lower() == "s"
        do_create_profile(
            name, width_mm, height_mm, margin_l, margin_r, margin_t, margin_b,
            spacing_h, spacing_v, make_default)
    elif choice == "2":
        profile_id = _ask_int("Id do perfil a tornar padrão: ")
        if profile_id is None:
            print("Cancelado.")
            return
        do_set_default_profile(profile_id)
    elif choice == "3":
        profile_id = _ask_int("Id do perfil a editar: ")
        if profile_id is None:
            print("Cancelado.")
            return
        row = next((p for p in db.get_all_profiles() if p[0] == profile_id), None)
        if row is None:
            print("Perfil não encontrado. Cancelado.")
            return
        (_id, current_name, current_w, current_h, *_rest) = row
        print(f"Editando \"{current_name}\" ({current_w}mm x {current_h}mm). Deixe em branco pra manter.")
        name = _ask(f"Nome (atual: {current_name}): ") or current_name
        width_mm = _ask_float(f"Largura em mm (atual: {current_w}): ")
        height_mm = _ask_float(f"Altura em mm (atual: {current_h}): ")
        spacing_h, spacing_v, margin_l, margin_r, margin_t, margin_b = _ask_profile_spacing_and_margins()
        do_edit_profile(
            profile_id, name, width_mm or current_w, height_mm or current_h,
            margin_l, margin_r, margin_t, margin_b, spacing_h, spacing_v)
    elif choice == "4":
        print("Os arquivos de produção são salvos nessa versão, pra abrir sem erro em qualquer")
        print("computador que use uma versão igual ou mais nova do CorelDRAW. Use a versão mais")
        print("ANTIGA do CorelDRAW que alguém realmente precisa abrir esse arquivo.")
        print("Exemplos: 2021=23, 2020=22, 2019=21, 2018=20, 2017=19 (confira em Ajuda > Sobre).")
        version = _ask_int("Versão (número): ")
        if version is None:
            print("Cancelado.")
            return
        set_target_corel_version(version)
        print(f"Versão de destino definida: {version}.")
    else:
        print("Cancelado.")


def _menu_publish_catalog():
    print("\n--- Publicar catálogo no site ---")
    do_list()
    choice = _ask("Digite o id de um catálogo específico, ou Enter para publicar TODOS os aprovados: ")
    catalog_id = int(choice) if choice.strip().isdigit() else None
    confirm = _ask("Isso substitui TUDO que está no site agora pela lista escolhida. Continuar? (s/n): ")
    if confirm.lower() != "s":
        print("Cancelado.")
        return
    do_publish_catalog(catalog_id)


def _menu_website_orders():
    print("\n--- Pedidos do site (clientes) ---")
    pedidos = do_list_website_orders()
    if not pedidos:
        return
    pedido_id = _ask_int("\nDigite o pedido_id pra validar/excluir (Enter para voltar): ")
    if pedido_id is None:
        return
    pedido = next((p for p in pedidos if p["pedido_id"] == pedido_id), None)
    if pedido is None:
        print("Pedido não encontrado nessa lista.")
        return
    action = _ask("(V)alidar e mandar pra fila de produção, ou (E)xcluir? ").strip().lower()
    if action == "v":
        manual_sizes = {}
        for item in pedido["itens"]:
            reference = item["referencia"]
            matches = db.find_approved_arts_by_reference(reference)
            if not matches:
                continue  # reported as "não encontrada" by do_validate_website_order
            art_id = matches[0][0]
            # Re-checked fresh each time: if an earlier item set a
            # catalog-wide default just below, later items from that same
            # catalog pick it up here and are never asked.
            if get_locked_size_for_art(art_id) is not None:
                continue
            print(f"\nREF {reference} não tem tamanho definido pelo arquivo original.")
            size = _ask_size_for_art(art_id)
            if size is not None:
                manual_sizes[reference] = size
        do_validate_website_order(pedido_id, manual_sizes)
    elif action == "e":
        confirm = _ask(f"Tem certeza que quer excluir o pedido {pedido_id}? (s/n): ")
        if confirm.lower() == "s":
            do_delete_website_order(pedido_id)
        else:
            print("Cancelado.")
    else:
        print("Opção inválida. Cancelado.")


def _print_status_bar():
    """Printed before every menu prompt so the current saved state (catálogos,
    fila) is always visible -- no need to guess whether the last action saved
    or to run a separate command just to check."""
    print("\n" + "-" * 60)
    catalogs = db.get_all_catalogs()
    if not catalogs:
        print("Estado atual: nenhum catálogo importado ainda.")
    else:
        print("Estado atual:")
        for catalog_id, name, status, _created_at, total_arts, approved_arts, arts_with_reference, published_at in catalogs:
            published_txt = ", publicado no site" if published_at else ""
            print(f"  Catálogo id={catalog_id} \"{name}\" [{status}] -- "
                  f"{total_arts or 0} arte(s), {approved_arts or 0} aprovada(s){published_txt}")

    queue_rows = db.get_pending_queue_items()
    if queue_rows:
        print(f"  Fila de produção: {len(queue_rows)} item(ns) pendente(s)")
    else:
        print("  Fila de produção: vazia")
    print("-" * 60)


def run_interactive_menu():
    print("=== Automação de Produção — Terminal ===")
    actions = {
        "1": ("Importar arquivo original (.cdr)", _menu_import_master),
        "2": ("Excluir arquivo original (catálogo)", _menu_delete),
        "3": ("Listar catálogos (detalhado)", _menu_list),
        "4": ("Identificar arte a partir de foto(s) do cliente", _menu_identify),
        "5": ("Adicionar arte à fila de produção", _menu_add_to_queue),
        "6": ("Ver fila de produção (detalhado)", _menu_list_queue),
        "7": ("Gerar produção no CorelDRAW", _menu_generate_production),
        "8": ("Configurar perfis de produção (tamanho da área)", _menu_configure_profile),
        "9": ("Publicar catálogo no site", _menu_publish_catalog),
        "10": ("Ver pedidos do site (validar/excluir)", _menu_website_orders),
        "0": ("Sair", None),
    }
    while True:
        _print_status_bar()
        print("\nEscolha uma opção:")
        for key, (label, _) in actions.items():
            print(f"  {key}. {label}")
        choice = _ask("> ")

        if choice == "0":
            print("Até mais.")
            return
        if choice not in actions:
            print(f"Opção '{choice}' inválida.")
            continue

        _, action_func = actions[choice]
        try:
            action_func()
        except Exception:
            print("\nERRO durante a operação:")
            traceback.print_exc()


# ---------------------------------------------------------------------------
# argparse entry points, for direct one-shot usage / scripting.
# ---------------------------------------------------------------------------

def _cmd_import_master(args):
    do_import_from_master(args.master_path, args.name)


def _cmd_list(args):
    do_list()


def _cmd_identify(args):
    do_identify(args.photo_paths, args.top)


def _cmd_delete(args):
    do_delete(args.catalog_id)


def _cmd_add_to_queue(args):
    do_add_to_queue(args.catalog_art_id, args.width_mm, args.height_mm)


def _cmd_list_queue(args):
    do_list_queue()


def _cmd_generate_production(args):
    do_generate_production(args.cdr_output_path, args.profile_id)


def _cmd_produce_from_master(args):
    do_produce_from_master(
        args.master_cdr_path, args.ref_number, args.width_mm, args.height_mm,
        args.cdr_output_path, args.profile_id)


def _cmd_publish_catalog(args):
    do_publish_catalog(args.catalog_id)


def _cmd_orders_list(args):
    do_list_website_orders()


def _cmd_orders_validate(args):
    do_validate_website_order(args.pedido_id)


def _cmd_orders_delete(args):
    do_delete_website_order(args.pedido_id)


def main():
    db.ensure_schema_extensions()

    if len(sys.argv) == 1:
        run_interactive_menu()
        return

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_import = subparsers.add_parser(
        "import-master", help="Importa um catálogo direto do arquivo original (.cdr/.zip do designer)")
    p_import.add_argument("master_path")
    p_import.add_argument("name", nargs="?", default=None)
    p_import.set_defaults(func=_cmd_import_master)

    p_list = subparsers.add_parser("list", help="Lista catálogos importados")
    p_list.set_defaults(func=_cmd_list)

    p_identify = subparsers.add_parser("identify", help="Busca a arte mais parecida com uma ou mais fotos")
    p_identify.add_argument("photo_paths", nargs="+")
    p_identify.add_argument("--top", type=int, default=5)
    p_identify.set_defaults(func=_cmd_identify)

    p_delete = subparsers.add_parser("delete", help="Exclui um catálogo e suas artes")
    p_delete.add_argument("catalog_id", type=int)
    p_delete.set_defaults(func=_cmd_delete)

    p_queue_add = subparsers.add_parser(
        "queue-add", help="Adiciona uma arte à fila de produção (width/height = tamanho de UMA peça)")
    p_queue_add.add_argument("catalog_art_id", type=int, help="id interno da arte (não é o número de REF)")
    p_queue_add.add_argument("width_mm", type=float, help="largura de UMA peça, em mm")
    p_queue_add.add_argument("height_mm", type=float, help="altura de UMA peça, em mm")
    p_queue_add.set_defaults(func=_cmd_add_to_queue)

    p_queue_list = subparsers.add_parser("queue-list", help="Lista a fila de produção pendente")
    p_queue_list.set_defaults(func=_cmd_list_queue)

    p_generate = subparsers.add_parser("generate", help="Gera a produção no CorelDRAW a partir da fila")
    p_generate.add_argument("cdr_output_path")
    p_generate.add_argument("--profile-id", type=int, default=None, dest="profile_id")
    p_generate.set_defaults(func=_cmd_generate_production)

    p_master = subparsers.add_parser(
        "produce-from-master",
        help="Gera produção usando a arte VETORIAL de verdade de um arquivo .cdr mestre (não o recorte do PDF)")
    p_master.add_argument("master_cdr_path")
    p_master.add_argument("ref_number")
    p_master.add_argument("width_mm", type=float)
    p_master.add_argument("height_mm", type=float)
    p_master.add_argument("cdr_output_path")
    p_master.add_argument("--profile-id", type=int, default=None, dest="profile_id")
    p_master.set_defaults(func=_cmd_produce_from_master)

    p_publish = subparsers.add_parser(
        "publish-catalog", help="Publica as artes aprovadas (com REF) no site para os clientes")
    p_publish.add_argument("--catalog-id", type=int, default=None, dest="catalog_id",
                            help="Publica só esse catálogo (padrão: todos os aprovados)")
    p_publish.set_defaults(func=_cmd_publish_catalog)

    p_orders_list = subparsers.add_parser("orders-list", help="Lista os pedidos pendentes feitos no site")
    p_orders_list.set_defaults(func=_cmd_orders_list)

    p_orders_validate = subparsers.add_parser(
        "orders-validate", help="Valida um pedido do site e manda os itens pra fila de produção")
    p_orders_validate.add_argument("pedido_id", type=int)
    p_orders_validate.set_defaults(func=_cmd_orders_validate)

    p_orders_delete = subparsers.add_parser("orders-delete", help="Exclui um pedido do site")
    p_orders_delete.add_argument("pedido_id", type=int)
    p_orders_delete.set_defaults(func=_cmd_orders_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
