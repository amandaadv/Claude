"""Catálogo Personalizado: manage private (reserved) catalogs and generate
personalized links for individual clients.

Private catalogs are separate from the public site listing -- they live in
the same local database but with is_private=1, so they never appear on the
Catálogos page or in the public showcase order. To make a personalized link
the catalog still has to be published to the site (so PHP can serve its
images), but it's marked privado=true in the publish payload so the PHP
backend can hide it from the public listing (requires PHP support for that
flag -- the catalog IS uploaded either way).

Workflow:
  1. "Reservar catálogo existente" -- picks a catalog from the public list
     and marks it is_private=1 (it vanishes from the Catálogos page).
  2. Check one or more reserved catalogs.
  3. Type the client's name.
  4. "Gerar Link" -- publishes any unpublished private catalogs, then calls
     criar_catalogo_personalizado.php and returns a ?c=<codigo> link.

Each "Gerar Link" call creates a FRESH unique code. If you add a new catalog
later and click Gerar Link again, send the NEW link to the client -- the old
one still points to the old set of catalogs.
"""
import customtkinter as ctk

import db
import gui_theme
import gui_worker
import pa


class PersonalizedCatalogPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._private_catalogs: list[tuple] = []
        # {catalog_id: BooleanVar} -- one checkbox per private catalog
        self._check_vars: dict[int, ctk.BooleanVar] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Header ───────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Catálogo Personalizado").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Marque um ou mais catálogos reservados, informe o nome do cliente e clique em "
                 "\"Gerar Link\" -- cada geração cria um link novo. Se adicionar mais catálogos "
                 "depois, gere de novo e mande o link novo pro cliente.",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=860, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        # ── Scrollable body ───────────────────────────────────────────────────
        body = ctk.CTkScrollableFrame(self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 4))
        body._scrollbar.grid_remove()
        body.grid_columnconfigure(0, weight=1)
        self._body = body

        # ── Private catalog list (with checkboxes) ────────────────────────────
        list_section = ctk.CTkFrame(body, fg_color=("gray92", "gray17"), corner_radius=10)
        list_section.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 6))
        list_section.grid_columnconfigure(0, weight=1)

        list_header = ctk.CTkFrame(list_section, fg_color="transparent")
        list_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        list_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            list_header, text="Catálogos reservados",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        gui_theme.secondary_button(
            list_header, text="+ Reservar catálogo existente", width=220, height=30,
            command=self._reserve_catalog,
        ).grid(row=0, column=1, sticky="e")

        self.private_list_frame = ctk.CTkFrame(list_section, fg_color="transparent")
        self.private_list_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))

        # ── Generate link form ────────────────────────────────────────────────
        form = ctk.CTkFrame(body, fg_color=("gray92", "gray17"), corner_radius=10)
        form.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))

        client_row = ctk.CTkFrame(form, fg_color="transparent")
        client_row.pack(anchor="w", padx=16, pady=16)
        ctk.CTkLabel(client_row, text="Nome do cliente:", font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 8))
        self.client_entry = ctk.CTkEntry(client_row, width=260, placeholder_text="ex: Ana Lucia")
        self.client_entry.pack(side="left")

        footer_row = ctk.CTkFrame(body, fg_color="transparent")
        footer_row.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))
        gui_theme.primary_button(
            footer_row, text="Gerar Link", width=180, height=36, command=self._generate,
        ).pack(side="left")

        # ── Result ────────────────────────────────────────────────────────────
        self.result_frame = ctk.CTkFrame(body, fg_color=("gray92", "gray17"), corner_radius=10)
        self.result_frame.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 6))
        self.result_frame.grid_remove()

        result_inner = ctk.CTkFrame(self.result_frame, fg_color="transparent")
        result_inner.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            result_inner,
            text="Link gerado  ·  mande ESSE link pro cliente (o link antigo continua apontando pro catálogo anterior):",
            font=ctk.CTkFont(size=11), text_color="gray55",
        ).pack(anchor="w", pady=(0, 6))
        link_row = ctk.CTkFrame(result_inner, fg_color="transparent")
        link_row.pack(fill="x")
        self.result_entry = ctk.CTkEntry(link_row, width=460)
        self.result_entry.pack(side="left", padx=(0, 8))
        gui_theme.secondary_button(
            link_row, text="Copiar", width=100, height=32, command=self._copy_link,
        ).pack(side="left")
        ctk.CTkLabel(
            self.result_frame, text="",
            font=ctk.CTkFont(size=11), text_color="gray55",
        ).pack(anchor="w", padx=16, pady=(0, 12))

        self.log_panel = gui_worker.LogPanel(self)
        self.log_panel.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 20))

    def on_show(self):
        self._reload_private_list()

    # ── private catalog list ──────────────────────────────────────────────────

    def _reload_private_list(self):
        self._private_catalogs = db.get_all_private_catalogs()
        self._check_vars = {}

        for child in self.private_list_frame.winfo_children():
            child.destroy()

        if not self._private_catalogs:
            ctk.CTkLabel(
                self.private_list_frame,
                text="Nenhum catálogo reservado ainda. Clique em \"Reservar catálogo existente\" acima.",
                font=ctk.CTkFont(size=12), text_color="gray55",
            ).pack(anchor="w", pady=8)
            return

        for catalog_id, name, status, _created_at, _total, approved_arts, _ref, _pub in self._private_catalogs:
            var = ctk.BooleanVar(value=False)
            self._check_vars[catalog_id] = var

            row = ctk.CTkFrame(self.private_list_frame, fg_color=("gray85", "gray22"), corner_radius=8)
            row.pack(fill="x", pady=2)
            row.grid_columnconfigure(1, weight=1)

            ctk.CTkCheckBox(
                row, variable=var, text="",
                width=24, height=24, checkbox_width=20, checkbox_height=20,
            ).grid(row=0, column=0, padx=(10, 4), pady=8)

            ctk.CTkLabel(
                row, text=f"🔒 {name}",
                font=ctk.CTkFont(size=12, weight="bold"), anchor="w",
            ).grid(row=0, column=1, sticky="w", padx=(0, 6))

            ctk.CTkLabel(
                row,
                text=f"{approved_arts or 0} REF(s)  ·  {status}",
                font=ctk.CTkFont(size=11), text_color="gray55",
            ).grid(row=0, column=2, padx=8)

            gui_theme.secondary_button(
                row, text="Tornar público", width=120, height=26,
                command=lambda cid=catalog_id: self._make_public(cid),
            ).grid(row=0, column=3, padx=(0, 10), pady=6)

    def _reserve_catalog(self):
        public_catalogs = db.get_all_public_catalogs()
        if not public_catalogs:
            gui_theme.show_message(self, "Sem catálogos", "Não há catálogos públicos disponíveis pra reservar.")
            return

        choices = [
            (f"{name}  ({approved_arts or 0} REF(s) aprovada(s))", cid)
            for cid, name, _s, _c, _t, approved_arts, _r, _p in public_catalogs
        ]
        chosen_id = gui_theme.ask_choice(
            self, "Reservar catálogo",
            "Escolha o catálogo que vai ficar reservado (só acessível via link personalizado, "
            "não aparece mais na lista pública do site):",
            choices, 0,
        )
        if chosen_id is None:
            return

        chosen_name = next(name for cid, name, *_ in public_catalogs if cid == chosen_id)
        if not gui_theme.ask_confirm(
            self, "Confirmar",
            f'"{chosen_name}" vai sair da listagem pública e ficar disponível só aqui, '
            f"pra gerar links personalizados. Pode desfazer depois com \"Tornar público\". Continuar?",
            confirm_text="Reservar",
        ):
            return

        db.set_catalog_private(chosen_id, True)
        self._reload_private_list()

    def _make_public(self, catalog_id):
        row = next((r for r in self._private_catalogs if r[0] == catalog_id), None)
        name = row[1] if row else f"id={catalog_id}"
        if not gui_theme.ask_confirm(
            self, "Tornar público",
            f'"{name}" vai voltar pra listagem pública do site. Continuar?',
            confirm_text="Tornar público",
        ):
            return
        db.set_catalog_private(catalog_id, False)
        self._reload_private_list()

    # ── generate link ─────────────────────────────────────────────────────────

    def _copy_link(self):
        link = self.result_entry.get()
        if not link:
            return
        self.clipboard_clear()
        self.clipboard_append(link)

    def _generate(self):
        selected_ids = [cid for cid, var in self._check_vars.items() if var.get()]
        if not selected_ids:
            gui_theme.show_message(self, "Nenhum catálogo", "Marque pelo menos um catálogo acima.")
            return
        client_name = self.client_entry.get().strip()
        if not client_name:
            gui_theme.show_message(self, "Falta o nome", "Digite o nome do cliente.")
            return

        self.result_frame.grid_remove()
        self.log_panel.show("Gerando link personalizado...\n\n")

        def task():
            return pa.do_create_personalized_catalog(selected_ids, client_name)

        def on_success(link):
            self.log_panel.hide_after()
            self.result_entry.delete(0, "end")
            self.result_entry.insert(0, link)
            self.result_frame.grid()

        def on_error(ex):
            self.log_panel.hide()
            gui_theme.show_message(self, "Erro ao gerar link", str(ex))

        gui_worker.run_task(
            self.app, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)
