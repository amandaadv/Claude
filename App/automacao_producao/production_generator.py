"""Port of CorelDrawProductionGenerator.cs: walks a ProductionPlan (see
production.py) and drives CorelDrawService to actually build the document --
one page per plan page, one imported shape per row (duplicated for extra
copies), then validates the page/shape counts CorelDRAW reports match what
was planned.
"""
from dataclasses import dataclass, field

import master_artwork

LAYER_NAME = "PRODUÇÃO"


def _cache_key(piece, ident=None):
    """Chave do cache de formas de uma página: figura (ou REF) + TAMANHO. Antes era só a figura:
    a mesma figura pedida em duas medidas diferentes (ex.: 110x100 e 140x120) saía toda no
    tamanho da primeira, porque as cópias seguintes eram duplicatas dela. Só reaproveita a cópia
    quando o tamanho é o mesmo."""
    return (piece.catalog_art_id if ident is None else ident, round(piece.width_mm, 2), round(piece.height_mm, 2))


def _orient_to_native_shape(native_width_mm, native_height_mm, target_long_mm, target_short_mm):
    """Assigns the catalog's two recorded measurements ("REF NNN MED AxB")
    to width/height by matching them to the artwork's own real orientation
    -- whichever side (width or height) is natively longer for this
    specific piece gets the longer of the two recorded numbers -- using
    both exactly as recorded, not a value computed from the piece's native
    proportions. That's deliberate: the two recorded numbers came from
    someone measuring the real intended output size, and take precedence
    over the artwork's raw native size on the page."""
    if native_width_mm >= native_height_mm:
        return target_long_mm, target_short_mm
    return target_short_mm, target_long_mm


@dataclass
class GenerationResult:
    success: bool
    is_partial: bool
    pages_created: int
    shapes_created: int
    error_code: str | None
    error_message: str | None
    document: object = None
    # [(catalog_art_id, reference, motivo)] -- peças que travaram (arte original não encontrada,
    # erro do CorelDRAW ao importar/colar/redimensionar essa figura específica etc) e foram
    # PULADAS em vez de abortar a produção inteira: o resto do pedido sai normal, e essas ficam na
    # fila (não marcadas como produzidas) pra reportar e produzir depois de corrigidas.
    skipped_pieces: list = field(default_factory=list)
    # Contagem de formas não bateu (ver _validate_post_generation) mas isso NUNCA mais trava a
    # produção -- só um aviso pra registro, texto pronto ou None.
    validation_warning: str | None = None


def generate(corel, plan, profile, original_image_paths_by_catalog_art_id: dict) -> GenerationResult:
    pages_created = 0
    shapes_created = 0
    layers_by_page = []
    document = None

    try:
        corel.connect()
        document = corel.create_production_document()
        corel.set_units(document)

        for page_index, plan_page in enumerate(plan.pages):
            page = corel.get_active_page(document) if page_index == 0 else corel.add_page(document)
            pages_created += 1

            corel.set_page_size(page, profile.width_mm, profile.height_mm)
            layer = corel.create_layer(page, LAYER_NAME)
            layers_by_page.append(layer)

            # Reused only within this same page -- a row can now mix
            # several different figures (see production.calculate_layout),
            # so caching moved from "first piece of this row" to "first
            # piece of this figure anywhere on this page" -- keyed by
            # catalog_art_id, reset every page since Duplicate() is only
            # confirmed to land copies on the same page as the original.
            shape_cache: dict[tuple, object] = {}

            for row in plan_page.rows:
                corel_y = profile.height_mm - row.y_mm
                for piece in row.pieces:
                    cached_shape = shape_cache.get(_cache_key(piece))
                    if cached_shape is None:
                        image_path = original_image_paths_by_catalog_art_id.get(piece.catalog_art_id)
                        if not image_path:
                            return GenerationResult(
                                False, shapes_created > 0, pages_created, shapes_created,
                                "ORIGINAL_IMAGE_MISSING",
                                f"Imagem original não encontrada para CatalogArtId {piece.catalog_art_id}.",
                                document)
                        shape = corel.import_artwork(layer, image_path)
                        native_width_mm, native_height_mm = corel.get_shape_size(shape)
                        target_long_mm = max(piece.width_mm, piece.height_mm)
                        target_short_mm = min(piece.width_mm, piece.height_mm)
                        final_width_mm, final_height_mm = _orient_to_native_shape(
                            native_width_mm, native_height_mm, target_long_mm, target_short_mm)
                        corel.resize_artwork(shape, final_width_mm, final_height_mm)
                        shape_cache[_cache_key(piece)] = shape
                    else:
                        shape = corel.duplicate_artwork(cached_shape)
                    corel.position_artwork(shape, piece.x_mm, corel_y)
                    shapes_created += 1

        validation_error = _validate_post_generation(corel, document, plan, layers_by_page)
        if validation_error:
            return GenerationResult(False, True, pages_created, shapes_created, "POST_VALIDATION_FAILED", validation_error, document)

        return GenerationResult(True, False, pages_created, shapes_created, None, None, document)

    except Exception as ex:
        return GenerationResult(False, shapes_created > 0, pages_created, shapes_created, "COREL_GENERATION_FAILED", str(ex), document)


def generate_from_master(corel, plan, profile, master_document, ref_to_shape_location: dict):
    """Same as generate(), but instead of importing a raster PNG per row, copies
    the real vector artwork shape out of the designer's master .cdr document
    (see master_artwork.py) and pastes it in -- the first copy per row comes
    from the master file, further copies in that row are plain in-document
    duplicates of the pasted shape (same as generate())."""
    pages_created = 0
    shapes_created = 0
    layers_by_page = []
    document = None

    try:
        corel.connect()
        document = corel.create_production_document()
        corel.set_units(document)

        for page_index, plan_page in enumerate(plan.pages):
            page = corel.get_active_page(document) if page_index == 0 else corel.add_page(document)
            pages_created += 1

            corel.set_page_size(page, profile.width_mm, profile.height_mm)
            layer = corel.create_layer(page, LAYER_NAME)
            layers_by_page.append(layer)

            # Reused only within this same page (see generate()'s shape_cache
            # for why) -- keyed by reference here since this function looks
            # up artwork by reference, not catalog_art_id.
            shape_cache: dict[tuple, object] = {}

            for row in plan_page.rows:
                corel_y = profile.height_mm - row.y_mm
                for piece in row.pieces:
                    cached_shape = shape_cache.get(_cache_key(piece, piece.reference))
                    if cached_shape is None:
                        location = ref_to_shape_location.get(piece.reference)
                        if location is None:
                            return GenerationResult(
                                False, shapes_created > 0, pages_created, shapes_created,
                                "ORIGINAL_ARTWORK_MISSING",
                                f"Arte original não encontrada no arquivo mestre para referência {piece.reference!r}.",
                                document)
                        master_page_index, shape_path = location
                        master_artwork.copy_artwork_shape(master_document, master_page_index, shape_path)
                        shape = corel.paste_artwork(layer)
                        native_width_mm, native_height_mm = corel.get_shape_size(shape)
                        target_long_mm = max(piece.width_mm, piece.height_mm)
                        target_short_mm = min(piece.width_mm, piece.height_mm)
                        final_width_mm, final_height_mm = _orient_to_native_shape(
                            native_width_mm, native_height_mm, target_long_mm, target_short_mm)
                        corel.resize_artwork(shape, final_width_mm, final_height_mm)
                        shape_cache[_cache_key(piece, piece.reference)] = shape
                    else:
                        shape = corel.duplicate_artwork(cached_shape)
                    corel.position_artwork(shape, piece.x_mm, corel_y)
                    shapes_created += 1

        validation_error = _validate_post_generation(corel, document, plan, layers_by_page)
        if validation_error:
            return GenerationResult(False, True, pages_created, shapes_created, "POST_VALIDATION_FAILED", validation_error, document)

        return GenerationResult(True, False, pages_created, shapes_created, None, None, document)

    except Exception as ex:
        return GenerationResult(False, shapes_created > 0, pages_created, shapes_created, "COREL_GENERATION_FAILED", str(ex), document)


def generate_unified(
    corel, plan, profile, artwork_sources_by_catalog_art_id: dict, force_orientation: bool = False,
    document=None, page_number_offset: int = 0,
):
    """Like generate(), but each row's artwork can come from either source:
    artwork_sources_by_catalog_art_id[catalog_art_id] is either
    {"kind": "file", "path": str} (raster crop from the PDF catalog -- used
    when no master .cdr is configured for that art's catalog) or
    {"kind": "master", "document": <CorelDRAW document>, "page_index": int,
    "shape_path": str} (the real vector artwork, copied from the designer's
    master file). Lets a single production run mix items from catalogs that
    do and don't have a master file configured yet.

    force_orientation: the default (False) keeps every piece in whatever
    orientation it's naturally drawn, assigning the longer of its two
    target numbers to whichever side is naturally longer
    (_orient_to_native_shape) -- right for a normal queue-based run, where
    each client's piece should look like the original. True instead
    physically ROTATES a piece 90 degrees first whenever its native shape
    doesn't already match its target box's own orientation, then resizes
    to that target's width_mm/height_mm exactly as given -- used by
    do_generate_production_for_catalog, where every piece in the run must
    come out standing the same way (typically vertical) regardless of how
    it happens to sit in the master file.

    document: None (default) creates a brand new CorelDRAW document. Pass an existing document
    (from a PREVIOUS generate_unified call's result.document) to instead APPEND pages onto it --
    used to draw aplique and faixa (different orientation rules, so two separate calculate_layout
    + generate_unified passes) into the SAME file, saved once, one card in "Produções anteriores"
    (ver pa.do_generate_production_mixed), instead of two separate .cdr files. page_number_offset:
    how many pages already exist in `document` from a previous pass -- plan_page.page_number in
    the result's production_items stays correct (continues counting from there) instead of
    restarting at 1 and colliding with the first pass's page numbers."""
    pages_created = 0
    shapes_created = 0
    layers_by_page = []
    is_new_document = document is None
    # Uma figura travando (arte original sumiu, CorelDRAW recusa colar/importar/redimensionar
    # ELA especificamente) não pode derrubar um pedido de 300+ peças por causa de UMA -- pula só
    # essa (fica registrada aqui pra reportar e continua fora da fila como pendente) e segue o
    # resto normal. Só aborta tudo (except Exception lá embaixo) se o problema for geral --
    # conexão com o CorelDRAW, documento, página -- não uma peça específica.
    skipped_pieces = []

    try:
        corel.connect()
        if is_new_document:
            document = corel.create_production_document()
            corel.set_units(document)

        for page_index, plan_page in enumerate(plan.pages):
            page = corel.get_active_page(document) if (is_new_document and page_index == 0) else corel.add_page(document)
            plan_page.page_number = page_number_offset + page_index + 1
            pages_created += 1

            corel.set_page_size(page, profile.width_mm, profile.height_mm)
            layer = corel.create_layer(page, LAYER_NAME)
            layers_by_page.append(layer)

            # Reused only within this same page (see generate()'s shape_cache
            # for why).
            shape_cache: dict[tuple, object] = {}
            failed_cache_keys: set = set()  # figura+tamanho que já falhou NESSA página -- não tenta de novo pra cada cópia

            for row in plan_page.rows:
                corel_y = profile.height_mm - row.y_mm
                for piece in row.pieces:
                    cache_key = _cache_key(piece)
                    if cache_key in failed_cache_keys:
                        continue

                    cached_shape = shape_cache.get(cache_key)
                    if cached_shape is None:
                        source = artwork_sources_by_catalog_art_id.get(piece.catalog_art_id)
                        if source is None:
                            skipped_pieces.append(
                                (piece.catalog_art_id, piece.reference, "arte original não encontrada"))
                            failed_cache_keys.add(cache_key)
                            continue

                        try:
                            if source["kind"] == "master":
                                master_artwork.copy_artwork_shape(
                                    source["document"], source["page_index"], source["shape_path"])
                                shape = corel.paste_artwork(layer)
                            else:
                                shape = corel.import_artwork(layer, source["path"])

                            native_width_mm, native_height_mm = corel.get_shape_size(shape)
                            if force_orientation:
                                native_is_landscape = native_width_mm >= native_height_mm
                                target_is_landscape = piece.width_mm >= piece.height_mm
                                if native_is_landscape != target_is_landscape:
                                    corel.rotate_artwork(shape, 90.0)
                                final_width_mm, final_height_mm = piece.width_mm, piece.height_mm
                            else:
                                target_long_mm = max(piece.width_mm, piece.height_mm)
                                target_short_mm = min(piece.width_mm, piece.height_mm)
                                final_width_mm, final_height_mm = _orient_to_native_shape(
                                    native_width_mm, native_height_mm, target_long_mm, target_short_mm)
                            corel.resize_artwork(shape, final_width_mm, final_height_mm)
                        except Exception as ex:
                            skipped_pieces.append((piece.catalog_art_id, piece.reference, str(ex)))
                            failed_cache_keys.add(cache_key)
                            continue
                        shape_cache[cache_key] = shape
                    else:
                        shape = corel.duplicate_artwork(cached_shape)
                    corel.position_artwork(shape, piece.x_mm, corel_y)
                    shapes_created += 1

        # Confere a contagem só pra AVISAR -- nunca mais trava a produção por causa disso. Com
        # peça pulada a contagem nem bate mesmo (normal). E mesmo sem peça pulada, uma arte que é
        # um GRUPO de 2+ formas no arquivo original conta como 2+ pro CorelDRAW mas só 1 peça pra
        # gente -- confirmado ao vivo: pedido de 166 peças (nenhuma pulada) virou 168 formas
        # contadas, e isso travava o pedido inteiro à toa (nada realmente faltou nem duplicou).
        validation_warning = None if skipped_pieces else _validate_post_generation(
            corel, document, plan, layers_by_page, page_number_offset)

        return GenerationResult(
            True, bool(skipped_pieces), pages_created, shapes_created, None, None, document, skipped_pieces,
            validation_warning)

    except Exception as ex:
        return GenerationResult(
            False, shapes_created > 0, pages_created, shapes_created, "COREL_GENERATION_FAILED", str(ex),
            document, skipped_pieces)


def _validate_post_generation(corel, document, plan, layers_by_page, page_number_offset=0) -> str | None:
    # Com page_number_offset > 0 (segunda passada num documento que já tinha páginas de uma
    # passada anterior -- ver generate_unified), o documento inteiro tem mais páginas do que só as
    # dessa passada; soma o offset pra comparar certo.
    actual_page_count = corel.get_page_count(document)
    expected_page_count = page_number_offset + len(plan.pages)
    if actual_page_count != expected_page_count:
        return f"Esperado {expected_page_count} página(s), CorelDRAW reporta {actual_page_count}."

    for i, plan_page in enumerate(plan.pages):
        expected_shape_count = sum(row.quantity for row in plan_page.rows)
        actual_shape_count = corel.get_shape_count_on_layer(layers_by_page[i])
        if actual_shape_count != expected_shape_count:
            return (f"Página {plan_page.page_number}: esperado {expected_shape_count} forma(s), "
                    f"CorelDRAW reporta {actual_shape_count}.")

    return None
