"""Catálogos page: import a master .cdr file, publish one to the site, or delete
one. All the actual work is delegated to pa.py's do_* functions (same code path
already validated from the terminal) -- this page is purely presentation.
"""
import os

import customtkinter as ctk
from PIL import Image

import db
import file_picker
import gui_theme
import gui_worker
import pa
import website_sync

# Rótulo mostrado no dropdown -> valor gravado no banco (os dois primeiros nunca mudam, só o
# texto exibido -- assim continua batendo com o que já está salvo em catálogos antigos e na
# Tabela de Preços sem precisar migrar nada). "TextilUV" é um catálogo que vende os dois --
# some catálogos têm a mesma arte disponível tanto em Têxtil Termocolante quanto em Adesivo UV.
MATERIAIS_SITE = {
    "Têxtil - Termocolante": "Textil",
    "Adesivo - UV": "UV",
    "Os dois (Têxtil + UV)": "TextilUV",
}
# Categoria do catálogo no SITE -- decide quais botões de tipo/medida cada figura
# mostra (aplique: termo colante ou adesivo; faixa: só termo colante).
CATEGORIAS_SITE = {"Aplique": "aplique", "Faixa": "faixa", "Sem categoria (Adicionar antigo)": "sem_categoria"}


# Cor de fundo do card conforme o material -- bem fraca, só pra identificar de relance
# (nenhum material definido ainda = cor neutra de sempre).
MATERIAL_CARD_COLORS = {
    "Textil": ("#e3f7e6", "#193321"),
    "UV": ("#fbe9e7", "#331c19"),
    "TextilUV": ("#e6f0fb", "#17263b"),
}
MATERIAL_CARD_COLOR_DEFAULT = ("white", "gray17")


class CatalogsPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 8))
        header.grid_columnconfigure(0, weight=1)
        gui_theme.back_button(header, self.app).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        gui_theme.section_title(header, "Catálogos").grid(row=1, column=0, sticky="w")
        buttons_row = ctk.CTkFrame(header, fg_color="transparent")
        buttons_row.grid(row=1, column=1, sticky="e")
        gui_theme.secondary_button(
            buttons_row, text="🔄 Sincronizar com o site", command=self._sync_with_site,
        ).pack(side="left", padx=(0, 8))
        gui_theme.primary_button(
            buttons_row, text="+ Importar arquivo original (.cdr)", command=self._import_master
        ).pack(side="left")

        self.status_label = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=12), text_color="gray60", anchor="w")
        self.status_label.grid(row=1, column=0, sticky="ew", padx=28)

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.list_frame.grid(row=2, column=0, sticky="nsew", padx=24, pady=(8, 8))
        self.CARD_COLUMNS = 8
        self.list_frame.grid_columnconfigure(tuple(range(self.CARD_COLUMNS)), weight=1, uniform="cards")

        self._catalog_rows = {}  # catalog_id -> full row from db.get_all_public_catalogs(), refreshed every refresh()
        self._drag_cards = {}  # catalog_id -> card widget, rebuilt every refresh()
        self._drag_catalog_id = None  # catalog_id currently being dragged, or None
        self._drag_start_xy = None  # (x_root, y_root) at ButtonPress-1 -- tells a click from a drag
        self._drag_active = False  # only True once the mouse actually moved past the click threshold
        self._drag_highlighted_id = None  # catalog_id of the card currently shown as drop target
        self._DRAG_THRESHOLD_PX = 6  # movement below this is a click (opens the catalog), not a reorder drag

        self.log_panel = gui_worker.LogPanel(self)
        self.log_panel.grid(row=3, column=0, sticky="sew", padx=24, pady=(0, 20))

        # Data loads on first on_show(), not here -- every page is built
        # eagerly at startup (App._build_pages()), so an upfront refresh()
        # here would query the database (and, for the website page, make a
        # network call) for all 7 pages before the window even finishes
        # opening. Loading lazily is what actually made startup fast.

    def on_show(self):
        self.refresh()

    def refresh(self):
        for child in self.list_frame.winfo_children():
            child.destroy()
        self._drag_cards = {}
        self._drag_catalog_id = None
        self._drag_start_xy = None
        self._drag_active = False
        self._drag_highlighted_id = None

        rows = db.get_all_public_catalogs()
        self._catalog_rows = {row[0]: row for row in rows}
        if not rows:
            self.status_label.configure(text="Nenhum catálogo importado ainda.")
            return
        self.status_label.configure(
            text=f"{len(rows)} catálogo(s)  ·  clique num card pra abrir as funções  ·  "
                 f"arraste pra reordenar")

        for i, (catalog_id, name, _status, _created_at, _total_arts, _approved_arts,
                _arts_with_reference, _published_at) in enumerate(rows):
            # Card compacto -- só o nome. Ver/mudar qualquer outra coisa do catálogo (medidas,
            # publicar, material, categoria, renomear...) é um clique nele, que abre
            # CatalogDetailDialog com tudo isso. Cards pequenos = mais fácil de mirar e mais rápido
            # de arrastar pra reordenar. A cor de fundo (fraca) já entrega o material de relance,
            # sem precisar abrir nada -- ver MATERIAL_CARD_COLORS.
            _material = db.get_catalog_tipo_produto(catalog_id)[1]
            card_color = MATERIAL_CARD_COLORS.get(_material, MATERIAL_CARD_COLOR_DEFAULT)
            card = ctk.CTkFrame(self.list_frame, corner_radius=10, fg_color=card_color,
                                 border_width=2, border_color=("gray88", "gray25"), cursor="hand2",
                                 width=118, height=52)
            card.grid(row=i // self.CARD_COLUMNS, column=i % self.CARD_COLUMNS, sticky="new", pady=4, padx=4)
            card.grid_propagate(False)
            self._drag_cards[catalog_id] = card

            title_label = ctk.CTkLabel(
                card, text=name, font=ctk.CTkFont(size=11, weight="bold"),
                wraplength=104, justify="center", cursor="hand2",
            )
            title_label.place(relx=0.5, rely=0.5, anchor="center")

            for widget in (card, title_label):
                widget.bind("<ButtonPress-1>", lambda e, cid=catalog_id: self._on_drag_start(e, cid))
                widget.bind("<B1-Motion>", self._on_drag_motion)
                widget.bind("<ButtonRelease-1>", self._on_drag_release)

    def _open_catalog_detail(self, catalog_id):
        row = self._catalog_rows.get(catalog_id)
        if row is None:
            return
        CatalogDetailDialog(self.app, self, row)

    def _on_drag_start(self, event, catalog_id):
        self._drag_catalog_id = catalog_id
        self._drag_start_xy = (event.x_root, event.y_root)
        self._drag_active = False
        self._drag_highlighted_id = None

    def _catalog_id_at(self, x_root, y_root):
        for catalog_id, card in self._drag_cards.items():
            if not card.winfo_exists():
                continue
            left, top = card.winfo_rootx(), card.winfo_rooty()
            if left <= x_root <= left + card.winfo_width() and top <= y_root <= top + card.winfo_height():
                return catalog_id
        return None

    def _on_drag_motion(self, event):
        if self._drag_catalog_id is None:
            return
        if not self._drag_active:
            start_x, start_y = self._drag_start_xy
            if abs(event.x_root - start_x) < self._DRAG_THRESHOLD_PX and \
               abs(event.y_root - start_y) < self._DRAG_THRESHOLD_PX:
                return  # ainda dentro da tolerância de clique -- não é um arraste ainda
            self._drag_active = True
            card = self._drag_cards.get(self._drag_catalog_id)
            if card is not None:
                card.configure(border_color=gui_theme.ACCENT_BLUE)

        target_id = self._catalog_id_at(event.x_root, event.y_root)
        if target_id == self._drag_highlighted_id:
            return
        if self._drag_highlighted_id is not None and self._drag_highlighted_id != self._drag_catalog_id:
            highlighted_card = self._drag_cards.get(self._drag_highlighted_id)
            if highlighted_card is not None and highlighted_card.winfo_exists():
                highlighted_card.configure(border_color=("gray88", "gray25"))
        self._drag_highlighted_id = target_id
        if target_id is not None and target_id != self._drag_catalog_id:
            self._drag_cards[target_id].configure(border_color=gui_theme.ACCENT_MINT)

    def _on_drag_release(self, event):
        dragged_id = self._drag_catalog_id
        was_dragging = self._drag_active
        target_id = self._catalog_id_at(event.x_root, event.y_root)
        self._drag_catalog_id = None
        self._drag_start_xy = None
        self._drag_active = False
        self._drag_highlighted_id = None
        for card in self._drag_cards.values():
            if card.winfo_exists():
                card.configure(border_color=("gray88", "gray25"))

        if not was_dragging:
            # Mal se mexeu -- foi um clique, não um arraste: abre as funções desse catálogo.
            if dragged_id is not None:
                self._open_catalog_detail(dragged_id)
            return

        if dragged_id is None or target_id is None or target_id == dragged_id:
            return
        self._reorder_catalog(dragged_id, target_id)

    def _reorder_catalog(self, dragged_id, target_id):
        """Moves dragged_id to sit right where target_id currently is (the
        rest of the list shifts to make room) -- an arbitrary-distance move
        in one drag, unlike the old "one step at a time" arrow buttons.
        Only re-positions the existing card widgets (no destroy/rebuild --
        that full refresh() is what made this feel slow), then pushes the
        new order to the site in the background."""
        ids_in_order = list(self._catalog_rows)
        ids_in_order.remove(dragged_id)
        target_index = ids_in_order.index(target_id)
        ids_in_order.insert(target_index, dragged_id)

        db.reorder_catalogs(ids_in_order)
        self._catalog_rows = {cid: self._catalog_rows[cid] for cid in ids_in_order}
        for i, cid in enumerate(ids_in_order):
            self._drag_cards[cid].grid(row=i // self.CARD_COLUMNS, column=i % self.CARD_COLUMNS, pady=4, padx=4)

        def task():
            website_sync.definir_ordem_catalogos({self._catalog_rows[cid][1]: i for i, cid in enumerate(ids_in_order)})

        def on_error(ex):
            gui_theme.show_message(
                self.app, "Erro ao atualizar ordem no site",
                f"A ordem foi salva localmente, mas não foi possível enviar pro site:\n\n{ex}")

        gui_worker.run_task(self.app, task, on_error=on_error)

    def _sync_with_site(self):
        """Manual trigger for the same reconciliation gui_app.py runs
        automatically at startup -- lets the operator see the result
        immediately instead of it happening silently in the background."""
        self.log_panel.show("Comparando com o site...\n\n")

        def task():
            local_names = {row[1] for row in db.get_all_catalogs()}
            return website_sync.sync_catalogs(local_names)

        def on_success(removed):
            self.log_panel.hide_after()
            if removed:
                lines = "\n".join(f"• {name}" for name in removed)
                gui_theme.show_message(
                    self, "Sincronizado",
                    f"{len(removed)} catálogo(s) removido(s) do site (não existiam mais localmente):\n\n{lines}")
            else:
                gui_theme.show_message(self, "Sincronizado", "O site já estava igual ao seu sistema local. Nada pra remover.")

        def on_error(ex):
            gui_theme.show_message(self, "Erro ao sincronizar", str(ex))

        gui_worker.run_task(self, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)

    def _import_master(self):
        path = file_picker.pick_master_file()
        if not path:
            return
        name = gui_theme.ask_text(
            self.app, "Importar catálogo", "Nome para o catálogo (Enter para usar o nome do arquivo):")

        label = name or "(nome do arquivo)"
        material_choice = gui_theme.ask_choice(
            self.app, f'Material de "{label}"', "Esse catálogo é Têxtil - Termocolante ou Adesivo - UV?",
            list(MATERIAIS_SITE.items()))
        categoria_choice_raw = gui_theme.ask_choice(
            self.app, f'Categoria no site de "{label}"',
            "Isso define os botões de tipo/medida que aparecem pra cada figura desse catálogo no site.",
            list(CATEGORIAS_SITE.items()))
        # None (dialog cancelado) e "sem_categoria" (escolhido de propósito) dão no mesmo aqui: o
        # catálogo fica sem categoria, dá pra definir depois clicando no card.
        categoria_choice = None if categoria_choice_raw in (None, "sem_categoria") else categoria_choice_raw

        self.log_panel.show(f"Importando '{path}'...\n\n")

        def task():
            catalog_id = pa.do_import_from_master(path, name or None)
            if catalog_id is not None and material_choice is not None:
                db.set_catalog_material(catalog_id, material_choice)
            if catalog_id is not None:
                db.set_catalog_categoria_site(catalog_id, categoria_choice)
            if catalog_id is not None:
                print("\nPublicando no site...")
                try:
                    pa.do_publish_catalog(catalog_id)
                except Exception as ex:
                    print(f"AVISO: catálogo importado com sucesso, mas não consegui publicar no site agora "
                          f"({ex}). O catálogo continua salvo localmente.")

        def on_success(_result):
            self.refresh()
            self.log_panel.hide_after()

        gui_worker.run_task(self.app, task, on_log=self.log_panel.append, on_success=on_success)

    def _view_arts(self, catalog_id, name):
        CatalogArtsDialog(self.app, catalog_id, name)

    def _edit_catalog_sizes(self, catalog_id, name):
        """Medidas cadastradas aqui valem pro catálogo inteiro (todo REF dele
        oferece as mesmas opções no site) -- não precisa configurar desenho
        por desenho. Só tem efeito depois de publicar esse catálogo de novo
        (ver _publish)."""
        current = ", ".join(db.get_catalog_available_sizes(catalog_id))
        result = gui_theme.ask_text(
            self.app, f"Medidas de \"{name}\" (site)",
            "Medidas que esse catálogo vende, separadas por vírgula (ex: 29cm, 35cm). "
            "Vale pra todos os desenhos desse catálogo. Deixe em branco pra não mostrar "
            "escolha de medida. Depois de salvar, clique \"Publicar no site\" pra valer.",
            placeholder="29cm, 35cm", default=current)
        if result is None:
            return
        sizes = [s.strip() for s in result.split(",") if s.strip()]
        pa.do_set_catalog_available_sizes(catalog_id, sizes)

    def _upload_new_arts(self, catalog_id, name):
        """Adiciona só as REFs novas de um arquivo .cdr a esse catálogo --
        REF que esse catálogo já tem é ignorada, nunca sobrescrita (ver
        pa.do_add_new_arts_to_catalog). Pra quando o desenhista manda uma
        versão atualizada do arquivo com peças novas no meio das antigas."""
        path = file_picker.pick_master_file()
        if not path:
            return

        self.log_panel.show(f"Analisando '{os.path.basename(path)}' contra \"{name}\"...\n\n")

        def task():
            return pa.do_add_new_arts_to_catalog(catalog_id, path)

        def on_success(result):
            self.log_panel.hide_after()
            self.refresh()
            if result is None:
                gui_theme.show_message(self.app, "Nada adicionado", "Não consegui ler esse arquivo.")
                return
            added, skipped = result
            gui_theme.show_message(
                self.app, "Upload concluído",
                f"\"{name}\": {added} desenho(s) novo(s) adicionado(s), {skipped} já existiam e foram ignorados.\n\n"
                f"Lembre de clicar em \"Publicar no site\" pra essas novas REFs aparecerem pros clientes.")

        def on_error(ex):
            self.log_panel.hide()
            gui_theme.show_message(self.app, "Erro no upload", str(ex))

        gui_worker.run_task(self.app, task, on_log=self.log_panel.append, on_success=on_success, on_error=on_error)

    def _backfill_sizes(self, catalog_id, name):
        """Preenche o tamanho de toda REF desse catálogo que ainda não tem
        nenhum (nem legenda "MED" no arquivo original, nem correção manual)
        medindo direto do desenho vetorial -- pra um catálogo que foi
        importado sem essa legenda, sem precisar digitar medida nenhuma na
        mão (ver pa.do_backfill_sizes_from_master)."""
        self.log_panel.show(f"Remedindo peças sem tamanho de \"{name}\" direto do arquivo original...\n\n")

        def task():
            return pa.do_backfill_sizes_from_master(catalog_id)

        def on_success(result):
            self.log_panel.hide_after()
            filled, failed = result
            if filled == 0 and failed == 0:
                gui_theme.show_message(
                    self.app, "Nada pra remedir",
                    f"\"{name}\" não tem arquivo original salvo, ou já não tem nenhuma REF sem tamanho.")
                return
            message = f"{filled} REF(s) de \"{name}\" agora têm tamanho, medido direto da arte."
            if failed:
                message += f"\n\n{failed} falharam e continuam sem tamanho -- corrija na mão em \"Ver desenhos\"."
            gui_theme.show_message(self.app, "Tamanhos preenchidos", message)

        def on_error(ex):
            self.log_panel.hide()
            gui_theme.show_message(self.app, "Erro ao remedir", str(ex))

        gui_worker.run_task(self.app, task, on_log=self.log_panel.append, on_success=on_success, on_error=on_error)

    def _publish(self, catalog_id, name):
        self.log_panel.show(f"Publicando \"{name}\" no site...\n\n")

        def task():
            pa.do_publish_catalog(catalog_id)

        def on_success(_result):
            self.refresh()
            self.log_panel.hide_after()

        def on_error(ex):
            self.log_panel.hide()
            gui_theme.show_message(self.app, "Erro ao publicar", str(ex))

        gui_worker.run_task(self.app, task, on_log=self.log_panel.append, on_success=on_success, on_error=on_error)

    def _rename(self, catalog_id, old_name, published_at):
        new_name = gui_theme.ask_text(
            self.app, "Renomear catálogo",
            f'Nome atual: "{old_name}"\n\nNovo nome:',
            placeholder="ex: Catálogo Baby 2025",
            default=old_name,
        )
        if not new_name or new_name == old_name:
            return
        new_name = new_name.strip()
        if not new_name:
            return
        if db.catalog_name_exists(new_name):
            gui_theme.show_message(
                self.app, "Nome já existe",
                f'Já existe um catálogo com o nome "{new_name}". Escolha um nome diferente.')
            return

        db.rename_catalog(catalog_id, new_name)
        self.refresh()

        # O site guarda as figuras e a POSIÇÃO de cada catálogo pelo nome -- renomear tem que chegar lá também.
        self.log_panel.show(f'Renomeado aqui. Atualizando o site: "{old_name}" -> "{new_name}"...\n\n')

        def task():
            return pa.do_rename_catalog_on_site(catalog_id, old_name, new_name)

        def on_success(outcome):
            self.log_panel.hide_after()
            if outcome == "nao_publicado":
                gui_theme.show_message(
                    self.app, "Renomeado",
                    f'"{old_name}" renomeado para "{new_name}".\n\n'
                    f'Esse catálogo ainda não foi publicado, então o site não precisou mudar.')
            else:
                gui_theme.show_message(
                    self.app, "Renomeado e atualizado",
                    f'"{old_name}" -> "{new_name}"\n\nSite atualizado (nome e posição do catálogo).')

        def on_error(ex):
            self.log_panel.hide()
            gui_theme.show_message(
                self.app, "Erro ao atualizar o site",
                f'O nome foi atualizado aqui para "{new_name}", mas falhou ao atualizar o site:\n\n{ex}\n\n'
                f'Tente renomear de novo ou clique em "Publicar no site" no card do catálogo.')

        gui_worker.run_task(self.app, task, on_log=self.log_panel.append,
                            on_success=on_success, on_error=on_error)

    def _set_material(self, catalog_id, name):
        current_material = db.get_catalog_tipo_produto(catalog_id)[1]
        default_label = next(
            (label for label, value in MATERIAIS_SITE.items() if value == current_material),
            next(iter(MATERIAIS_SITE)))
        material_label_choice = gui_theme.ask_choice(
            self.app, f'Material de "{name}"', "Esse catálogo é Têxtil - Termocolante ou Adesivo - UV?",
            list(MATERIAIS_SITE.items()), default_index=list(MATERIAIS_SITE).index(default_label))
        if material_label_choice is None:
            return
        db.set_catalog_material(catalog_id, material_label_choice)
        self.refresh()

    def _set_categoria(self, catalog_id, name):
        current_categoria = db.get_catalog_categoria_site(catalog_id)
        default_label = next(
            (label for label, value in CATEGORIAS_SITE.items() if value == current_categoria),
            "Sem categoria (Adicionar antigo)")
        # "sem_categoria" (não None) como valor -- ask_choice usa None pra dizer "cancelado", e
        # "Sem categoria" é uma escolha real aqui, então precisa de um valor que não seja None ou
        # cancelar a tela seria indistinguível de escolher "Sem categoria" de propósito (e apagaria
        # a classificação existente sem querer).
        new_categoria_raw = gui_theme.ask_choice(
            self.app, f'Categoria no site de "{name}"',
            "Isso define os botões de tipo/medida que aparecem pra cada figura desse catálogo no site.",
            list(CATEGORIAS_SITE.items()), default_index=list(CATEGORIAS_SITE).index(default_label))
        if new_categoria_raw is None:
            return
        new_categoria = None if new_categoria_raw == "sem_categoria" else new_categoria_raw
        db.set_catalog_categoria_site(catalog_id, new_categoria)
        self.refresh()

        if new_categoria != current_categoria:
            # Já publicado? Troca só a categoria lá (sem reenviar imagem nenhuma).
            try:
                website_sync.definir_categoria(name, new_categoria)
            except Exception as ex:
                gui_theme.show_message(
                    self.app, "Categoria salva aqui",
                    f"Salvei a categoria, mas não consegui avisar o site agora:\n\n{ex}\n\n"
                    f'Clique em "Publicar no site" no card do catálogo pra atualizar.')


    def _delete(self, catalog_id, name):
        if not gui_theme.ask_confirm(
            self.app, "Excluir catálogo",
            f"Tem certeza que quer excluir o catálogo \"{name}\" (id={catalog_id})? "
            f"Essa ação não pode ser desfeita.",
            confirm_text="Excluir", danger=True,
        ):
            return
        pa.do_delete(catalog_id)
        self.refresh()
        gui_theme.show_message(self.app, "Excluído", f"\"{name}\" excluído com sucesso.")


class CatalogDetailDialog(ctk.CTkToplevel):
    """Everything that used to sit directly on a catalog's card in the grid (status, counts,
    category, and every action button) now lives here instead -- opened by clicking a card. Keeps
    the grid itself down to just the catalog name, which is what made cards small/light enough to
    drag around quickly (see CatalogsPage.refresh()). Every action just calls the same
    CatalogsPage method the old card button called (page.<action>), then closes this popup -- the
    action's own success/error message and the page's refresh() happen exactly as before."""

    def __init__(self, master, page: "CatalogsPage", row: tuple):
        super().__init__(master)
        (catalog_id, name, status, created_at, total_arts, approved_arts,
         arts_with_reference, published_at) = row
        self.page = page
        self.catalog_id = catalog_id
        self.name = name
        self.published_at = published_at

        self.title(name)
        gui_theme.center_over_master(self, master, 380, 420)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(18, 6))
        _tipo_produto, material = db.get_catalog_tipo_produto(catalog_id)
        categoria_site = db.get_catalog_categoria_site(catalog_id)
        if material == "Textil":
            icon_text, icon_color = "TX", gui_theme.ACCENT_MINT
        elif material == "UV":
            icon_text, icon_color = "UV", "#c0392b"
        elif material == "TextilUV":
            icon_text, icon_color = "TX+UV", gui_theme.ACCENT_BLUE
        else:
            icon_text, icon_color = "?", "gray50"
        ctk.CTkLabel(
            header, text=icon_text, font=ctk.CTkFont(size=11, weight="bold"), fg_color=icon_color,
            text_color="white", corner_radius=7, width=44 if icon_text == "TX+UV" else 28, height=24,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(
            header, text=name, font=ctk.CTkFont(size=15, weight="bold"),
            wraplength=280, justify="left", anchor="w",
        ).pack(side="left", fill="x")

        ctk.CTkLabel(
            self, text=f"id={catalog_id}  ·  {created_at[:16].replace('T', ' ')}",
            font=ctk.CTkFont(size=10), text_color="gray55", anchor="w",
        ).pack(anchor="w", padx=20, pady=(0, 8))

        pills = ctk.CTkFrame(self, fg_color="transparent")
        pills.pack(anchor="w", padx=20, pady=(0, 4), fill="x")
        gui_theme.status_pill(pills, status).grid(row=0, column=0, sticky="w", padx=(0, 4), pady=2)
        gui_theme.pill(pills, f"🖼️ {total_arts or 0}", "#e5f1fb", gui_theme.ACCENT_BLUE_HOVER).grid(
            row=0, column=1, sticky="w", pady=2)
        gui_theme.pill(pills, f"✅ {approved_arts or 0}", "#e3faf1", "#1e8a4c").grid(
            row=0, column=2, sticky="w", padx=(4, 0), pady=2)
        gui_theme.pill(pills, f"🏷️ {arts_with_reference or 0} REF", "#f3ecfb", gui_theme.ACCENT_PURPLE_HOVER).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=2)
        if categoria_site:
            gui_theme.pill(pills, {"aplique": "Aplique", "faixa": "Faixa"}[categoria_site], "#e3faf1", "#1e8a4c").grid(
                row=2, column=0, columnspan=3, sticky="w", pady=2)
        else:
            gui_theme.pill(pills, "sem categoria no site", "#fdecea", "#c0392b").grid(
                row=2, column=0, columnspan=3, sticky="w", pady=2)

        if published_at:
            ctk.CTkLabel(
                self, text=f"✓ Publicado em {published_at[:16].replace('T', ' ')}",
                font=ctk.CTkFont(size=10, weight="bold"), text_color=gui_theme.ACCENT_BLUE, anchor="w",
            ).pack(anchor="w", padx=20, pady=(4, 0))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=(14, 4))
        ctk.CTkButton(
            actions, text="Ver desenhos", width=110, height=28, font=ctk.CTkFont(size=11),
            fg_color="gray40", hover_color="gray30", command=self._view_arts,
        ).pack(side="left", padx=(0, 6))
        gui_theme.danger_button(
            actions, text="Excluir", width=90, height=28, font=ctk.CTkFont(size=11), command=self._delete,
        ).pack(side="left")

        actions2 = ctk.CTkFrame(self, fg_color="transparent")
        actions2.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkButton(
            actions2, text="Medidas (site)", width=110, height=28, font=ctk.CTkFont(size=11),
            fg_color="gray40", hover_color="gray30", command=self._edit_catalog_sizes,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions2, text="Publicar no site", width=130, height=28, font=ctk.CTkFont(size=11),
            fg_color=gui_theme.ACCENT_BLUE, hover_color=gui_theme.ACCENT_BLUE_HOVER, command=self._publish,
        ).pack(side="left")

        actions3 = ctk.CTkFrame(self, fg_color="transparent")
        actions3.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkButton(
            actions3, text="Material", width=90, height=28, font=ctk.CTkFont(size=11),
            fg_color="gray40", hover_color="gray30", command=self._set_material,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions3, text="Categoria no site", width=130, height=28, font=ctk.CTkFont(size=11),
            fg_color="gray40", hover_color="gray30", command=self._set_categoria,
        ).pack(side="left")

        actions3b = ctk.CTkFrame(self, fg_color="transparent")
        actions3b.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkButton(
            actions3b, text="✏️ Renomear", width=110, height=28, font=ctk.CTkFont(size=11),
            fg_color="gray40", hover_color="gray30", command=self._rename,
        ).pack(side="left")

        actions4 = ctk.CTkFrame(self, fg_color="transparent")
        actions4.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkButton(
            actions4, text="⬆️ Upload", width=110, height=28, font=ctk.CTkFont(size=11),
            fg_color=gui_theme.ACCENT_MINT, hover_color=gui_theme.ACCENT_MINT_HOVER, command=self._upload_new_arts,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions4, text="📏 Remedir", width=110, height=28, font=ctk.CTkFont(size=11),
            fg_color="gray40", hover_color="gray30", command=self._backfill_sizes,
        ).pack(side="left")

        ctk.CTkButton(
            self, text="Fechar", width=100, height=30, fg_color="gray40", hover_color="gray30",
            command=self.destroy,
        ).pack(pady=(16, 16))

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _e: self.destroy())

    # Cada ação chama o mesmo método que o card antigo chamava, depois fecha esse popup -- a
    # mensagem de sucesso/erro e o refresh() da grade continuam exatamente como antes.
    def _view_arts(self):
        self.destroy()
        self.page._view_arts(self.catalog_id, self.name)

    def _delete(self):
        self.destroy()
        self.page._delete(self.catalog_id, self.name)

    def _edit_catalog_sizes(self):
        self.destroy()
        self.page._edit_catalog_sizes(self.catalog_id, self.name)

    def _publish(self):
        self.destroy()
        self.page._publish(self.catalog_id, self.name)

    def _set_material(self):
        self.destroy()
        self.page._set_material(self.catalog_id, self.name)

    def _set_categoria(self):
        self.destroy()
        self.page._set_categoria(self.catalog_id, self.name)

    def _rename(self):
        self.destroy()
        self.page._rename(self.catalog_id, self.name, self.published_at)

    def _upload_new_arts(self):
        self.destroy()
        self.page._upload_new_arts(self.catalog_id, self.name)

    def _backfill_sizes(self):
        self.destroy()
        self.page._backfill_sizes(self.catalog_id, self.name)


class CatalogArtsDialog(ctk.CTkToplevel):
    """Browses every art in a catalog as a grid of thumbnails; clicking one's
    "Editar tamanho" corrects its production size (see pa.do_set_art_size_override)
    -- for fixing a wrong/missing size on one specific piece without touching
    the rest of the catalog."""
    COLUMNS = 4

    def __init__(self, master, catalog_id, catalog_name):
        super().__init__(master)
        self.title(f"Desenhos de \"{catalog_name}\"")
        self.geometry("900x650")
        self.minsize(600, 400)
        self.transient(master)
        self.grab_set()
        self.app = master
        self.catalog_id = catalog_id
        self.catalog_name = catalog_name
        self._images = []  # keep CTkImage references alive
        self._size_labels = {}  # art_id -> label widget, updated in place after an edit

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(
            header, text=f"Desenhos de \"{catalog_name}\"", font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            header, text="Fechar", width=90, height=30, fg_color="gray40", hover_color="gray30",
            command=self.destroy,
        ).pack(side="right")

        self.grid_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.grid_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        for col in range(self.COLUMNS):
            self.grid_frame.grid_columnconfigure(col, weight=1, uniform="art_cards")

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _e: self.destroy())

        self._load_arts()

    def _load_arts(self):
        arts = db.get_arts_with_sizes_by_catalog_id(self.catalog_id)
        for i, (art_id, reference, _page_number, preview_path,
                _review_status, override_width_mm, override_height_mm) in enumerate(arts):
            card = self._build_art_card(art_id, reference, preview_path, override_width_mm, override_height_mm)
            card.grid(row=i // self.COLUMNS, column=i % self.COLUMNS, sticky="new", padx=6, pady=6)

    def _build_art_card(self, art_id, reference, preview_path, override_width_mm, override_height_mm):
        # override_width_mm/height_mm here is only a MANUAL correction (see
        # db.get_arts_with_sizes_by_catalog_id) -- it used to be treated as
        # "the" size, so any REF whose real size instead came from the
        # master file's own "REF N MED WxHMM" caption (get_locked_size_for_art,
        # the exact same size that's already published to the site and
        # already used by the "Criar Catálogo" tool) showed "sem tamanho
        # definido" here even though a perfectly good size was already in
        # use everywhere else -- confusing when the site clearly had it
        # right. _refresh_size_label falls back to it below so this screen
        # never disagrees with what's actually live.
        card = ctk.CTkFrame(self.grid_frame, corner_radius=10, fg_color=("gray92", "gray17"))

        if preview_path:
            try:
                image = Image.open(preview_path)
                image.thumbnail((90, 90))
                ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
                self._images.append(ctk_image)
                ctk.CTkLabel(card, image=ctk_image, text="").pack(padx=10, pady=(10, 4))
            except Exception:
                ctk.CTkLabel(card, text="(sem imagem)", text_color="gray50").pack(padx=10, pady=(10, 4))

        ctk.CTkLabel(
            card, text=reference or "(sem REF)", font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(padx=10)

        size_label = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=11), text_color="gray50")
        size_label.pack(padx=10, pady=(0, 6))
        self._size_labels[art_id] = size_label
        self._refresh_size_label(art_id, override_width_mm, override_height_mm)

        ctk.CTkButton(
            card, text="Editar tamanho", width=120, height=26, fg_color="gray40", hover_color="gray30",
            command=lambda: self._edit_size(art_id, reference),
        ).pack(padx=10, pady=(0, 4))
        gui_theme.danger_button(
            card, text="Excluir", width=120, height=26,
            command=lambda: self._delete_art(art_id, reference, card),
        ).pack(padx=10, pady=(0, 10))

        return card

    def _refresh_size_label(self, art_id, override_width_mm, override_height_mm):
        label = self._size_labels.get(art_id)
        if label is None:
            return
        if override_width_mm is not None and override_height_mm is not None:
            label.configure(text=f"{override_height_mm}mm x {override_width_mm}mm (altura x largura)")
            return
        locked_size = pa.get_locked_size_for_art(art_id)
        if locked_size is not None:
            width_mm, height_mm = locked_size
            label.configure(text=f"{height_mm:g}mm x {width_mm:g}mm (altura x largura)")
        else:
            label.configure(text="sem tamanho definido")

    def _edit_size(self, art_id, reference):
        # catalog_name faz o SizeDialog mostrar "Aplicar a todo o catálogo"
        # -- pra um catálogo inteiro importado sem a legenda "MED WxHMM" no
        # arquivo original (nenhuma peça tem tamanho), corrigir peça por
        # peça em "Editar tamanho" seria repetir a mesma medida dezenas de
        # vezes. Antes esse retorno vinha, mas nada aqui olhava pra ele
        # (_apply_to_catalog descartado) -- o checkbox aparecia na tela e
        # não fazia nada.
        label = reference or f"id={art_id}"
        current = db.get_art_size_override(art_id) or pa.get_locked_size_for_art(art_id)
        result = gui_theme.ask_size(
            self, f"Tamanho de \"{label}\"", catalog_name=self.catalog_name, initial_size=current)
        if result is None:
            return
        width_mm, height_mm, apply_to_catalog = result
        if apply_to_catalog:
            pa.do_set_catalog_default_size(self.catalog_id, width_mm, height_mm)
            for other_art_id in list(self._size_labels):
                override = db.get_art_size_override(other_art_id)
                if override is None:
                    self._refresh_size_label(other_art_id, None, None)
        else:
            pa.do_set_art_size_override(art_id, width_mm, height_mm)
            self._refresh_size_label(art_id, width_mm, height_mm)

    def _delete_art(self, art_id, reference, card):
        label = reference or f"id={art_id}"
        if not gui_theme.ask_confirm(
            self, "Excluir desenho",
            f"Isso remove \"{label}\" do catálogo e do site (se estiver publicado). "
            f"Essa ação não pode ser desfeita. Continuar?",
            confirm_text="Excluir", danger=True,
        ):
            return

        def task():
            pa.do_delete_art(art_id)

        def on_success(_result):
            card.destroy()
            self._size_labels.pop(art_id, None)

        def on_error(ex):
            gui_theme.show_message(self, "Erro", f"Não consegui excluir: {ex}")

        gui_worker.run_task(self.app, task, on_success=on_success, on_error=on_error)
