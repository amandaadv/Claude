"""Buscar Produto page: one place to find a product either by typing its REF
number or by uploading a customer photo, then add it straight to the queue.
Replaces the old separate "Identificar Foto" page and the queue page's
"+ Adicionar por REF" button -- both did the same job (find something to
queue) through two different doors.
"""
import customtkinter as ctk
from PIL import Image

import db
import file_picker
import gui_theme
import gui_worker
import pa


class SearchPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Buscar Produto").pack(anchor="w")

        search_row = ctk.CTkFrame(self, fg_color="transparent")
        search_row.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 8))
        search_row.grid_columnconfigure(0, weight=1)

        self.reference_entry = ctk.CTkEntry(
            search_row, placeholder_text="Digite o número de REF e aperte Enter...", height=36)
        self.reference_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.reference_entry.bind("<Return>", lambda _e: self._search_by_reference())

        gui_theme.card_button(
            search_row, "🔎", "Buscar por REF", self._search_by_reference,
            color=gui_theme.ACCENT_BLUE, hover_color=gui_theme.ACCENT_BLUE_HOVER,
            text_color="#1a1a1f", width=130, height=64,
        ).grid(row=0, column=1, padx=4)
        gui_theme.card_button(
            search_row, "📷", "Buscar por foto\ndo cliente", self._pick_photos, width=150, height=64,
        ).grid(row=0, column=2, padx=(4, 0))

        self.status_label = ctk.CTkLabel(
            self, text="Digite o número de REF, ou selecione foto(s) do cliente pra identificar o produto.",
            font=ctk.CTkFont(size=12), text_color="gray60", anchor="w")
        self.status_label.grid(row=2, column=0, sticky="ew", padx=28)

        self.results_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.results_frame.grid(row=3, column=0, sticky="nsew", padx=24, pady=(8, 8))
        self.results_frame.grid_columnconfigure(0, weight=1)

        self.log_panel = gui_worker.LogPanel(self)
        self.log_panel.grid(row=4, column=0, sticky="sew", padx=24, pady=(0, 20))

        self._images = []  # keep CTkImage references alive
        # Lembrados de um "+ Adicionar à fila" pro próximo -- adicionar várias peças do mesmo
        # tamanho/quantidade (comum: o mesmo pedido inteiro digitado por REF) não obrigava mais a
        # redigitar tudo de novo a cada uma.
        self._last_manual_size: tuple[float, float] | None = None
        self._last_quantity_text = "10"

    def on_show(self):
        pass

    def _clear_results(self):
        for child in self.results_frame.winfo_children():
            child.destroy()
        self._images.clear()

    def _search_by_reference(self):
        reference = self.reference_entry.get().strip()
        if not reference:
            return
        self._clear_results()
        matches = db.find_approved_arts_by_reference(reference)
        if not matches:
            self.status_label.configure(text=f"Nenhuma arte aprovada encontrada com REF \"{reference}\".")
            return

        self.status_label.configure(text=f"{len(matches)} resultado(s) para REF \"{reference}\".")
        for row_index, (art_id, catalog_name, found_reference, preview_path) in enumerate(matches):
            card = self._build_candidate_card(
                art_id, catalog_name, found_reference, preview_path, score=1.0, is_exact=True)
            card.grid(row=row_index, column=0, sticky="ew", pady=6)

    def _pick_photos(self):
        photo_paths = file_picker.pick_image_files()
        if not photo_paths:
            return
        self._clear_results()
        self.status_label.configure(text=f"Analisando {len(photo_paths)} foto(s)...")
        self.log_panel.show("Analisando foto(s)...\n\n")

        def task():
            return pa.do_identify(photo_paths)

        def on_success(results):
            self._show_photo_results(results)
            self.log_panel.hide_after()

        gui_worker.run_task(self.app, task, on_log=self.log_panel.append, on_success=on_success)

    def _show_photo_results(self, results):
        self.status_label.configure(text=f"{len(results)} foto(s) analisada(s).")
        row_index = 0
        for result in results:
            if result["error"]:
                card = ctk.CTkFrame(self.results_frame, corner_radius=10, fg_color=("gray92", "gray17"))
                card.grid(row=row_index, column=0, sticky="ew", pady=6)
                ctk.CTkLabel(card, text=f"{result['photo_path']}: {result['error']}",
                             text_color=gui_theme.DANGER).pack(padx=16, pady=12, anchor="w")
                row_index += 1
                continue

            candidates = []
            if result["exact_match"]:
                art_id, catalog_name, reference, preview_path = result["exact_match"]
                candidates = [(1.0, art_id, catalog_name, reference, preview_path, True)]
            elif result["candidates"]:
                candidates = [
                    (score, art_id, catalog_name, reference, preview_path, False)
                    for score, art_id, catalog_name, reference, preview_path in result["candidates"][:3]
                ]

            if not candidates:
                card = ctk.CTkFrame(self.results_frame, corner_radius=10, fg_color=("gray92", "gray17"))
                card.grid(row=row_index, column=0, sticky="ew", pady=6)
                ctk.CTkLabel(card, text=f"{result['photo_path']}: nenhum candidato encontrado.",
                             text_color="gray50").pack(padx=16, pady=12, anchor="w")
                row_index += 1
                continue

            for score, art_id, catalog_name, reference, preview_path, is_exact in candidates:
                card = self._build_candidate_card(art_id, catalog_name, reference, preview_path, score, is_exact)
                card.grid(row=row_index, column=0, sticky="ew", pady=6)
                row_index += 1

    def _build_candidate_card(self, art_id, catalog_name, reference, preview_path, score, is_exact):
        card = ctk.CTkFrame(self.results_frame, corner_radius=10, fg_color=("gray92", "gray17"))
        card.grid_columnconfigure(1, weight=1)

        try:
            image = Image.open(preview_path)
            image.thumbnail((84, 84))
            ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
            self._images.append(ctk_image)
            ctk.CTkLabel(card, image=ctk_image, text="").grid(row=0, column=0, rowspan=2, padx=16, pady=12)
        except Exception:
            pass

        title = reference or "(sem REF)"
        badge = "MATCH DIRETO (REF)" if is_exact else f"{score:.0%} de semelhança visual"
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=1, sticky="w", padx=(0, 16), pady=(12, 0))
        ctk.CTkLabel(card, text=f"{catalog_name}  ·  {badge}", font=ctk.CTkFont(size=12),
                     text_color="gray50").grid(row=1, column=1, sticky="w", padx=(0, 16), pady=(0, 12))

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=0, column=2, rowspan=2, padx=16, pady=12)
        gui_theme.primary_button(
            actions, text="+ Adicionar à fila", width=150, height=30,
            command=lambda: self._add_to_queue(art_id, reference),
        ).pack(pady=(0, 6))
        ctk.CTkButton(
            actions, text="Alterar tamanho", width=150, height=30, fg_color="gray40", hover_color="gray30",
            command=lambda: self._edit_size(art_id, reference, catalog_name),
        ).pack(pady=(0, 6))
        gui_theme.danger_button(
            actions, text="Excluir do site", width=150, height=30,
            command=lambda: self._delete_from_site(art_id, reference),
        ).pack()

        return card

    def _edit_size(self, art_id, reference, catalog_name=None):
        label = reference or f"id={art_id}"
        current = db.get_art_size_override(art_id) or pa.get_locked_size_for_art(art_id)
        result = gui_theme.ask_size(
            self.app, f"Tamanho de \"{label}\"", catalog_name=catalog_name, initial_size=current)
        if result is None:
            return
        width_mm, height_mm, apply_to_catalog = result
        if apply_to_catalog:
            catalog_id = pa.get_catalog_id_for_art(art_id)
            pa.do_set_catalog_default_size(catalog_id, width_mm, height_mm)
            gui_theme.show_message(
                self.app, "Tamanho atualizado",
                f"\"{catalog_name}\": toda peça sem tamanho próprio agora usa "
                f"{height_mm}mm x {width_mm}mm (altura x largura).")
        else:
            pa.do_set_art_size_override(art_id, width_mm, height_mm)
            gui_theme.show_message(
                self.app, "Tamanho atualizado",
                f"\"{label}\" atualizado para {height_mm}mm x {width_mm}mm (altura x largura) -- "
                f"vale pra qualquer lugar que usa essa peça daqui pra frente.")

    def _delete_from_site(self, art_id, reference):
        label = reference or f"id={art_id}"
        if not gui_theme.ask_confirm(
            self.app, "Excluir do site",
            f"Isso remove só \"{label}\" da vitrine do site -- o resto do catálogo continua "
            f"publicado normalmente. Continuar?",
            confirm_text="Excluir", danger=True,
        ):
            return

        def task():
            pa.do_excluir_produto_do_site(art_id)

        def on_success(_result):
            gui_theme.show_message(self.app, "Excluído", f"\"{label}\" removido do site.")

        def on_error(ex):
            gui_theme.show_message(self.app, "Erro", f"Não consegui remover do site: {ex}")

        gui_worker.run_task(self.app, task, on_success=on_success, on_error=on_error)

    def _add_to_queue(self, art_id, reference):
        label = reference or f"id={art_id}"
        width_mm = height_mm = None
        if pa.get_locked_size_for_art(art_id) is None:
            result = gui_theme.ask_size(
                self.app, f"Tamanho para {label}",
                "Essa arte não tem tamanho travado pelo arquivo original -- informe o tamanho de UMA peça.",
                initial_size=self._last_manual_size)
            if result is None:
                return
            width_mm, height_mm, _apply_to_catalog = result
            self._last_manual_size = (width_mm, height_mm)  # sugestão pronta na próxima peça

        quantity_text = gui_theme.ask_text(
            self.app, f"Quantidade de \"{label}\"", "Quantas peças dessa?",
            default=self._last_quantity_text)
        if quantity_text is None:
            return
        try:
            quantity = int(quantity_text.strip().replace(",", "."))
            if quantity <= 0:
                raise ValueError
        except ValueError:
            gui_theme.show_message(self.app, "Quantidade inválida", "Informe um número inteiro maior que 0.")
            return
        self._last_quantity_text = str(quantity)  # sugestão pronta na próxima peça

        pa.do_add_to_queue(art_id, width_mm, height_mm, quantity=quantity)
        gui_theme.show_message(
            self.app, "Adicionado", f"\"{label}\" ({quantity} peça(s)) adicionado à fila de produção.")
