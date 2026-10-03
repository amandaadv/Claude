"""Ajuntador de Páginas: builds a brand-new document with a single page
holding every source page side by side, in order -- for the shop's
continuous "faixa"/roll production files, which end up split into several
2000mm-tall pages even though they're really meant to print as one long
strip. Two sources, picked with a toggle:

- "Documento aberto no CorelDRAW": every page of whatever's already open
  and active there (see pa.do_join_pages).
- "Arquivos do computador": every page of several master .cdr files
  chosen straight from disk, one after another (see
  pa.do_join_pages_from_files) -- for joining pages across DIFFERENT
  catalogs into one, not just within a single already-open one.

Either way the original document(s)/file(s) are only ever read from,
never modified.
"""
import os

import customtkinter as ctk

import file_picker
import gui_theme
import gui_worker
import pa


class JoinPagesPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._file_paths: list[str] = []

        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Ajuntador de Páginas").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Junta várias páginas numa página só, uma do lado da outra na mesma ordem -- pra "
                 "transformar um arquivo de produção paginado numa faixa contínua só. Escolhe a "
                 "origem: o documento que já está aberto no CorelDRAW, ou vários arquivos do "
                 "computador (junta as páginas de todos eles, um catálogo atrás do outro, numa "
                 "página só). O(s) arquivo(s) original(is) não são alterados; isso salva um arquivo "
                 "novo.",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=860, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        self.source_var = ctk.StringVar(value="Documento aberto no CorelDRAW")
        source_toggle = ctk.CTkSegmentedButton(
            self, values=["Documento aberto no CorelDRAW", "Arquivos do computador"],
            variable=self.source_var, command=self._on_source_change,
        )
        source_toggle.grid(row=1, column=0, sticky="w", padx=28, pady=(0, 8))

        self.files_frame = ctk.CTkFrame(self, fg_color=("gray92", "gray17"), corner_radius=10)
        pick_row = ctk.CTkFrame(self.files_frame, fg_color="transparent")
        pick_row.pack(anchor="w", fill="x", padx=16, pady=(16, 8))
        gui_theme.secondary_button(
            pick_row, text="+ Escolher arquivos (.cdr)", width=200, command=self._pick_files,
        ).pack(side="left")
        self.files_list_frame = ctk.CTkScrollableFrame(
            self.files_frame, fg_color="transparent", height=90, **gui_theme.SCROLLBAR_KWARGS)
        self.files_list_frame.pack(anchor="w", fill="x", padx=16, pady=(0, 16))
        self.files_status_label = ctk.CTkLabel(
            self.files_list_frame, text="Nenhum arquivo escolhido ainda.",
            font=ctk.CTkFont(size=12), text_color="gray60")
        self.files_status_label.pack(anchor="w", padx=8, pady=8)
        self.files_frame.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 8))
        self.files_frame.grid_remove()  # só aparece no modo "Arquivos do computador"

        form = ctk.CTkFrame(self, fg_color=("gray92", "gray17"), corner_radius=10)
        form.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 8))
        spacing_row = ctk.CTkFrame(form, fg_color="transparent")
        spacing_row.pack(anchor="w", padx=16, pady=(16, 16))
        ctk.CTkLabel(spacing_row, text="Espaço entre páginas (mm):", font=ctk.CTkFont(size=13)).pack(
            side="left", padx=(0, 8))
        self.spacing_entry = ctk.CTkEntry(spacing_row, width=90)
        self.spacing_entry.insert(0, "0")
        self.spacing_entry.pack(side="left")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", padx=28, pady=(0, 8))
        gui_theme.primary_button(
            footer, text="Juntar Páginas", width=200, height=36, command=self._join,
        ).pack(side="left")

        self.log_panel = gui_worker.LogPanel(self)
        self.log_panel.grid(row=5, column=0, sticky="ew", padx=28, pady=(0, 20))

    def on_show(self):
        pass

    def _on_source_change(self, _choice=None):
        if self.source_var.get() == "Arquivos do computador":
            self.files_frame.grid()
        else:
            self.files_frame.grid_remove()

    def _pick_files(self):
        paths = file_picker.pick_cdr_files()
        if not paths:
            return
        self._file_paths = list(paths)
        for child in self.files_list_frame.winfo_children():
            child.destroy()
        ctk.CTkLabel(
            self.files_list_frame, text=f"{len(self._file_paths)} arquivo(s) escolhido(s):",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=8, pady=(8, 4))
        for path in self._file_paths:
            ctk.CTkLabel(
                self.files_list_frame, text=f"•  {os.path.basename(path)}",
                font=ctk.CTkFont(size=12), text_color="gray70", anchor="w",
            ).pack(anchor="w", padx=16, pady=1)

    def _join(self):
        try:
            spacing_mm = float(self.spacing_entry.get().strip().replace(",", "."))
            if spacing_mm < 0:
                raise ValueError
        except ValueError:
            gui_theme.show_message(self, "Valor inválido", "O espaço entre páginas precisa ser 0 ou maior (em mm).")
            return

        from_files = self.source_var.get() == "Arquivos do computador"
        if from_files and not self._file_paths:
            gui_theme.show_message(self, "Sem arquivos", "Escolha pelo menos um arquivo .cdr.")
            return

        save_path = file_picker.pick_save_path("paginas_juntadas.cdr")
        if not save_path:
            return

        self.log_panel.show("Juntando as páginas no CorelDRAW...\n\n")
        file_paths = list(self._file_paths)

        def task():
            if from_files:
                pa.do_join_pages_from_files(file_paths, save_path, spacing_mm)
            else:
                pa.do_join_pages(save_path, spacing_mm)

        def on_success(_result):
            self.log_panel.hide_after()
            gui_theme.show_message(self, "Páginas juntadas", f"Arquivo salvo em:\n{save_path}")

        def on_error(ex):
            gui_theme.show_message(self, "Erro ao juntar", str(ex))

        gui_worker.run_task(
            self.app, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)
