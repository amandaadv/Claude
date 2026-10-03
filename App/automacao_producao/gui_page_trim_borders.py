"""Recortar Bordas Transparentes: crops away invisible transparent padding
around a catalog's figures (see image_storage.trim_transparent_border).

An AI-generated figure is often exported on a canvas much bigger than its
own drawn content -- invisible in a normal preview since it's transparent,
but that padding is still part of the shape's bounding box everywhere a
size gets applied to it: at production time (the piece prints smaller than
its recorded size because the padding eats into that box) and in "Montar
Pedido"/catalog layout (fewer copies fit per row than the real content
would need, since the padding counts toward each copy's own width). This
fixes the file itself so both problems go away without touching any other
code -- same "backup before overwrite" safety the Melhorador de Imagens
page already uses, and no paid API involved (this runs entirely locally).
"""
import os

import customtkinter as ctk

import db
import gui_theme
import gui_worker
import pa
import paths


class TrimBordersPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app

        self._catalogs: list[tuple] = []
        self._catalog_id: int | None = None
        self._rows: list[dict] = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Recortar Bordas Transparentes").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Corta a margem transparente (invisível) que sobra em volta do desenho de cada figura "
                 "-- não muda o desenho, só remove o espaço vazio ao redor dele no arquivo. Isso ajuda em "
                 "dois lugares: a peça sai impressa no tamanho certo (a margem invisível estava roubando "
                 "espaço da medida gravada) e cabe mais cópias por linha em \"Montar Pedido\"/produção, "
                 "já que cada cópia deixa de contar aquele espaço vazio como parte do seu tamanho. Roda "
                 "local, sem custo de API. O original de cada figura fica guardado num backup antes de "
                 "ser substituído.",
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
            footer, text="Recortar em lote", width=200, height=36, command=self._start_batch,
        )
        self.start_button.pack(side="left")
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

        arts = db.get_arts_with_paths_by_catalog_id(catalog_id)
        self._rows = [
            {
                "art_id": art_id,
                "reference": reference or f"#{art_id}",
                "original_image_path": original_image_path,
                "preview_path": preview_path,
                "include_var": ctk.BooleanVar(value=True),
            }
            for art_id, reference, _page_number, original_image_path, preview_path, _review_status in arts
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
                self.table_frame, text="Esse catálogo não tem figuras com imagem pra recortar.",
                font=ctk.CTkFont(size=12), text_color="gray60").pack(anchor="w", pady=20)
            return

        for row in self._rows:
            item = ctk.CTkFrame(self.table_frame, fg_color=("gray95", "gray14"), corner_radius=8)
            item.pack(fill="x", pady=2)
            ctk.CTkCheckBox(
                item, variable=row["include_var"], text=row["reference"],
                font=ctk.CTkFont(size=13, weight="bold"),
            ).pack(side="left", padx=12, pady=8)

    # -- rodar em lote ---------------------------------------------------

    def _start_batch(self):
        if not self._rows:
            gui_theme.show_message(self, "Nada pra recortar", "Escolha um catálogo com figuras primeiro.")
            return

        selected = [row for row in self._rows if row["include_var"].get()]
        if not selected:
            gui_theme.show_message(self, "Nada marcado", "Marque pelo menos uma figura.")
            return

        if not gui_theme.ask_confirm(
            self, "Confirmar recorte em lote",
            f"Isso vai conferir {len(selected)} figura(s) e SUBSTITUIR o arquivo de qualquer uma que "
            f"tenha margem transparente pra cortar -- o original de cada uma alterada fica guardado num "
            f"backup antes disso. Quer continuar?",
            confirm_text="Recortar", danger=False,
        ):
            return

        catalog_id = self._catalog_id
        art_ids = [row["art_id"] for row in selected]

        self.start_button.configure(state="disabled")
        self.status_label.configure(text=f"Processando {len(selected)} figura(s)...")
        self.log_panel.show(f"Recortando {len(selected)} figura(s)...\n\n")

        def task():
            return pa.do_trim_catalog_borders(catalog_id, art_ids)

        def on_success(result):
            trimmed_count, already_tight_count, fail_count, tag = result
            self.start_button.configure(state="normal")
            status = f"Concluído: {trimmed_count} recortada(s), {already_tight_count} já justa(s), " \
                      f"{fail_count} falha(s)."
            self.status_label.configure(text=status)
            self.log_panel.hide_after()

            originals_folder = os.path.join(paths.STORAGE_FOLDER, "catalogs", str(self._catalog_id), "originals")
            backup_folder = os.path.join(paths.BACKUPS_FOLDER, "catalogs", str(self._catalog_id), tag)

            # Abre as duas pastas direto no Explorer -- pedir pra digitar/
            # colar um caminho longo de %LOCALAPPDATA% só pra conferir se
            # funcionou era o próprio problema que ela reclamou.
            try:
                if trimmed_count and os.path.isdir(backup_folder):
                    os.startfile(backup_folder)
                os.startfile(originals_folder)
            except OSError:
                pass

            backup_note = f"\n\nAntes (backup): {backup_folder}" if trimmed_count else ""
            gui_theme.show_message(
                self, "Recorte concluído",
                f"{trimmed_count} figura(s) recortada(s).\n{already_tight_count} já estavam justas, sem "
                f"nada pra fazer.\n{fail_count} falharam (veja o log acima se quiser saber qual).\n\n"
                f"Já abri a pasta com as figuras atuais (depois do recorte) no Explorer pra você conferir."
                f"{backup_note}")

        def on_error(ex):
            self.start_button.configure(state="normal")
            self.status_label.configure(text="Falhou.")
            gui_theme.show_message(self, "Erro ao recortar em lote", str(ex))

        gui_worker.run_task(self, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.title("Baby Luz — Recortar Bordas Transparentes")
    root.geometry("900x760")

    class _StandaloneApp:
        def show_page(self, _key):
            root.destroy()

    TrimBordersPage(root, _StandaloneApp()).pack(fill="both", expand=True)
    root.mainloop()
