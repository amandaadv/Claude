"""Importar Vários Catálogos page: pick several designer master .cdr files
straight from the computer (not from what's already in the system) and
import all of them into ONE new merged catalog. See
pa.do_import_from_multiple_masters for how REF collisions across files
and each art's size are handled.
"""
import os

import customtkinter as ctk

import db
import file_picker
import gui_theme
import gui_worker
import pa


class MergeCatalogsPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._file_paths: list[str] = []
        self._profiles: dict[str, tuple] = {}  # rótulo exibido -> linha do perfil (db.get_all_profiles)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Importar Vários Catálogos").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Escolhe vários arquivos originais (.cdr) direto do computador e importa todos juntos "
                 "num catálogo novo só, em vez de um catálogo pra cada arquivo. Cada peça mantém a REF e "
                 "a medida do próprio arquivo dela; se a mesma REF aparecer em mais de um arquivo "
                 "escolhido, só a primeira entra. O catálogo é montado no CorelDRAW com as configurações "
                 "do perfil de produção que você escolher (largura, margens, espaçamento e altura da página).",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=860, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        name_row = ctk.CTkFrame(self, fg_color="transparent")
        name_row.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 8))
        ctk.CTkLabel(name_row, text="Nome do catálogo:", font=ctk.CTkFont(size=12)).pack(side="left")
        self.name_entry = ctk.CTkEntry(name_row, width=280, placeholder_text="ex: CATALOGO JUNTADO")
        self.name_entry.pack(side="left", padx=(8, 20))
        gui_theme.primary_button(
            name_row, text="+ Escolher arquivos (.cdr)", width=200, command=self._pick_files,
        ).pack(side="left")

        profile_row = ctk.CTkFrame(self, fg_color="transparent")
        profile_row.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 8))
        ctk.CTkLabel(profile_row, text="Perfil de produção:", font=ctk.CTkFont(size=12)).pack(side="left")
        self.profile_menu = ctk.CTkComboBox(
            profile_row, width=280, state="readonly", values=[""], command=self._on_profile_changed)
        self.profile_menu.pack(side="left", padx=(8, 12))
        self.profile_info_label = ctk.CTkLabel(
            profile_row, text="", font=ctk.CTkFont(size=11), text_color="gray60")
        self.profile_info_label.pack(side="left")

        self.files_list_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.files_list_frame.grid(row=3, column=0, sticky="nsew", padx=28, pady=(4, 8))
        self.status_label = ctk.CTkLabel(
            self.files_list_frame, text="Nenhum arquivo escolhido ainda.",
            font=ctk.CTkFont(size=12), text_color="gray60")
        self.status_label.pack(anchor="w", padx=8, pady=8)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", padx=28, pady=(0, 8))
        gui_theme.primary_button(
            footer, text="Importar e Juntar", width=180, command=self._import,
        ).pack(side="left")

        self.log_panel = gui_worker.LogPanel(self)
        self.log_panel.grid(row=5, column=0, sticky="ew", padx=28, pady=(0, 20))

    def on_show(self):
        self._load_profiles()

    def _load_profiles(self):
        """Puxa os perfis de produção cadastrados (mesma lista da aba Perfis
        de Produção) e mantém a escolha atual se ela ainda existir; sem
        nenhum perfil cadastrado, cai no layout padrão da prévia."""
        rows = db.get_all_profiles()
        default_row = db.get_default_profile()
        default_id = default_row[0] if default_row else None
        previous = self.profile_menu.get()

        self._profiles = {}
        default_label = None
        for row in rows:
            profile_id, name, width_mm, height_mm = row[0], row[1], row[2], row[3]
            label = f"{name} ({width_mm:g}mm x {height_mm:g}mm)" + (" — padrão" if profile_id == default_id else "")
            self._profiles[label] = row
            if profile_id == default_id:
                default_label = label

        if not self._profiles:
            self.profile_menu.configure(values=["Sem perfil (layout padrão)"])
            self.profile_menu.set("Sem perfil (layout padrão)")
            self.profile_info_label.configure(
                text="Nenhum perfil cadastrado -- cadastre em Perfis de Produção.")
            return

        labels = list(self._profiles)
        self.profile_menu.configure(values=labels)
        self.profile_menu.set(previous if previous in self._profiles else (default_label or labels[0]))
        self._on_profile_changed(self.profile_menu.get())

    def _on_profile_changed(self, label):
        row = self._profiles.get(label)
        if row is None:
            self.profile_info_label.configure(text="")
            return
        _id, _name, _w, _h, margin_left, margin_right, margin_top, margin_bottom, spacing_h, spacing_v, _material = row
        self.profile_info_label.configure(
            text=f"margens E{margin_left:g}/D{margin_right:g}/T{margin_top:g}/B{margin_bottom:g}mm  ·  "
                 f"espaçamento H{spacing_h:g}/V{spacing_v:g}mm")

    def _selected_profile_id(self):
        row = self._profiles.get(self.profile_menu.get())
        return row[0] if row else None

    def _pick_files(self):
        paths = file_picker.pick_cdr_files()
        if not paths:
            return
        self._file_paths = list(paths)
        self._render_file_list()

    def _render_file_list(self):
        for child in self.files_list_frame.winfo_children():
            child.destroy()
        if not self._file_paths:
            ctk.CTkLabel(
                self.files_list_frame, text="Nenhum arquivo escolhido ainda.",
                font=ctk.CTkFont(size=12), text_color="gray60").pack(anchor="w", padx=8, pady=8)
            return
        ctk.CTkLabel(
            self.files_list_frame, text=f"{len(self._file_paths)} arquivo(s) escolhido(s):",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=8, pady=(8, 4))
        for path in self._file_paths:
            ctk.CTkLabel(
                self.files_list_frame, text=f"•  {os.path.basename(path)}",
                font=ctk.CTkFont(size=12), text_color="gray70", anchor="w",
            ).pack(anchor="w", padx=16, pady=1)

    def _import(self):
        name = self.name_entry.get().strip()
        if not name:
            gui_theme.show_message(self, "Falta o nome", "Digite um nome pro catálogo antes de importar.")
            return
        if len(self._file_paths) < 1:
            gui_theme.show_message(self, "Sem arquivos", "Escolha pelo menos um arquivo .cdr.")
            return

        save_path = file_picker.pick_save_path(f"{name}.cdr")
        if not save_path:
            return

        file_paths = list(self._file_paths)
        profile_id = self._selected_profile_id()
        profile_label = self.profile_menu.get() if profile_id is not None else "layout padrão"
        self.log_panel.show(f"Importando {len(file_paths)} arquivo(s) em '{name}'...\n\n")

        def task():
            catalog_id = pa.do_import_from_multiple_masters(file_paths, name)
            if catalog_id is not None:
                # Junta tudo num .cdr único de verdade, pra abrir e conferir --
                # NUNCA publica no site sozinho (isso é manual, na tela de Catálogos).
                pa.do_export_catalog_preview(catalog_id, save_path, profile_id=profile_id)
            return catalog_id

        def on_success(catalog_id):
            self.log_panel.hide_after()
            if catalog_id is None:
                gui_theme.show_message(
                    self.app, "Nada importado", "Nenhuma referência foi encontrada em nenhum dos arquivos.")
                return
            gui_theme.show_message(
                self.app, "Catálogo criado",
                f"\"{name}\" criado (id={catalog_id}) juntando {len(file_paths)} arquivo(s) -- "
                f"NÃO foi publicado no site. Montado com o perfil: {profile_label}. "
                f"O .cdr único foi salvo e já está aberto no CorelDRAW:\n{save_path}")
            self.name_entry.delete(0, "end")
            self._file_paths = []
            self._render_file_list()

        def on_error(ex):
            gui_theme.show_message(self.app, "Erro ao importar", str(ex))

        gui_worker.run_task(
            self.app, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)
