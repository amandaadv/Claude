"""Melhorador de Imagens (IA): sends every figure of a chosen catalog through
OpenAI's image-edit API (gpt-image-1) to sharpen it and strip its background
to a transparent PNG -- the same result the shop used to get by hand through
ChatGPT Plus, one figure at a time, now done for a whole catalog at once.

ChatGPT Plus itself has no API access, so this bills a separate, pay-per-image
OpenAI API key (see paths.read_openai_api_key()) -- real cost per figure, not
covered by the flat monthly subscription. Each figure's untouched original
(and its preview) is copied under storage/backups/ before being overwritten,
since this replaces the catalog's own images in place.
"""
import datetime
import os
import threading

import customtkinter as ctk

import db
import gui_theme
import gui_worker
import image_enhancer
import image_storage
import paths


class ImageEnhancerPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app

        self._catalogs: list[tuple] = []
        self._catalog_id: int | None = None
        self._rows: list[dict] = []
        self._enhanced_ids: set[int] = set()
        self._stop_event = threading.Event()
        self._running = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Melhorador de Imagens (IA)").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Manda cada figura marcada abaixo pra IA -- melhora a nitidez e remove o fundo, "
                 "entregando em PNG transparente, igual sair editando uma por uma no ChatGPT. Usa uma "
                 "chave paga da API da OpenAI (cobra por imagem processada, separado da assinatura "
                 "ChatGPT Plus). O original de cada figura fica guardado numa pasta de backup antes de "
                 "ser substituído, caso o resultado não fique bom.",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=820, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        pick_row = ctk.CTkFrame(self, fg_color="transparent")
        pick_row.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 8))
        ctk.CTkLabel(pick_row, text="Catálogo:", font=ctk.CTkFont(size=13)).pack(side="left")
        self.catalog_var = ctk.StringVar(value="")
        self.catalog_combo = ctk.CTkComboBox(
            pick_row, values=[], variable=self.catalog_var, width=360,
            command=self._on_catalog_selected, state="readonly")
        self.catalog_combo.pack(side="left", padx=(8, 0))
        gui_theme.secondary_button(
            pick_row, text="Marcar todas", width=120, height=30, command=lambda: self._set_all(True),
        ).pack(side="left", padx=(16, 4))
        gui_theme.secondary_button(
            pick_row, text="Desmarcar todas", width=130, height=30, command=lambda: self._set_all(False),
        ).pack(side="left")

        self.table_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.table_frame.grid(row=2, column=0, sticky="nsew", padx=28, pady=(0, 8))
        self.table_frame.grid_columnconfigure(0, weight=1)
        self._empty_label = ctk.CTkLabel(
            self.table_frame, text="Escolha um catálogo acima pra ver as figuras dele.",
            font=ctk.CTkFont(size=12), text_color="gray60")
        self._empty_label.pack(anchor="w", pady=20)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 8))
        self.start_button = gui_theme.primary_button(
            footer, text="Melhorar em lote", width=220, height=36, command=self._start_batch,
        )
        self.start_button.pack(side="left")
        self.stop_button = gui_theme.danger_button(
            footer, text="Parar", width=100, height=36, command=self._stop_batch,
        )
        gui_theme.secondary_button(
            footer, text="Testar numa figura antes →", width=210, height=36,
            command=lambda: app.show_page("image_test"),
        ).pack(side="left", padx=(16, 0))
        self.status_label = ctk.CTkLabel(footer, text="", font=ctk.CTkFont(size=12), text_color="gray60")
        self.status_label.pack(side="left", padx=(16, 0))

        self.log_panel = gui_worker.LogPanel(self)
        self.log_panel.grid(row=4, column=0, sticky="sew", padx=28, pady=(0, 20))

        self._load_catalogs()

    def on_show(self):
        self._load_catalogs()

    # -- catálogo ------------------------------------------------------

    def _load_catalogs(self):
        self._catalogs = db.get_all_catalogs()
        values = [f"{name}  ({total_arts} figura(s))" for _id, name, _s, _c, total_arts, _a, _r, _p in self._catalogs]
        self.catalog_combo.configure(values=values)
        if values and self.catalog_var.get() not in values:
            self.catalog_var.set(values[0])
            self._on_catalog_selected(values[0])
        elif not values:
            self.catalog_var.set("")
            self._catalog_id = None
            self._rows = []
            self._build_rows_ui()

    def _on_catalog_selected(self, _choice):
        index = self.catalog_combo.cget("values").index(self.catalog_var.get())
        catalog_id = self._catalogs[index][0]
        self._catalog_id = catalog_id
        self._enhanced_ids = db.get_enhanced_art_ids(catalog_id)

        arts = db.get_arts_with_paths_by_catalog_id(catalog_id)
        self._rows = [
            {
                "art_id": art_id,
                "reference": reference or f"#{art_id}",
                "original_image_path": original_image_path,
                "preview_path": preview_path,
                "review_status": review_status,
                # Already-enhanced figures start unchecked -- this is what makes a
                # batch resumable across "Parar", or even closing and reopening
                # the whole app: reselecting the same catalog here skips whatever
                # already succeeded, so only the ones still pending get processed.
                "include_var": ctk.BooleanVar(value=art_id not in self._enhanced_ids),
                "already_enhanced": art_id in self._enhanced_ids,
            }
            for art_id, reference, _page_number, original_image_path, preview_path, review_status in arts
            if original_image_path
        ]
        self._build_rows_ui()

    def _set_all(self, checked: bool):
        for row in self._rows:
            row["include_var"].set(checked)

    # -- tabela --------------------------------------------------------

    def _build_rows_ui(self):
        for child in self.table_frame.winfo_children():
            child.destroy()

        if not self._rows:
            ctk.CTkLabel(
                self.table_frame, text="Esse catálogo não tem figuras com imagem pra melhorar.",
                font=ctk.CTkFont(size=12), text_color="gray60").pack(anchor="w", pady=20)
            return

        for row in self._rows:
            item = ctk.CTkFrame(self.table_frame, fg_color=("gray95", "gray14"), corner_radius=8)
            item.pack(fill="x", pady=2)
            ctk.CTkCheckBox(
                item, variable=row["include_var"], text=row["reference"],
                font=ctk.CTkFont(size=13, weight="bold"),
            ).pack(side="left", padx=12, pady=8)
            status_text = "✓ já melhorada" if row["already_enhanced"] else row["review_status"]
            status_color = gui_theme.ACCENT_MINT if row["already_enhanced"] else "gray60"
            ctk.CTkLabel(
                item, text=status_text, font=ctk.CTkFont(size=11), text_color=status_color,
            ).pack(side="right", padx=12)

    # -- rodar em lote ---------------------------------------------------

    def _start_batch(self):
        if not self._rows:
            gui_theme.show_message(self, "Nada pra melhorar", "Escolha um catálogo com figuras primeiro.")
            return

        selected = [row for row in self._rows if row["include_var"].get()]
        if not selected:
            gui_theme.show_message(self, "Nada marcado", "Marque pelo menos uma figura.")
            return

        if not gui_theme.ask_confirm(
            self, "Confirmar melhoria em lote",
            f"Isso vai chamar a API paga da OpenAI {len(selected)} vez(es) (uma por figura marcada) e "
            f"SUBSTITUIR a imagem original de cada uma no catálogo -- o original de cada uma fica "
            f"guardado num backup antes disso. Quer continuar?",
            confirm_text="Melhorar", danger=False,
        ):
            return

        backup_tag = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        catalog_id = self._catalog_id

        self._stop_event.clear()
        self._running = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.stop_button.pack(side="left", padx=(8, 0))
        self.status_label.configure(text=f"Processando 0/{len(selected)}...")
        self.log_panel.show(f"Melhorando {len(selected)} figura(s)...\n\n")

        def task():
            ok_count = 0
            fail_count = 0
            stopped_early = False
            for i, row in enumerate(selected, start=1):
                if self._stop_event.is_set():
                    stopped_early = True
                    print("Parado pelo usuário.")
                    break
                reference = row["reference"]
                try:
                    with open(row["original_image_path"], "rb") as f:
                        original_bytes = f.read()
                    new_bytes = image_enhancer.enhance_and_remove_background(original_bytes)
                    image_storage.backup_and_replace_art_image(
                        catalog_id, row["original_image_path"], row["preview_path"], new_bytes, backup_tag)
                    db.mark_art_enhanced(row["art_id"], backup_tag)
                    ok_count += 1
                    print(f"{reference}: OK ({i}/{len(selected)})")
                except Exception as ex:
                    fail_count += 1
                    print(f"{reference}: FALHOU -- {ex}")
            return ok_count, fail_count, backup_tag, stopped_early

        def on_success(result):
            ok_count, fail_count, tag, stopped_early = result
            self._running = False
            self.start_button.configure(state="normal")
            self.stop_button.pack_forget()
            self._on_catalog_selected(self.catalog_var.get())  # refresh done/pending markers
            status = "Parado" if stopped_early else "Concluído"
            self.status_label.configure(text=f"{status}: {ok_count} melhorada(s), {fail_count} falha(s).")
            self.log_panel.hide_after()
            extra = "\n\nVocê parou antes de terminar -- clique em \"Melhorar em lote\" de novo (mesmo " \
                    "fechando e abrindo o programa) que ele continua de onde parou." if stopped_early else ""

            originals_folder = os.path.join(paths.STORAGE_FOLDER, "catalogs", str(catalog_id), "originals")
            backup_folder = os.path.join(paths.BACKUPS_FOLDER, "catalogs", str(catalog_id), tag)
            # Abre as pastas direto no Explorer -- digitar/colar um caminho
            # longo de %LOCALAPPDATA% só pra conferir se funcionou era o
            # próprio problema que ela reclamou (ver gui_page_trim_borders.py).
            try:
                if ok_count and os.path.isdir(backup_folder):
                    os.startfile(backup_folder)
                os.startfile(originals_folder)
            except OSError:
                pass

            gui_theme.show_message(
                self, status,
                f"{ok_count} figura(s) melhorada(s) com sucesso.\n{fail_count} falharam (veja o log acima "
                f"se quiser saber qual).\n\nJá abri a pasta com as figuras atuais no Explorer pra você "
                f"conferir.\n\nAntes (backup): {backup_folder}{extra}")

        def on_error(ex):
            self._running = False
            self.start_button.configure(state="normal")
            self.stop_button.pack_forget()
            self.status_label.configure(text="Falhou.")
            gui_theme.show_message(self, "Erro ao melhorar em lote", str(ex))

        gui_worker.run_task(self, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)

    def _stop_batch(self):
        if not self._running:
            return
        self._stop_event.set()
        self.status_label.configure(text="Parando (termina a figura atual)...")
        self.stop_button.configure(state="disabled")


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.title("Baby Luz — Melhorador de Imagens (IA)")
    root.geometry("900x760")

    class _StandaloneApp:
        def show_page(self, _key):
            root.destroy()

    ImageEnhancerPage(root, _StandaloneApp()).pack(fill="both", expand=True)
    root.mainloop()
