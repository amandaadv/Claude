"""Perfis de Produção page: CRUD for the production-area profiles (size,
margins, spacing between copies) used when generating a sheet in CorelDRAW.
"""
import customtkinter as ctk

import db
import gui_theme
import pa

# Rótulo mostrado -> valor gravado (igual gui_page_catalogs.py) -- é isso que deixa "Gerar
# produção" perguntar só o MATERIAL e achar o perfil certo sozinho (ver db.get_profile_by_material).
PROFILE_MATERIAIS = {"Nenhum (perfil genérico)": None, "Têxtil - Termocolante": "Textil", "Adesivo - UV": "UV"}


class ProfilesPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 8))
        header.grid_columnconfigure(0, weight=1)
        gui_theme.back_button(header, self.app).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        gui_theme.section_title(header, "Perfis de Produção").grid(row=1, column=0, sticky="w")
        gui_theme.card_button(
            header, "📐", "Novo perfil", self._create, width=120, height=70,
        ).grid(row=1, column=1, sticky="e")

        ctk.CTkLabel(
            self, text="Tamanho da área de produção (a tela do CorelDRAW), margens e espaçamento entre peças "
                       "(pra não ficarem grudadas).",
            font=ctk.CTkFont(size=12), text_color="gray60", anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=28)

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.list_frame.grid(row=2, column=0, sticky="nsew", padx=24, pady=(8, 24))
        self.list_frame.grid_columnconfigure((0, 1), weight=1, uniform="cards")
        self.CARD_COLUMNS = 2

        # Data loads on first on_show(), not here -- see gui_page_catalogs.py.

    def on_show(self):
        self.refresh()

    def refresh(self):
        for child in self.list_frame.winfo_children():
            child.destroy()

        profiles = db.get_all_profiles()
        default_row = db.get_default_profile()
        default_id = default_row[0] if default_row else None

        if not profiles:
            ctk.CTkLabel(self.list_frame, text="Nenhum perfil cadastrado ainda.", text_color="gray60").grid(
                row=0, column=0, sticky="w")
            return

        for i, (profile_id, name, width_mm, height_mm, ml, mr, mt, mb, sh, sv, material) in enumerate(profiles):
            is_default = profile_id == default_id
            card = ctk.CTkFrame(self.list_frame, corner_radius=20, fg_color=("white", "gray17"),
                                 border_width=1, border_color=("gray88", "gray25"))
            card.grid(row=i // self.CARD_COLUMNS, column=i % self.CARD_COLUMNS,
                      sticky="new", pady=10, padx=10, ipadx=4)

            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=18, pady=(18, 8))
            ctk.CTkLabel(
                top, text="📐", font=ctk.CTkFont(size=19), fg_color=gui_theme.ACCENT_SLATE,
                text_color="white", corner_radius=13, width=44, height=44,
            ).pack(side="left", padx=(0, 12))
            ctk.CTkLabel(
                top, text=name, font=ctk.CTkFont(size=15, weight="bold"),
                wraplength=200, justify="left", anchor="w",
            ).pack(side="left", fill="x")
            if is_default:
                gui_theme.pill(top, "⭐ padrão", "#fff3d6", "#a1720a").pack(side="left", padx=(8, 0))

            pills = ctk.CTkFrame(card, fg_color="transparent")
            pills.pack(anchor="w", padx=18, pady=(0, 10))
            gui_theme.pill(
                pills, f"📏 {width_mm}mm x {height_mm}mm", "#e5f1fb", gui_theme.ACCENT_BLUE_HOVER,
            ).grid(row=0, column=0, sticky="w", padx=(0, 6), pady=3)
            gui_theme.pill(
                pills, f"↔️ margens {ml}/{mr}/{mt}/{mb}mm", "#f3ecfb", gui_theme.ACCENT_PURPLE_HOVER,
            ).grid(row=1, column=0, sticky="w", pady=3)
            gui_theme.pill(
                pills, f"↕️ espaço {sh}/{sv}mm", "#e3faf1", "#1e8a4c",
            ).grid(row=2, column=0, sticky="w", pady=3)
            # Material amarrado a esse perfil ("Gerar produção" usa isso pra achar o perfil certo
            # sozinho quando pergunta só o material -- ver db.get_profile_by_material).
            material_label = next((l for l, v in PROFILE_MATERIAIS.items() if v == material), None)
            if material_label and material:
                gui_theme.pill(pills, f"🧵 {material_label}", "#fdecea" if material == "UV" else "#e3f7e6",
                                "#c0392b" if material == "UV" else "#1e8a4c").grid(
                    row=3, column=0, sticky="w", pady=3)

            actions = ctk.CTkFrame(card, fg_color="transparent")
            actions.pack(fill="x", padx=18, pady=(4, 18))
            if not is_default:
                gui_theme.secondary_button(
                    actions, text="Tornar padrão", width=120, height=30,
                    command=lambda pid=profile_id: self._set_default(pid),
                ).pack(side="left", padx=(0, 4), pady=2)
            ctk.CTkButton(
                actions, text="Editar", width=90, height=30, fg_color="gray40", hover_color="gray30",
                command=lambda p=(profile_id, name, width_mm, height_mm, ml, mr, mt, mb, sh, sv, material): self._edit(p),
            ).pack(side="left", padx=4, pady=2)
            gui_theme.danger_button(
                actions, text="Excluir", width=90, height=30,
                command=lambda pid=profile_id, n=name: self._delete(pid, n),
            ).pack(side="left", padx=4, pady=2)

    def _set_default(self, profile_id):
        db.set_default_profile(profile_id)
        self.refresh()

    def _create(self):
        values = ProfileFormDialog.ask(self.app, "Novo perfil de produção")
        if values is None:
            return
        name, width_mm, height_mm, ml, mr, mt, mb, sh, sv, make_default, material = values
        pa.do_create_profile(name, width_mm, height_mm, ml, mr, mt, mb, sh, sv, make_default, material)
        self.refresh()
        gui_theme.show_message(self.app, "Perfil criado", f"\"{name}\" criado com sucesso.")

    def _edit(self, profile):
        profile_id, name, width_mm, height_mm, ml, mr, mt, mb, sh, sv, material = profile
        values = ProfileFormDialog.ask(
            self.app, f"Editar perfil \"{name}\"",
            initial=(name, width_mm, height_mm, ml, mr, mt, mb, sh, sv, material), show_default_checkbox=False)
        if values is None:
            return
        name, width_mm, height_mm, ml, mr, mt, mb, sh, sv, _, material = values
        pa.do_edit_profile(profile_id, name, width_mm, height_mm, ml, mr, mt, mb, sh, sv, material)
        self.refresh()

    def _delete(self, profile_id, name):
        if len(db.get_all_profiles()) <= 1:
            gui_theme.show_message(
                self.app, "Não é possível excluir",
                "Esse é o único perfil cadastrado -- crie outro antes de excluir este.")
            return
        if not gui_theme.ask_confirm(
            self.app, "Excluir perfil",
            f"Tem certeza que quer excluir o perfil \"{name}\"? Essa ação não pode ser desfeita.",
            confirm_text="Excluir", danger=True,
        ):
            return
        pa.do_delete_profile(profile_id)
        self.refresh()
        gui_theme.show_message(self.app, "Excluído", f"\"{name}\" excluído com sucesso.")


class ProfileFormDialog(ctk.CTkToplevel):
    def __init__(self, master, title, initial=None, show_default_checkbox=True):
        super().__init__(master)
        self.title(title)
        gui_theme.center_over_master(self, master, 420, 600)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.result = None

        initial = initial or ("", "", "", 0, 0, 0, 0, 0, 0, None)
        (name0, width0, height0, ml0, mr0, mt0, mb0, sh0, sv0, material0) = initial

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        scroll.pack(fill="both", expand=True, padx=20, pady=20)

        self.name_entry = self._labeled_entry(scroll, "Nome do perfil", str(name0))
        self.width_entry = self._labeled_entry(scroll, "Largura da área de produção (mm)", str(width0))
        self.height_entry = self._labeled_entry(scroll, "Altura da área de produção (mm)", str(height0))

        ctk.CTkLabel(scroll, text="Margens (mm)", font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", pady=(12, 4))
        margins_row = ctk.CTkFrame(scroll, fg_color="transparent")
        margins_row.pack(fill="x")
        self.margin_left_entry = self._grid_entry(margins_row, "Esquerda", str(ml0), 0)
        self.margin_right_entry = self._grid_entry(margins_row, "Direita", str(mr0), 1)
        self.margin_top_entry = self._grid_entry(margins_row, "Superior", str(mt0), 2)
        self.margin_bottom_entry = self._grid_entry(margins_row, "Inferior", str(mb0), 3)

        ctk.CTkLabel(scroll, text="Espaçamento entre peças (mm)", font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", pady=(16, 4))
        spacing_row = ctk.CTkFrame(scroll, fg_color="transparent")
        spacing_row.pack(fill="x")
        self.spacing_h_entry = self._grid_entry(spacing_row, "Horizontal", str(sh0), 0)
        self.spacing_v_entry = self._grid_entry(spacing_row, "Vertical", str(sv0), 1)

        ctk.CTkLabel(
            scroll, text="Material (pra \"Gerar produção\" perguntar só isso e achar o perfil sozinho)",
            font=ctk.CTkFont(size=13, weight="bold"), wraplength=360, justify="left",
        ).pack(anchor="w", pady=(16, 4))
        self.material_combo = ctk.CTkComboBox(scroll, values=list(PROFILE_MATERIAIS), state="readonly")
        self.material_combo.pack(fill="x")
        self.material_combo.set(next(
            (label for label, value in PROFILE_MATERIAIS.items() if value == material0),
            next(iter(PROFILE_MATERIAIS))))

        self.make_default_var = ctk.BooleanVar(value=False)
        if show_default_checkbox:
            ctk.CTkCheckBox(scroll, text="Tornar esse o perfil padrão", variable=self.make_default_var).pack(
                anchor="w", pady=(16, 0))

        self.error_label = ctk.CTkLabel(scroll, text="", text_color=gui_theme.DANGER, font=ctk.CTkFont(size=11))
        self.error_label.pack(anchor="w", pady=(8, 0))

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=(0, 16))
        ctk.CTkButton(button_row, text="Cancelar", fg_color="gray40", hover_color="gray30",
                      width=110, command=self._cancel).pack(side="left", padx=8)
        gui_theme.primary_button(button_row, text="Salvar", width=110, command=self._confirm).pack(side="left", padx=8)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Return>", lambda _e: self._confirm())
        self.bind("<Escape>", lambda _e: self._cancel())

    def _labeled_entry(self, master, label, default=""):
        ctk.CTkLabel(master, text=label, font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(6, 2))
        entry = ctk.CTkEntry(master)
        entry.insert(0, default)
        entry.pack(fill="x")
        return entry

    def _grid_entry(self, master, label, default, col):
        master.grid_columnconfigure(col, weight=1)
        frame = ctk.CTkFrame(master, fg_color="transparent")
        frame.grid(row=0, column=col, sticky="ew", padx=4)
        ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=11), text_color="gray60").pack(anchor="w")
        entry = ctk.CTkEntry(frame, width=80)
        entry.insert(0, default)
        entry.pack(fill="x")
        return entry

    def _parse_float(self, entry, field_name, allow_zero=True):
        raw = entry.get().strip().replace(",", ".")
        if not raw:
            return 0.0 if allow_zero else None
        try:
            return float(raw)
        except ValueError:
            raise ValueError(f"{field_name} inválido: \"{raw}\"")

    def _confirm(self):
        name = self.name_entry.get().strip()
        if not name:
            self.error_label.configure(text="Informe um nome para o perfil.")
            return
        try:
            width_mm = self._parse_float(self.width_entry, "Largura", allow_zero=False)
            height_mm = self._parse_float(self.height_entry, "Altura", allow_zero=False)
            if not width_mm or not height_mm or width_mm <= 0 or height_mm <= 0:
                raise ValueError("Largura e altura precisam ser maiores que zero.")
            ml = self._parse_float(self.margin_left_entry, "Margem esquerda")
            mr = self._parse_float(self.margin_right_entry, "Margem direita")
            mt = self._parse_float(self.margin_top_entry, "Margem superior")
            mb = self._parse_float(self.margin_bottom_entry, "Margem inferior")
            sh = self._parse_float(self.spacing_h_entry, "Espaçamento horizontal")
            sv = self._parse_float(self.spacing_v_entry, "Espaçamento vertical")
        except ValueError as ex:
            self.error_label.configure(text=str(ex))
            return

        material = PROFILE_MATERIAIS.get(self.material_combo.get())
        self.result = (name, width_mm, height_mm, ml, mr, mt, mb, sh, sv, self.make_default_var.get(), material)
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()

    @staticmethod
    def ask(master, title, initial=None, show_default_checkbox=True):
        dialog = ProfileFormDialog(master, title, initial, show_default_checkbox)
        master.wait_window(dialog)
        return dialog.result
