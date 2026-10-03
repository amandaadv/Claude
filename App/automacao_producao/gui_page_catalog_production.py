"""Produção do Catálogo Inteiro: pick one already-imported catalog, then either

  - "Usar tamanho original de cada peça": one click, every approved REF goes
    straight to a production sheet at its own already-recorded size (see
    pa.do_generate_production_for_whole_catalog) -- no size to type at all.

  - "Trocar tamanho em lote": the older two-step flow -- first find every REF
    that's CURRENTLY at some given size (a real catalog routinely mixes a
    few different sizes; this isolates just one group), then type the NEW
    size to apply to only that found group.

Either way this generates straight into a production (cutting) sheet in
CorelDRAW without going through the production queue at all, unlike "Gerar
Produção" (that one works off whatever's already queued, one piece at a
time).
"""
import customtkinter as ctk

import db
import file_picker
import gui_theme
import gui_worker
import pa


class CatalogProductionPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._catalogs = []
        self._catalog_id = None
        self._found_arts: list[tuple] = []

        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Produção do Catálogo Inteiro").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Escolhe um catálogo e gera a produção (folha de corte) dele inteiro no CorelDRAW, sem "
                 "passar pela fila. \"Usar tamanho original\" manda cada REF do jeito que já está gravada "
                 "-- um clique só. \"Trocar tamanho em lote\" acha as REFs de uma medida atual e aplica "
                 "uma medida nova só nelas (útil quando o catálogo mistura mais de um tamanho).",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=860, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        # -- catálogo (compartilhado pelos dois modos) ------------------------
        catalog_card = ctk.CTkFrame(self, fg_color=("gray92", "gray17"), corner_radius=10)
        catalog_card.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 8))
        catalog_row = ctk.CTkFrame(catalog_card, fg_color="transparent")
        catalog_row.pack(anchor="w", fill="x", padx=16, pady=14)
        ctk.CTkLabel(catalog_row, text="Catálogo:", font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 8))
        self.catalog_var = ctk.StringVar(value="")
        self.catalog_combo = ctk.CTkComboBox(
            catalog_row, values=[], variable=self.catalog_var, width=420,
            command=self._on_catalog_selected, state="readonly")
        self.catalog_combo.pack(side="left")

        # -- modo ---------------------------------------------------------------
        self.mode_var = ctk.StringVar(value="original")
        mode_toggle = ctk.CTkSegmentedButton(
            self, values=["Usar tamanho original", "Trocar tamanho em lote"],
            command=self._on_mode_changed, width=420, height=32,
        )
        mode_toggle.set("Usar tamanho original")
        mode_toggle.grid(row=2, column=0, sticky="w", padx=28, pady=(0, 8))

        # -- modo "tamanho original": simples, um clique -----------------------
        self.simple_panel = ctk.CTkFrame(self, fg_color=("gray92", "gray17"), corner_radius=10)
        self.simple_panel.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 8))
        ctk.CTkLabel(
            self.simple_panel, text="Toda REF aprovada desse catálogo, cada uma na medida já gravada pra ela.",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=820, justify="left",
        ).pack(anchor="w", padx=16, pady=(14, 8))

        simple_options_row = ctk.CTkFrame(self.simple_panel, fg_color="transparent")
        simple_options_row.pack(anchor="w", padx=16, pady=(0, 8))
        ctk.CTkLabel(simple_options_row, text="Cópias por linha (opcional):", font=ctk.CTkFont(size=13)).pack(
            side="left", padx=(0, 8))
        self.simple_copies_entry = ctk.CTkEntry(
            simple_options_row, width=70, placeholder_text="auto")
        self.simple_copies_entry.pack(side="left", padx=(0, 20))
        ctk.CTkLabel(simple_options_row, text="Orientação:", font=ctk.CTkFont(size=13)).pack(
            side="left", padx=(0, 8))
        self.simple_orientation_combo = ctk.CTkComboBox(
            simple_options_row, values=["Original de cada peça", "Forçar em pé", "Forçar deitada"],
            width=200, state="readonly")
        self.simple_orientation_combo.set("Original de cada peça")
        self.simple_orientation_combo.pack(side="left")

        self.simple_generate_button = gui_theme.primary_button(
            self.simple_panel, text="Gerar Produção do Catálogo", width=240, height=36,
            command=self._generate_simple,
        )
        self.simple_generate_button.pack(anchor="w", padx=16, pady=(0, 14))

        # -- modo "trocar tamanho": passo 1 (achar por medida atual) ----------
        self.step1 = ctk.CTkFrame(self, fg_color=("gray92", "gray17"), corner_radius=10)
        self.step1.grid(row=4, column=0, sticky="ew", padx=28, pady=(0, 8))
        ctk.CTkLabel(
            self.step1, text="1) Achar REFs por medida atual", font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(14, 6))

        current_size_row = ctk.CTkFrame(self.step1, fg_color="transparent")
        current_size_row.pack(anchor="w", padx=16, pady=(0, 8))
        ctk.CTkLabel(current_size_row, text="Altura atual (mm):", font=ctk.CTkFont(size=13)).pack(
            side="left", padx=(0, 8))
        self.current_altura_entry = ctk.CTkEntry(current_size_row, width=90)
        self.current_altura_entry.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(current_size_row, text="Largura atual (mm):", font=ctk.CTkFont(size=13)).pack(
            side="left", padx=(0, 8))
        self.current_largura_entry = ctk.CTkEntry(current_size_row, width=90)
        self.current_largura_entry.pack(side="left", padx=(0, 16))
        gui_theme.secondary_button(
            current_size_row, text="Buscar REFs", width=140, height=32, command=self._search,
        ).pack(side="left")

        # Some catalogs only keep ONE side fixed across every REF (usually
        # a "faixa"'s altura) while the other varies per piece to keep its
        # own proportion -- there's no shared largura value to search for
        # at all in that case (confirmed live: "290x60" found nothing even
        # though every piece really does share the same 290mm height).
        # Checking this ignores Largura atual entirely and matches on
        # Altura atual alone.
        self.width_proportional_var = ctk.BooleanVar(value=False)
        self.width_proportional_check = ctk.CTkCheckBox(
            self.step1, text="Largura é proporcional (varia por figura) -- buscar só pela altura",
            variable=self.width_proportional_var, font=ctk.CTkFont(size=12),
            command=self._on_width_proportional_toggle)
        self.width_proportional_check.pack(anchor="w", padx=16, pady=(0, 10))

        self.search_result_label = ctk.CTkLabel(
            self.step1, text="Nenhuma busca feita ainda.", font=ctk.CTkFont(size=12), text_color="gray60")
        self.search_result_label.pack(anchor="w", padx=16, pady=(0, 14))

        # -- passo 2: medida nova + gerar ---------------------------------
        self.step2 = ctk.CTkFrame(self, fg_color=("gray92", "gray17"), corner_radius=10)
        self.step2.grid(row=5, column=0, sticky="ew", padx=28, pady=(0, 8))
        ctk.CTkLabel(
            self.step2, text="2) Aplicar medida nova nessas REFs encontradas",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(14, 6))

        new_size_row = ctk.CTkFrame(self.step2, fg_color="transparent")
        new_size_row.pack(anchor="w", padx=16, pady=(0, 14))
        ctk.CTkLabel(new_size_row, text="Altura nova (mm):", font=ctk.CTkFont(size=13)).pack(
            side="left", padx=(0, 8))
        self.new_altura_entry = ctk.CTkEntry(new_size_row, width=90)
        self.new_altura_entry.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(new_size_row, text="Largura nova (mm):", font=ctk.CTkFont(size=13)).pack(
            side="left", padx=(0, 8))
        self.new_largura_entry = ctk.CTkEntry(new_size_row, width=90)
        self.new_largura_entry.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(new_size_row, text="Cópias por linha:", font=ctk.CTkFont(size=13)).pack(
            side="left", padx=(0, 8))
        self.copies_per_row_entry = ctk.CTkEntry(new_size_row, width=70, placeholder_text="ex: 12")
        self.copies_per_row_entry.pack(side="left")

        self.step2.grid_remove()  # só aparece depois de uma busca com resultado

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=6, column=0, sticky="ew", padx=28, pady=(0, 8))
        self.generate_button = gui_theme.primary_button(
            footer, text="Gerar Produção", width=200, height=36, command=self._generate,
        )
        self.generate_button.pack(side="left")
        self.generate_button.configure(state="disabled")

        self.log_panel = gui_worker.LogPanel(self)
        self.log_panel.grid(row=7, column=0, sticky="ew", padx=28, pady=(0, 20))

        self.step1.grid_remove()
        self.step2.grid_remove()
        footer.grid_remove()
        self._footer = footer

    def on_show(self):
        self._catalogs = db.get_all_catalogs()
        values = [
            f"{name}  ({approved_arts} REF(s) aprovada(s))"
            for _id, name, _status, _created_at, _total, approved_arts, _ref, _pub in self._catalogs
        ]
        self.catalog_combo.configure(values=values)
        if values and self.catalog_var.get() not in values:
            self.catalog_var.set(values[0])
            self._on_catalog_selected(values[0])
        elif not values:
            self.catalog_var.set("")
            self._catalog_id = None

    def _on_mode_changed(self, selected_value):
        if selected_value == "Usar tamanho original":
            self.mode_var.set("original")
            self.simple_panel.grid()
            self.step1.grid_remove()
            self.step2.grid_remove()
            self._footer.grid_remove()
        else:
            self.mode_var.set("troca")
            self.simple_panel.grid_remove()
            self.step1.grid()
            self._footer.grid()
            if self._found_arts:
                self.step2.grid()

    def _on_catalog_selected(self, selected_value):
        self._catalog_id = None
        for row in self._catalogs:
            catalog_id, name, _status, _created_at, _total, approved_arts, _ref, _pub = row
            if f"{name}  ({approved_arts} REF(s) aprovada(s))" == selected_value:
                self._catalog_id = catalog_id
                break
        self._reset_search()

    def _reset_search(self):
        self._found_arts = []
        self.search_result_label.configure(text="Nenhuma busca feita ainda.")
        self.step2.grid_remove()
        self.generate_button.configure(state="disabled")

    def _on_width_proportional_toggle(self):
        if self.width_proportional_var.get():
            self.current_largura_entry.configure(state="disabled")
        else:
            self.current_largura_entry.configure(state="normal")

    # -- modo "tamanho original" -------------------------------------------

    def _generate_simple(self):
        if self._catalog_id is None:
            gui_theme.show_message(self, "Nenhum catálogo", "Escolha um catálogo primeiro.")
            return

        copies_text = self.simple_copies_entry.get().strip()
        copies_per_row = None
        if copies_text:
            try:
                copies_per_row = int(copies_text)
                if copies_per_row <= 0:
                    raise ValueError
            except ValueError:
                gui_theme.show_message(
                    self, "Quantidade inválida",
                    "\"Cópias por linha\" precisa ser um número inteiro maior que zero, ou deixe em branco "
                    "pra automático.")
                return

        orientation_label = self.simple_orientation_combo.get()
        force_orientation = {
            "Original de cada peça": None, "Forçar em pé": "vertical", "Forçar deitada": "horizontal",
        }[orientation_label]

        profiles = db.get_all_profiles()
        if not profiles:
            gui_theme.show_message(
                self, "Sem perfis", "Cadastre um perfil de produção primeiro (aba Perfis de Produção).")
            return
        default_row = db.get_default_profile()
        default_id = default_row[0] if default_row else profiles[0][0]
        choices = [(f"{name} ({width_mm}mm x {height_mm}mm)", pid) for pid, name, width_mm, height_mm, *_ in profiles]
        default_index = next((i for i, p in enumerate(profiles) if p[0] == default_id), 0)
        profile_id = gui_theme.ask_choice(
            self.app, "Escolher perfil", "Qual perfil de produção usar?", choices, default_index)
        if profile_id is None:
            return

        catalog_name = next((row[1] for row in self._catalogs if row[0] == self._catalog_id), "producao")
        save_path = file_picker.pick_save_path(f"{catalog_name}.cdr")
        if not save_path:
            return

        self.log_panel.show("Gerando produção no CorelDRAW...\n\n")
        catalog_id = self._catalog_id

        def task():
            pa.do_generate_production_for_whole_catalog(
                catalog_id, save_path, profile_id, copies_per_row, force_orientation)

        def on_success(_result):
            self.log_panel.hide_after()
            gui_theme.show_message(self, "Produção gerada", f"Arquivo salvo em:\n{save_path}")

        def on_error(ex):
            gui_theme.show_message(self, "Erro ao gerar", str(ex))

        gui_worker.run_task(
            self.app, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)

    # -- modo "trocar tamanho em lote" -------------------------------------

    def _search(self):
        if self._catalog_id is None:
            gui_theme.show_message(self, "Nenhum catálogo", "Escolha um catálogo primeiro.")
            return
        width_is_proportional = self.width_proportional_var.get()
        try:
            current_altura_mm = float(self.current_altura_entry.get().strip().replace(",", "."))
            if current_altura_mm <= 0:
                raise ValueError
            if width_is_proportional:
                current_largura_mm = 0.0
            else:
                current_largura_mm = float(self.current_largura_entry.get().strip().replace(",", "."))
                if current_largura_mm <= 0:
                    raise ValueError
        except ValueError:
            campo = "a altura atual" if width_is_proportional else "a altura e a largura atuais"
            gui_theme.show_message(
                self, "Medida inválida", f"Preencha {campo} com número(s) maior(es) que zero (em mm).")
            return

        # Runs in the background, not straight on the UI thread -- a REF
        # with no locked size at all now falls back to opening the master
        # .cdr and measuring its real artwork (see
        # pa.find_arts_by_current_size), which can take a while on a big
        # file and would otherwise freeze the whole window meanwhile.
        catalog_id = self._catalog_id
        self.search_result_label.configure(text="Buscando...")
        self.log_panel.show("Buscando REFs (pode abrir o CorelDRAW se precisar medir a arte original)...\n\n")

        def task():
            return pa.find_arts_by_current_size(
                catalog_id, current_largura_mm, current_altura_mm, width_is_proportional=width_is_proportional)

        def on_success(found_arts):
            self.log_panel.hide_after()
            self._found_arts = found_arts
            if not self._found_arts:
                medida_txt = f"altura {current_altura_mm:g}mm" if width_is_proportional \
                    else f"{current_altura_mm:g}mm x {current_largura_mm:g}mm"
                self.search_result_label.configure(text=f"Nenhuma REF encontrada com {medida_txt} nesse catálogo.")
                self.step2.grid_remove()
                self.generate_button.configure(state="disabled")
                return

            refs = ", ".join(row[1] for row in self._found_arts[:20])
            more = f" (+{len(self._found_arts) - 20})" if len(self._found_arts) > 20 else ""
            self.search_result_label.configure(
                text=f"{len(self._found_arts)} REF(s) encontrada(s): {refs}{more}")
            self.step2.grid()
            self.generate_button.configure(state="normal")

        def on_error(ex):
            self.search_result_label.configure(text="Erro na busca.")
            gui_theme.show_message(self, "Erro ao buscar", str(ex))

        gui_worker.run_task(
            self.app, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)

    def _generate(self):
        if not self._found_arts or self._catalog_id is None:
            gui_theme.show_message(self, "Nada pra gerar", "Busque as REFs primeiro (passo 1).")
            return
        try:
            new_altura_mm = float(self.new_altura_entry.get().strip().replace(",", "."))
            new_largura_mm = float(self.new_largura_entry.get().strip().replace(",", "."))
            if new_altura_mm <= 0 or new_largura_mm <= 0:
                raise ValueError
        except ValueError:
            gui_theme.show_message(
                self, "Medida inválida", "Preencha a altura e a largura novas com números maiores que zero (em mm).")
            return
        try:
            copies_per_row = int(self.copies_per_row_entry.get().strip())
            if copies_per_row <= 0:
                raise ValueError
        except ValueError:
            gui_theme.show_message(
                self, "Quantidade inválida", "Preencha \"Cópias por linha\" com um número inteiro maior que zero.")
            return

        profiles = db.get_all_profiles()
        if not profiles:
            gui_theme.show_message(
                self, "Sem perfis", "Cadastre um perfil de produção primeiro (aba Perfis de Produção).")
            return
        default_row = db.get_default_profile()
        default_id = default_row[0] if default_row else profiles[0][0]
        choices = [(f"{name} ({width_mm}mm x {height_mm}mm)", pid) for pid, name, width_mm, height_mm, *_ in profiles]
        default_index = next((i for i, p in enumerate(profiles) if p[0] == default_id), 0)
        profile_id = gui_theme.ask_choice(
            self.app, "Escolher perfil", "Qual perfil de produção usar?", choices, default_index)
        if profile_id is None:
            return

        catalog_name = next((row[1] for row in self._catalogs if row[0] == self._catalog_id), "producao")
        save_path = file_picker.pick_save_path(f"{catalog_name}.cdr")
        if not save_path:
            return

        self.log_panel.show("Gerando produção no CorelDRAW...\n\n")
        catalog_id = self._catalog_id
        arts = list(self._found_arts)

        def task():
            pa.do_generate_production_for_arts(
                catalog_id, arts, new_largura_mm, new_altura_mm, save_path, profile_id, copies_per_row)

        def on_success(_result):
            self.log_panel.hide_after()
            gui_theme.show_message(self, "Produção gerada", f"Arquivo salvo em:\n{save_path}")

        def on_error(ex):
            gui_theme.show_message(self, "Erro ao gerar", str(ex))

        gui_worker.run_task(
            self.app, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)
