"""Representantes page: cadastra os representantes que aparecem no seletor
obrigatório do pedido no site (index.html) e fazem login no painel deles
(painel.html, só o pedido de cada um). Toda a lista/CRUD é remota -- não tem
tabela local, o site (MySQL) é a fonte da verdade porque é lá que o login é
validado (ver representante_login.php).
"""
import customtkinter as ctk

import gui_theme
import gui_worker
import website_sync


class RepresentanteDialog(ctk.CTkToplevel):
    """Formulário de criar/editar representante -- mesmo padrão visual do
    TextInputDialog em gui_theme.py, só que com mais de um campo."""

    def __init__(self, master, title, representante=None):
        super().__init__(master)
        self.title(title)
        is_edit = representante is not None
        height = 400 if is_edit else 360
        gui_theme.center_over_master(self, master, 360, height)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.result = None

        ctk.CTkLabel(self, text="Nome", font=ctk.CTkFont(size=12), text_color="gray50").pack(
            padx=24, pady=(20, 0), anchor="w")
        self.nome_entry = ctk.CTkEntry(self, placeholder_text="ex: João Silva")
        self.nome_entry.pack(padx=24, pady=(2, 10), fill="x")

        ctk.CTkLabel(self, text="Usuário (login)", font=ctk.CTkFont(size=12), text_color="gray50").pack(
            padx=24, pady=(0, 0), anchor="w")
        self.usuario_entry = ctk.CTkEntry(self, placeholder_text="ex: joao.silva")
        self.usuario_entry.pack(padx=24, pady=(2, 10), fill="x")

        ctk.CTkLabel(self, text="Região", font=ctk.CTkFont(size=12), text_color="gray50").pack(
            padx=24, pady=(0, 0), anchor="w")
        self.regiao_entry = ctk.CTkEntry(self, placeholder_text="ex: Sul, Norte, SP Capital")
        self.regiao_entry.pack(padx=24, pady=(2, 10), fill="x")

        senha_label = "Nova senha (deixe em branco pra manter a atual)" if is_edit else "Senha"
        ctk.CTkLabel(self, text=senha_label, font=ctk.CTkFont(size=12), text_color="gray50").pack(
            padx=24, pady=(0, 0), anchor="w")
        self.senha_entry = ctk.CTkEntry(self, placeholder_text="mínimo 4 caracteres", show="•")
        self.senha_entry.pack(padx=24, pady=(2, 10), fill="x")

        self.ativo_var = ctk.BooleanVar(value=True)
        if is_edit:
            self.nome_entry.insert(0, representante["nome"])
            self.usuario_entry.insert(0, representante["usuario"])
            self.regiao_entry.insert(0, representante.get("regiao") or "")
            self.ativo_var.set(bool(representante["ativo"]))
            ctk.CTkCheckBox(self, text="Ativo (aparece no seletor do site)", variable=self.ativo_var).pack(
                padx=24, pady=(0, 10), anchor="w")

        self.erro_label = ctk.CTkLabel(self, text="", text_color="#c0392b", font=ctk.CTkFont(size=12))
        self.erro_label.pack(padx=24, anchor="w")

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=(6, 20))
        ctk.CTkButton(button_row, text="Cancelar", fg_color="gray40", hover_color="gray30",
                      width=110, command=self._cancel).pack(side="left", padx=8)
        gui_theme.primary_button(button_row, text="Salvar", width=110, command=self._confirm).pack(
            side="left", padx=8)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())
        self.nome_entry.focus()

    def _confirm(self):
        nome = self.nome_entry.get().strip()
        usuario = self.usuario_entry.get().strip()
        regiao = self.regiao_entry.get().strip()
        senha = self.senha_entry.get()
        if not nome or not usuario:
            self.erro_label.configure(text="Nome e usuário são obrigatórios.")
            return
        if senha and len(senha) < 4:
            self.erro_label.configure(text="Senha muito curta (mínimo 4 caracteres).")
            return
        self.result = {"nome": nome, "usuario": usuario, "regiao": regiao, "senha": senha, "ativo": self.ativo_var.get()}
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class RepresentantesPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 8))
        header.grid_columnconfigure(0, weight=1)
        gui_theme.back_button(header, self.app).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        gui_theme.section_title(header, "Representantes").grid(row=1, column=0, sticky="w")

        button_row = ctk.CTkFrame(header, fg_color="transparent")
        button_row.grid(row=1, column=1, sticky="e")
        gui_theme.card_button(
            button_row, "+", "Novo", self._create,
            color=gui_theme.ACCENT, hover_color=gui_theme.ACCENT_HOVER, width=100, height=70,
        ).pack(side="left", padx=4)
        gui_theme.card_button(
            button_row, "🔄", "Atualizar", self.refresh,
            color="gray45", hover_color="gray35", width=100, height=70,
        ).pack(side="left", padx=4)

        self.status_label = ctk.CTkLabel(
            self, text="Aparecem, nessa ordem, no seletor obrigatório do pedido no site.",
            font=ctk.CTkFont(size=12), text_color="gray60", anchor="w")
        self.status_label.grid(row=1, column=0, sticky="ew", padx=28)

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.list_frame.grid(row=2, column=0, sticky="nsew", padx=24, pady=(8, 8))
        self.list_frame.grid_columnconfigure(0, weight=1)

        self.log_panel = gui_worker.LogPanel(self)
        self.log_panel.grid(row=3, column=0, sticky="sew", padx=24, pady=(0, 20))

    def on_show(self):
        self.refresh()

    def refresh(self):
        for child in self.list_frame.winfo_children():
            child.destroy()

        def task():
            return website_sync.list_representantes()

        def on_success(representantes):
            self._render(representantes)

        def on_error(ex):
            ctk.CTkLabel(
                self.list_frame, text=f"Erro ao carregar representantes: {ex}", text_color="#c0392b",
            ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(self.list_frame, text="Carregando...", text_color="gray60").grid(row=0, column=0, sticky="w")
        gui_worker.run_task(self.app, task, on_success=on_success, on_error=on_error)

    def _render(self, representantes):
        for child in self.list_frame.winfo_children():
            child.destroy()

        if not representantes:
            ctk.CTkLabel(
                self.list_frame, text="Nenhum representante cadastrado ainda.", text_color="gray60",
            ).grid(row=0, column=0, sticky="w")
            return

        for i, rep in enumerate(representantes):
            row = ctk.CTkFrame(
                self.list_frame, corner_radius=10, fg_color=("gray92", "gray17"),
                border_width=2, border_color=gui_theme.ACCENT if rep["ativo"] else "gray50")
            row.grid(row=i, column=0, sticky="ew", pady=(0 if i == 0 else 10, 0), padx=2)
            row.grid_columnconfigure(0, weight=1)

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.grid(row=0, column=0, sticky="w", padx=16, pady=12)
            status_texto = "Ativo" if rep["ativo"] else "Inativo"
            ctk.CTkLabel(
                info, text=f"{rep['nome']}  ·  {status_texto}",
                font=ctk.CTkFont(size=14, weight="bold"),
            ).pack(anchor="w")
            regiao_txt = f"  ·  {rep['regiao']}" if rep.get("regiao") else ""
            ctk.CTkLabel(
                info, text=f"usuário: {rep['usuario']}{regiao_txt}  ·  cadastrado em {rep['criado_em']}",
                font=ctk.CTkFont(size=12), text_color="gray50",
            ).pack(anchor="w")

            actions = ctk.CTkFrame(row, fg_color="transparent")
            actions.grid(row=0, column=1, sticky="e", padx=16, pady=12)
            gui_theme.secondary_button(
                actions, text="Editar", width=90, height=30,
                command=lambda r=rep: self._edit(r),
            ).pack(side="left", padx=4)
            if rep["ativo"]:
                gui_theme.danger_button(
                    actions, text="Desativar", width=100, height=30,
                    command=lambda r=rep: self._deactivate(r),
                ).pack(side="left", padx=4)

    def _create(self):
        dialog = RepresentanteDialog(self.app, "Novo representante")
        self.app.wait_window(dialog)
        if not dialog.result:
            return
        data = dialog.result
        if not data["senha"]:
            gui_theme.show_message(self.app, "Senha obrigatória", "Informe uma senha pro novo representante.")
            return

        self.log_panel.show("Cadastrando representante...\n\n")

        def task():
            website_sync.criar_representante(data["nome"], data["usuario"], data["senha"], data["regiao"])

        def on_success(_result):
            self.log_panel.hide_after()
            self.refresh()

        def on_error(ex):
            gui_theme.show_message(self.app, "Erro ao cadastrar", str(ex))

        gui_worker.run_task(self.app, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)

    def _edit(self, rep):
        dialog = RepresentanteDialog(self.app, "Editar representante", representante=rep)
        self.app.wait_window(dialog)
        if not dialog.result:
            return
        data = dialog.result

        self.log_panel.show("Salvando alterações...\n\n")

        def task():
            website_sync.editar_representante(
                rep["id"], data["nome"], data["usuario"], data["ativo"], data["regiao"], data["senha"] or None)

        def on_success(_result):
            self.log_panel.hide_after()
            self.refresh()

        def on_error(ex):
            gui_theme.show_message(self.app, "Erro ao salvar", str(ex))

        gui_worker.run_task(self.app, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)

    def _deactivate(self, rep):
        if not gui_theme.ask_confirm(
            self.app, "Desativar representante",
            f'Tem certeza que quer desativar "{rep["nome"]}"?\n\n'
            f'Ele some do seletor do site e não consegue mais entrar no painel dele, mas os pedidos '
            f'já feitos continuam intactos.',
            confirm_text="Desativar", danger=True,
        ):
            return

        self.log_panel.show("Desativando...\n\n")

        def task():
            website_sync.excluir_representante(rep["id"])

        def on_success(_result):
            self.log_panel.hide_after()
            self.refresh()

        def on_error(ex):
            gui_theme.show_message(self.app, "Erro ao desativar", str(ex))

        gui_worker.run_task(self.app, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)
