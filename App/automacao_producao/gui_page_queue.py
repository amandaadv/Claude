"""Fila de Produção page: shows what's queued, grouped by client so it's
obvious whose designs are whose. Each group gets its own "Gerar produção"
button. To add something to the queue, use the Buscar Produto page.
"""
import re

import customtkinter as ctk
from PIL import Image

import db
import file_picker
import gui_theme
import gui_webpedido
import gui_worker
import pa
import production


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "producao"


class QueuePage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 8))
        header.grid_columnconfigure(0, weight=1)
        gui_theme.back_button(header, self.app).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        gui_theme.section_title(header, "Fila de Produção").grid(row=1, column=0, sticky="w")

        self.status_label = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=12), text_color="gray60", anchor="w")
        self.status_label.grid(row=1, column=0, sticky="ew", padx=28)

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.list_frame.grid(row=2, column=0, sticky="nsew", padx=24, pady=(8, 8))
        self.list_frame.grid_columnconfigure(0, weight=1)

        self.log_panel = gui_worker.LogPanel(self)
        self.log_panel.grid(row=3, column=0, sticky="sew", padx=24, pady=(0, 20))

        self._images = []  # keep CTkImage references alive
        # Data loads on first on_show(), not here -- see gui_page_catalogs.py.

    def on_show(self):
        self.refresh()

    def refresh(self):
        for child in self.list_frame.winfo_children():
            child.destroy()
        self._images.clear()

        rows = db.get_pending_queue_items()
        if not rows:
            self.status_label.configure(
                text="Fila de produção vazia. Use a aba \"Buscar Produto\" pra adicionar um item.")
        else:
            self.status_label.configure(text=f"{len(rows)} item(ns) pendente(s)")

        groups = {}
        for row in rows:
            client_name, client_phone = row[8], row[9]
            order_batch_id, created_at = row[12], row[13]
            # order_batch_id separa PEDIDOS do mesmo cliente -- sem isso, um pedido novo ainda
            # pendente de produzir ficava juntado com um pedido antigo esquecido na fila (mesmo
            # nome+telefone), e "Gerar produção" pegava os dois juntos (produzia faixa que não era
            # desse pedido, ou devolvia mais peças do que as da produção que tava sendo regerada).
            # order_batch_id=None é peça de antes dessa separação existir -- continua agrupada só
            # por nome+telefone, como sempre foi.
            key = (client_name, client_phone, order_batch_id)
            if key not in groups:
                groups[key] = {"name": client_name, "phone": client_phone, "rows": [], "created_at": created_at}
            groups[key]["rows"].append(row)

        next_row = 0
        for group in groups.values():
            next_row = self._build_group(next_row, group)

        self._build_past_productions(next_row)

    def _build_past_productions(self, start_row):
        # "Gerar de novo" já bota as peças na fila (replaces_production_id aponta pra cá) -- o card some
        # da lista de "Produções anteriores" NA HORA, não só quando a nova produção termina de ser gerada.
        # Só volta a aparecer se sobrar alguma peça dela sem gerar (ver pa.do_generate_production).
        productions = [
            p for p in db.get_all_productions() if db.count_pending_items_replacing(p[0]) == 0]
        if not productions:
            return

        ctk.CTkLabel(
            self.list_frame, text="Produções anteriores", font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=start_row, column=0, sticky="w", pady=(22, 4))
        ctk.CTkLabel(
            self.list_frame,
            text="Já foram geradas no CorelDRAW e saíram da fila -- \"Gerar de novo\" bota as mesmas "
                 "peças de volta na fila pra gerar com outro perfil.",
            font=ctk.CTkFont(size=11), text_color="gray50", wraplength=700, justify="left",
        ).grid(row=start_row + 1, column=0, sticky="w", pady=(0, 8))

        production_kinds = db.get_production_kinds()

        # Agrupa por nome de cliente -- uma cliente que fez vários pedidos ao longo do tempo (ou
        # cujo pedido saiu em 2 produções por causa do split aplique/faixa) lotava a lista com um
        # card gigante por produção. "Cliente não identificado" (sem nome) nunca agrupa com outro
        # sem nome -- produções manuais/avulsas não têm por que ficar juntas só por falta de nome.
        groups: dict = {}
        order: list = []
        for p in productions:
            key = p[3] or f"__sem_nome_{p[0]}"
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(p)

        row_index = start_row + 2
        for key in order:
            client_productions = groups[key]
            if len(client_productions) == 1:
                row_index = self._build_production_card(
                    self.list_frame, row_index, client_productions[0], production_kinds)
            else:
                row_index = self._build_production_group(row_index, client_productions, production_kinds)

    def _build_production_group(self, row_index, client_productions, production_kinds):
        """Card recolhido pra várias produções do MESMO cliente -- "Ver produções" monta cada
        card individual (_build_production_card) só quando abre, mesma ideia do "Ver itens"."""
        client_name = client_productions[0][3]
        client_representative = client_productions[0][8]
        total_figuras = sum(p[9] or 0 for p in client_productions)

        header = ctk.CTkFrame(self.list_frame, corner_radius=10, fg_color=("gray92", "gray17"))
        header.grid(row=row_index, column=0, sticky="ew", pady=4, padx=2)
        header.grid_columnconfigure(0, weight=1)

        info = ctk.CTkFrame(header, fg_color="transparent")
        info.grid(row=0, column=0, sticky="w", padx=16, pady=10)
        title = f"👤 {client_name}"
        if client_representative:
            title += f"  ·  rep: {client_representative}"
        ctk.CTkLabel(info, text=title, font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w")
        pills_row = ctk.CTkFrame(info, fg_color="transparent")
        pills_row.pack(anchor="w", pady=(5, 0))
        gui_theme.pill(pills_row, f"{total_figuras} figura(s) no total", "#e3faf1", "#1e8a4c").pack(
            side="left", padx=(0, 6))
        gui_theme.pill(
            pills_row, f"{len(client_productions)} produções", "#f3ecfb", gui_theme.ACCENT_PURPLE_HOVER,
        ).pack(side="left")

        group_container = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        group_container.grid(row=row_index + 1, column=0, sticky="ew", pady=(0, 4), padx=(18, 2))
        group_container.grid_columnconfigure(0, weight=1)
        group_container.grid_remove()  # começa escondido -- só "Ver produções" monta e abre

        toggle_button = gui_theme.secondary_button(
            header, text=f"Ver produções ({len(client_productions)})", width=140, height=30,
        )
        toggle_button.grid(row=0, column=1, padx=16, pady=10)

        group_montado = False

        def _montar_grupo():
            local_row = 0
            for production in client_productions:
                local_row = self._build_production_card(group_container, local_row, production, production_kinds)

        def _toggle_group():
            nonlocal group_montado
            visible = bool(group_container.grid_info())
            if visible:
                group_container.grid_remove()
                toggle_button.configure(text=f"Ver produções ({len(client_productions)})")
            else:
                if not group_montado:
                    _montar_grupo()
                    group_montado = True
                group_container.grid()
                toggle_button.configure(text="Esconder produções")
        toggle_button.configure(command=_toggle_group)

        return row_index + 2

    def _build_production_card(self, parent, row_index, production, production_kinds):
        """Um card de uma produção já gerada, com WebPedido/Orçamento/Gerar de novo/Excluir/Ver
        itens. `parent` e `row_index` são locais a quem chama -- um card avulso usa self.list_frame
        direto, várias produções do mesmo cliente usam um container próprio (ver
        _build_production_group) -- devolve a próxima linha livre nesse `parent`."""
        (production_id, created_at, status, client_name, client_phone,
            profile_name, cdr_file_path, item_count, client_representative,
            total_figuras, catalog_count) = production

        card = ctk.CTkFrame(parent, corner_radius=10, fg_color=("gray92", "gray17"))
        card.grid(row=row_index, column=0, sticky="ew", pady=4, padx=2)
        card.grid_columnconfigure(0, weight=1)

        info = ctk.CTkFrame(card, fg_color="transparent")
        info.grid(row=0, column=0, sticky="w", padx=16, pady=10)
        title = f"👤 {client_name}" if client_name else "📦 Cliente não identificado"
        if client_representative:
            title += f"  ·  rep: {client_representative}"
        ctk.CTkLabel(info, text=title, font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w")

        # Resumo do pedido de relance -- total de figuras e quantos
        # catálogos diferentes ele mistura, em vez da contagem de linhas
        # da tabela (item_count) que não dizia nada útil pro operador.
        pills_row = ctk.CTkFrame(info, fg_color="transparent")
        pills_row.pack(anchor="w", pady=(5, 0))
        gui_theme.pill(pills_row, f"{total_figuras or 0} figura(s) no total", "#e3faf1", "#1e8a4c").pack(
            side="left", padx=(0, 6))
        gui_theme.pill(pills_row, f"{catalog_count or 0} catálogo(s)", "#e5f1fb", gui_theme.ACCENT_BLUE_HOVER).pack(
            side="left", padx=(0, 6))
        # Pedido com faixa e aplique sai em 2 produções com o mesmo nome de cliente -- a etiqueta diz qual é qual.
        kind = production_kinds.get(production_id)
        if kind == "faixa":
            gui_theme.pill(pills_row, "FAIXAS", "#fff3d6", "#8a5a00").pack(side="left")
        elif kind == "aplique":
            gui_theme.pill(pills_row, "APLIQUES", "#f3ecfb", gui_theme.ACCENT_PURPLE_HOVER).pack(side="left")

        ctk.CTkLabel(
            info,
            text=f"{created_at[:16].replace('T', ' ')}  ·  perfil: {profile_name or '?'}  ·  "
                 f"produção_id={production_id}",
            font=ctk.CTkFont(size=11), text_color="gray50",
        ).pack(anchor="w", pady=(5, 0))

        card_actions = ctk.CTkFrame(card, fg_color="transparent")
        card_actions.grid(row=0, column=1, padx=16, pady=10)
        # Só aparece quando a produção tem nome E telefone do cliente
        # (vieram do pedido do site) -- é o par que identifica a cliente
        # no link; produção manual/sem cliente não tem o que buscar.
        if client_name and client_phone:
            gui_webpedido.make_button(
                card_actions, self, client_name, client_phone, width=100, production_id=production_id,
            ).pack(side="left", padx=(0, 6))
        gui_theme.secondary_button(
            card_actions, text="Gerar Orçamento", width=140, height=30,
            command=lambda pid=production_id, cn=client_name: self._generate_budget(pid, cn),
        ).pack(side="left", padx=(0, 6))
        gui_theme.secondary_button(
            card_actions, text="Gerar de novo", width=130, height=30,
            command=lambda pid=production_id: self._requeue(pid),
        ).pack(side="left", padx=(0, 6))
        gui_theme.danger_button(
            card_actions, text="Excluir", width=90, height=30,
            command=lambda pid=production_id: self._delete_production(pid),
        ).pack(side="left", padx=(0, 6))

        items_container = ctk.CTkFrame(parent, fg_color="transparent")
        items_container.grid(row=row_index + 1, column=0, sticky="ew", pady=(0, 4), padx=2)
        items_container.grid_remove()  # começa escondido -- só "Ver itens" monta e abre

        toggle_button = gui_theme.secondary_button(
            card_actions, text=f"Ver itens ({item_count})", width=110, height=30,
        )
        toggle_button.pack(side="left")

        itens_montados = False

        def _montar_itens_producao(container=items_container, pid=production_id):
            for catalog_art_id, reference, width_mm, height_mm, medida_texto, quantity, \
                    catalog_name, preview_path in db.get_production_items_for_display(pid):
                row = ctk.CTkFrame(container, corner_radius=10, fg_color=("gray92", "gray17"))
                row.pack(fill="x", pady=4, padx=2)
                row.grid_columnconfigure(1, weight=1)

                try:
                    image = Image.open(preview_path)
                    image.thumbnail((56, 56))
                    ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
                    self._images.append(ctk_image)
                    ctk.CTkLabel(row, image=ctk_image, text="").grid(
                        row=0, column=0, rowspan=2, padx=(16, 12), pady=10)
                except Exception:
                    pass

                ctk.CTkLabel(row, text=reference or "(sem REF)", font=ctk.CTkFont(size=14, weight="bold")).grid(
                    row=0, column=1, sticky="w", padx=(0, 16), pady=(10, 0))
                medida_txt = f"  ·  {medida_texto}" if medida_texto else ""
                ctk.CTkLabel(
                    row, text=f"{catalog_name}{medida_txt}  ·  {height_mm}mm x {width_mm}mm "
                              f"(altura x largura)  ·  qtd={quantity}",
                    font=ctk.CTkFont(size=12), text_color="gray50",
                ).grid(row=1, column=1, sticky="w", padx=(0, 16), pady=(0, 10))

        def _toggle_items_producao(container=items_container, btn=toggle_button, cnt=item_count):
            nonlocal itens_montados
            visible = bool(container.grid_info())
            if visible:
                container.grid_remove()
                btn.configure(text=f"Ver itens ({cnt})")
            else:
                if not itens_montados:
                    _montar_itens_producao()
                    itens_montados = True
                container.grid()
                btn.configure(text="Esconder itens")
        toggle_button.configure(command=_toggle_items_producao)

        return row_index + 2

    def _generate_budget(self, production_id, client_name):
        default_filename = f"Orcamento {_sanitize_filename(client_name)}.xlsx" if client_name \
            else f"Orcamento producao {production_id}.xlsx"
        save_path = file_picker.pick_save_path_xlsx(default_filename)
        if not save_path:
            return

        self.log_panel.show("Gerando orçamento...\n\n")

        def task():
            return pa.do_generate_budget(production_id, save_path)

        def on_success(missing_prices):
            self.log_panel.hide_after()
            if missing_prices:
                lines = "\n".join(f"• {ref}" for ref in missing_prices)
                gui_theme.show_message(
                    self.app, "Orçamento gerado com pendências",
                    f"O arquivo foi gerado, mas {len(missing_prices)} peça(s) não têm preço cadastrado "
                    f"na Tabela de Preços (ficaram em branco no orçamento -- preencha manualmente):\n\n{lines}")
            else:
                gui_theme.show_message(self.app, "Orçamento gerado", f"Salvo em:\n{save_path}")

        gui_worker.run_task(self.app, task, on_log=self.log_panel.append, on_success=on_success)

    def _requeue(self, production_id):
        count = pa.do_requeue_production(production_id)
        if count:
            gui_theme.show_message(
                self.app, "Adicionado à fila",
                f"{count} peça(s) de volta na fila -- role pra cima pra escolher o perfil e gerar.")
        else:
            gui_theme.show_message(
                self.app, "Já está na fila",
                "Essas peças já estão na fila desse cliente -- role pra cima pra gerar. "
                "Nada foi duplicado.")
        self.refresh()

    def _delete_production(self, production_id):
        if not gui_theme.ask_confirm(
            self.app, "Excluir produção",
            f"Tem certeza que quer remover a produção {production_id} do histórico? "
            f"O arquivo .cdr já gerado não é apagado, só some dessa lista.",
            confirm_text="Excluir", danger=True,
        ):
            return
        pa.do_delete_production(production_id)
        self.refresh()

    def _build_group(self, start_row, group):
        header_frame = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        header_frame.grid(row=start_row, column=0, sticky="ew", pady=(14, 4))
        header_frame.grid_columnconfigure(0, weight=1)

        # created_at só existe pra pedido adicionado depois da separação por order_batch_id --
        # mostra na hora/data pra diferenciar quando o mesmo cliente tem mais de um pedido
        # pendente na fila ao mesmo tempo (cada um agora é um grupo/card separado).
        quando = f"  ·  {group['created_at'][:16].replace('T', ' ')}" if group.get("created_at") else ""
        if group["name"]:
            title = f"👤 {group['name']}" + (f"  ·  {group['phone']}" if group["phone"] else "") + quando
            button_text = "Gerar produção desse pedido"
        else:
            title = "📦 Adicionado manualmente" + quando
            button_text = "Gerar produção desses itens"

        ctk.CTkLabel(header_frame, text=title, font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, sticky="w")

        # Resumo do pedido de relance (total de figuras + quantos catálogos
        # diferentes) em vez de só listar as REFs uma por uma direto na
        # tela -- a lista comprida (ver items_container abaixo) fica
        # escondida atrás de "Ver itens" por padrão.
        rows = group["rows"]
        total_figuras = sum(row[10] for row in rows if row[10] is not None)
        sem_quantidade = sum(1 for row in rows if row[10] is None)
        catalogos = len({row[6] for row in rows})
        pills_row = ctk.CTkFrame(header_frame, fg_color="transparent")
        pills_row.grid(row=1, column=0, sticky="w", pady=(4, 0))
        figuras_txt = f"{total_figuras} figura(s) no total"
        if sem_quantidade:
            figuras_txt += f"  (+{sem_quantidade} sem quantidade definida)"
        gui_theme.pill(pills_row, figuras_txt, "#e3faf1", "#1e8a4c").pack(side="left", padx=(0, 6))
        gui_theme.pill(pills_row, f"{catalogos} catálogo(s)", "#e5f1fb", gui_theme.ACCENT_BLUE_HOVER).pack(
            side="left", padx=(0, 6))
        gui_theme.pill(pills_row, f"{len(rows)} REF(s)", "#f3ecfb", gui_theme.ACCENT_PURPLE_HOVER).pack(
            side="left", padx=(0, 6))
        # Peças cuja medida a cliente ESCOLHEU no site (tipo + medida) -- não é o tamanho do catálogo.
        measure_texts = db.get_queue_medida_texts([row[0] for row in rows])
        if measure_texts:
            gui_theme.pill(
                pills_row, f"{len(measure_texts)} com medida escolhida pela cliente", "#fff3d6", "#8a5a00").pack(
                side="left")

        queue_ids = [row[0] for row in rows]
        client_name = group["name"]

        header_actions = ctk.CTkFrame(header_frame, fg_color="transparent")
        header_actions.grid(row=0, column=1, rowspan=2, sticky="e")
        # Ver o pedido do jeito que a cliente mandou no site, antes de gerar produção --
        # até aqui esse botão só existia em "Produções anteriores" (depois de já ter gerado).
        if group["name"] and group["phone"]:
            gui_webpedido.make_button(
                header_actions, self, group["name"], group["phone"], width=100,
            ).pack(side="left", padx=(0, 6))
        gui_theme.secondary_button(
            header_actions, text=button_text, width=210, height=30,
            command=lambda: self._generate(queue_ids, client_name),
        ).pack(side="left", padx=(0, 6))
        gui_theme.secondary_button(
            header_actions, text="Mudar cliente", width=110, height=30,
            command=lambda: self._change_client(queue_ids, group["name"], group["phone"]),
        ).pack(side="left", padx=(0, 6))
        gui_theme.danger_button(
            header_actions, text="Excluir pedido", width=110, height=30,
            command=lambda: self._delete_group(queue_ids, group["name"]),
        ).pack(side="left", padx=(0, 6))

        items_container = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        items_container.grid(row=start_row + 2, column=0, sticky="ew", pady=(4, 0))
        items_container.grid_remove()  # começa escondido -- só a "Ver itens" monta e abre

        toggle_button = gui_theme.secondary_button(
            header_actions, text=f"Ver itens ({len(rows)})", width=110, height=30,
        )
        toggle_button.pack(side="left")

        itens_montados = False

        def _montar_itens():
            # Monta as linhas (e carrega a imagem de cada uma) só na primeira vez que a pessoa
            # clica "Ver itens" -- com centenas de peças pendentes, montar tudo de cara (mesmo
            # escondido atrás de grid_remove) travava a tela a cada refresh() da fila inteira.
            for queue_id, catalog_art_id, reference, width_mm, height_mm, original_image_path, catalog_name, \
                    preview_path, client_name, client_phone, quantity, client_representative, \
                    order_batch_id, created_at in rows:
                row = ctk.CTkFrame(items_container, corner_radius=10, fg_color=("gray92", "gray17"))
                row.pack(fill="x", pady=4, padx=2)
                row.grid_columnconfigure(1, weight=1)

                try:
                    image = Image.open(preview_path)
                    image.thumbnail((56, 56))
                    ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
                    self._images.append(ctk_image)
                    ctk.CTkLabel(row, image=ctk_image, text="").grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=10)
                except Exception:
                    pass

                ctk.CTkLabel(row, text=reference or "(sem REF)", font=ctk.CTkFont(size=14, weight="bold")).grid(
                    row=0, column=1, sticky="w", padx=(0, 16), pady=(10, 0))
                qty_txt = f"  ·  qtd={quantity}" if quantity is not None else ""
                medida_txt = f"  ·  {measure_texts[queue_id]}" if queue_id in measure_texts else ""
                ctk.CTkLabel(
                    row, text=f"{catalog_name}{medida_txt}  ·  {height_mm}mm x {width_mm}mm (altura x largura)  ·  "
                              f"fila_id={queue_id}{qty_txt}",
                    font=ctk.CTkFont(size=12), text_color="gray50",
                ).grid(row=1, column=1, sticky="w", padx=(0, 16), pady=(0, 10))

                item_actions = ctk.CTkFrame(row, fg_color="transparent")
                item_actions.grid(row=0, column=2, rowspan=2, padx=16, pady=10)
                gui_theme.danger_button(
                    item_actions, text="Excluir", width=80, height=28,
                    command=lambda qid=queue_id, ref=reference: self._delete_item(qid, ref),
                ).pack(side="left")

        def _toggle_items():
            nonlocal itens_montados
            visible = bool(items_container.grid_info())
            if visible:
                items_container.grid_remove()
                toggle_button.configure(text=f"Ver itens ({len(rows)})")
            else:
                if not itens_montados:
                    _montar_itens()
                    itens_montados = True
                items_container.grid()
                toggle_button.configure(text="Esconder itens")
        toggle_button.configure(command=_toggle_items)

        ctk.CTkFrame(self.list_frame, height=2, fg_color=gui_theme.ACCENT).grid(
            row=start_row + 1, column=0, sticky="ew", pady=(0, 8))

        return start_row + 3

    def _change_client(self, queue_ids, current_name, current_phone):
        """Move um grupo inteiro pra outro nome de cliente (ou tira um nome errado) sem precisar
        excluir e adicionar tudo de novo -- pra quando algo foi adicionado manualmente (Buscar
        Produto, sem cliente) ou com o nome errado, e devia estar junto do pedido de alguém."""
        new_name = gui_theme.ask_text(
            self.app, "Mudar cliente",
            f"Nome atual: {current_name or '(sem cliente -- adicionado manualmente)'}\n\n"
            f"Novo nome do cliente pra essas {len(queue_ids)} peça(s) (deixe em branco pra tirar o "
            f"nome e voltar pra \"Adicionado manualmente\"):",
            placeholder="ex: Elaine", default=current_name or "")
        if new_name is None:
            return
        new_name = new_name.strip() or None
        new_phone = None
        if new_name:
            new_phone = gui_theme.ask_text(
                self.app, "Telefone do cliente",
                "Telefone (Enter em branco se não tiver ou não quiser mudar):",
                placeholder="ex: 11999999999", default=current_phone or "")
            if new_phone is not None:
                new_phone = new_phone.strip() or None
        db.set_queue_items_client(queue_ids, new_name, new_phone)
        self.refresh()

    def _delete_group(self, queue_ids, client_name):
        label = client_name or "itens adicionados manualmente"
        if not gui_theme.ask_confirm(
            self.app, "Excluir pedido inteiro",
            f"Tem certeza que quer excluir TODAS as {len(queue_ids)} peça(s) de \"{label}\" da fila de "
            f"produção? Isso não pode ser desfeito.",
            confirm_text="Excluir tudo", danger=True,
        ):
            return
        pa.do_delete_queue_items(queue_ids)
        self.refresh()
        gui_theme.show_message(
            self.app, "Pedido excluído", f"{len(queue_ids)} peça(s) de \"{label}\" excluída(s) com sucesso.")

    def _delete_item(self, queue_id, reference):
        label = reference or f"item {queue_id}"
        if not gui_theme.ask_confirm(
            self.app, "Excluir item", f"Tem certeza que quer excluir \"{label}\" da fila de produção?",
            confirm_text="Excluir", danger=True,
        ):
            return
        pa.do_delete_queue_item(queue_id)
        self.refresh()
        gui_theme.show_message(self.app, "Excluído", f"\"{label}\" excluído com sucesso.")

    def _ask_orientation(self, rows, profiles, profile_id):
        """Pergunta se gira as peças 90° pra caber mais por linha (só faz sentido pra aplique --
        faixa é sempre forçada em pé sem perguntar). Devolve None/"vertical"/"horizontal", ou a
        string "cancelled" se a pessoa fechou algum diálogo sem escolher."""
        # Confere se girar alguma peça 90° faria caber MAIS cópias por linha nessa folha --
        # deitada (largura > altura) sempre cabe menos por linha do que a mesma peça em pé,
        # então um ganho só existe pra peça deitada, e "em pé" é sempre a escolha que ganha
        # (ver production.units_per_row). É só uma estimativa com o tamanho do catálogo --
        # medida escolhida pela cliente/override mudam o resultado real.
        profile_row = next((p for p in profiles if p[0] == profile_id), None)
        best_gain = None
        if profile_row is not None:
            production_profile = production.ProductionProfile(*profile_row[1:10])
            for r in rows:
                width_mm, height_mm = r[3], r[4]
                normal_units = production.units_per_row(width_mm, height_mm, production_profile, rotated=False)
                rotated_units = production.units_per_row(width_mm, height_mm, production_profile, rotated=True)
                gain = rotated_units - normal_units
                if gain > 0 and (best_gain is None or gain > best_gain[3]):
                    best_gain = (r[2] or f"id={r[1]}", normal_units, rotated_units, gain)

        # Pergunta SEMPRE, pra toda produção (não só quando o cálculo acha que compensa --
        # o operador decide, o cálculo é só uma pista a mais na mensagem quando existe).
        if best_gain is not None:
            ref_label, normal_units, rotated_units, _gain = best_gain
            rotate_message = (
                f"Girando 90° (em pé), cabem mais cópias por linha nessa folha -- ex: \"{ref_label}\" "
                f"cabe {normal_units} na orientação original e {rotated_units} em pé. Quer girar as "
                f"peças 90° pra caber mais?")
        else:
            rotate_message = (
                "Quer girar as peças 90° (em pé) pra tentar caber mais por linha nessa folha?")
        force_orientation = "vertical" if gui_theme.ask_confirm(
            self.app, "Girar as peças 90°?", rotate_message, confirm_text="Girar pra caber mais",
        ) else None

        if force_orientation is None:
            orientation_choice = gui_theme.ask_choice(
                self.app, "Orientação das peças",
                "Cada peça deve manter a orientação gravada no catálogo, ou todas devem sair forçadas "
                "numa única direção?",
                # "original" (não None) como valor -- ask_choice usa None pra
                # dizer "cancelado" (ver ChoiceDialog._cancel), então None aqui
                # seria indistinguível de ter fechado a janela sem escolher nada.
                [("Manter orientação original", "original"),
                 ("Forçar em pé (vertical)", "vertical"),
                 ("Forçar deitada (horizontal)", "horizontal")],
            )
            if orientation_choice is None:
                return "cancelled"
            force_orientation = None if orientation_choice == "original" else orientation_choice
        return force_orientation

    def _generate(self, queue_ids, client_name, kind=None):
        """kind: None (decide aqui), "aplique", "faixa" ou "misto" (pedido com os dois tipos --
        gera aplique e faixa na MESMA produção, um arquivo só, perguntando Material/Perfil/etc uma
        vez só). Faixa sai sempre EM PÉ (vertical); na parte de aplique de um pedido misto a
        pergunta de girar 90° (ver _ask_orientation) continua valendo só pra ela."""
        rows = db.get_pending_queue_items()
        if queue_ids is not None:
            wanted = set(queue_ids)
            rows = [r for r in rows if r[0] in wanted]
        if not rows:
            gui_theme.show_message(self.app, "Fila vazia", "Não há itens pra gerar.")
            return

        aplique_ids, faixa_ids = [], []
        if kind is None:
            aplique_ids, faixa_ids = pa.split_queue_ids_by_kind([r[0] for r in rows])
            kind = "misto" if (aplique_ids and faixa_ids) else ("faixa" if faixa_ids else "aplique")

        by_catalog = False
        catalog_names = {r[6] for r in rows}
        if len(catalog_names) > 1:
            # default_index=1 -- pré-selecionado em "Por catálogo": só chega
            # aqui quando o pedido já tem vários catálogos misturados, e
            # como é uma CTkComboBox (fácil clicar "Confirmar" sem trocar a
            # seleção), o padrão mais seguro é o modo que separa, não o que
            # mistura tudo igual antes dessa pergunta existir.
            mode_choice = gui_theme.ask_choice(
                self.app, "Como produzir?",
                f"Esse pedido tem peças de {len(catalog_names)} catálogos diferentes. Produzir tudo "
                "misturado numa folha só, ou separar uma página por catálogo?",
                [("Produzir automático (tudo junto)", "auto"),
                 ("Produzir por catálogo (uma página por catálogo)", "per_catalog")],
                default_index=1,
            )
            if mode_choice is None:
                return
            by_catalog = mode_choice == "per_catalog"

        profiles = db.get_all_profiles()
        if not profiles:
            gui_theme.show_message(
                self.app, "Sem perfis", "Cadastre um perfil de produção primeiro (aba Perfis de Produção).")
            return

        # Pergunta o MATERIAL (o que o operador realmente decide -- Têxtil sai numa folha de
        # 580x2000mm, UV numa de 400x2000mm, e são coisas físicas diferentes) em vez do nome do
        # perfil, que não diz nada sobre isso. Se algum perfil já está marcado com esse material
        # (aba Perfis de Produção -> Editar), usa ele direto; senão, cai de volta pra escolher por
        # nome, do jeito antigo, pra nunca travar o fluxo por falta de configuração.
        #
        # Se a cliente já escolheu o TIPO (Termocolante/Adesivo) no site pra TODAS as peças desse
        # pedido, o material já tá decidido -- não pergunta de novo (medida_texto vem como "Tipo ·
        # Medida", ver regras_medidas.php).
        medida_texts = db.get_queue_medida_texts([r[0] for r in rows])
        material_choice = None
        if len(medida_texts) == len(rows):
            tipo_para_material = {"Termocolante": "Textil", "Adesivo": "UV"}
            materiais = {tipo_para_material.get(texto.split(" · ")[0]) for texto in medida_texts.values()}
            if len(materiais) == 1 and None not in materiais:
                material_choice = materiais.pop()

        if material_choice is None:
            material_choice = gui_theme.ask_choice(
                self.app, "Material da produção",
                {"faixa": "Vai produzir essas FAIXAS em qual material?",
                 "aplique": "Vai produzir em qual material?",
                 "misto": "Esse pedido tem aplique e faixa juntos -- vai produzir TUDO em qual material? "
                          "(sai num arquivo só)"}[kind],
                [("Têxtil - Termocolante", "Textil"), ("Adesivo - UV", "UV")])
            if material_choice is None:
                return

        matching_profiles = db.get_profiles_by_material(material_choice)
        if len(matching_profiles) == 1:
            profile_id = matching_profiles[0][0]
        else:
            if matching_profiles:
                # Ambíguo -- mais de um perfil marcado com esse mesmo material, não dá pra
                # adivinhar sozinho qual dos dois usar (ver Perfis de Produção pra marcar só um,
                # se não for essa a intenção).
                nomes = ", ".join(f"\"{p[1]}\"" for p in matching_profiles)
                aviso = (f"{len(matching_profiles)} perfis estão marcados como \"{material_choice}\" "
                         f"({nomes}) -- escolha qual usar dessa vez:")
            else:
                aviso = (f"Nenhum perfil está marcado como \"{material_choice}\" ainda (configure em "
                         f"Perfis de Produção, botão Editar) -- escolha o perfil (folha) certo pela lista:")
            default_row = db.get_default_profile()
            default_id = default_row[0] if default_row else profiles[0][0]
            choices = [(f"{name} ({width_mm}mm x {height_mm}mm)", pid) for pid, name, width_mm, height_mm, *_ in profiles]
            default_index = next((i for i, p in enumerate(profiles) if p[0] == default_id), 0)
            profile_id = gui_theme.ask_choice(self.app, "Escolher perfil", aviso, choices, default_index)
            if profile_id is None:
                return

        # Peças com medida escolhida pela cliente no site (tipo + medida): o tamanho delas já
        # é a ESCOLHA da cliente, não o do catálogo.
        measure_texts = db.get_queue_medida_texts([r[0] for r in rows])
        has_customer_measure = bool(measure_texts)
        all_have_measure = has_customer_measure and len(measure_texts) == len(rows)

        override_long_side_mm = None
        if all_have_measure:
            # Todas as peças já têm medida definida (vinda do Montar Pedido ou do site) --
            # usa direto, sem perguntar.
            pass
        elif has_customer_measure:
            size_message = (
                f"{len(measure_texts)} peça(s) desse pedido têm a medida que a cliente escolheu no site. "
                "Quer usar essa medida (o certo), ou colocar TODAS as peças numa mesma medida "
                "(vale pro maior lado de cada peça, cada uma mantém sua própria proporção)?")
            size_choice = gui_theme.ask_size_override_choice(
                self.app, "Tamanho das peças", size_message, use_order_measure=True)
            if size_choice is None:
                return
            _size_mode, override_long_side_mm = size_choice
            if override_long_side_mm is not None:
                if not gui_theme.ask_confirm(
                    self.app, "Vai apagar a medida das clientes",
                    f"{len(measure_texts)} peça(s) têm a medida que a cliente escolheu no site (por exemplo "
                    f"\"{next(iter(measure_texts.values()))}\"). Mudar a medida vai colocar TODAS as peças "
                    f"em {override_long_side_mm:g} mm e ignorar o que cada cliente escolheu. Tem certeza?",
                    confirm_text="Mudar mesmo", danger=True,
                ):
                    return
        else:
            size_message = (
                "Quer usar o tamanho de cada peça gravado no catálogo, ou mudar pra uma medida específica "
                "(vale pro maior lado de cada peça, cada uma mantém sua própria proporção)?")
            size_choice = gui_theme.ask_size_override_choice(
                self.app, "Tamanho das peças", size_message, use_order_measure=False)
            if size_choice is None:
                return
            _size_mode, override_long_side_mm = size_choice

        # Se todos os itens já têm quantidade definida (vinda do Montar Pedido),
        # pula o diálogo e usa None (automático = usa a quantidade de cada item).
        all_have_quantity = all(r[10] is not None for r in rows)
        if all_have_quantity:
            copies_per_row = None
        else:
            copies_per_row_result = gui_theme.ask_copies_per_row(self.app)
            if copies_per_row_result == "cancelled":
                return
            copies_per_row = copies_per_row_result  # None = automatic, int = fixed

        # "Faixa"-style pieces (ex: 488x111mm) ficam naturalmente deitadas --
        # numa folha estreita, várias delas lado a lado podem não caber
        # direito e sobrepor. Forçar em pé gira a peça 90° e recalcula a
        # folha já contando com o formato girado (ver
        # pa.do_generate_production). Faixa é sempre EM PÉ, sem perguntar; a pergunta de girar
        # 90° só faz sentido pra aplique (num pedido misto, só considera as linhas de aplique).
        force_orientation_aplique = None
        if kind == "faixa":
            force_orientation = "vertical"
        else:
            orientation_rows = [r for r in rows if r[0] in set(aplique_ids)] if kind == "misto" else rows
            force_orientation_aplique = self._ask_orientation(orientation_rows, profiles, profile_id)
            if force_orientation_aplique == "cancelled":
                return
            force_orientation = force_orientation_aplique

        # Quando sobra espaço numa linha da folha, as peças podem ser ESTICADAS na largura (até 20%)
        # pra preencher -- é a função de sempre, então "esticar" é a opção padrão. Vale também pra peças
        # com medida escolhida pela cliente (fica um pouco mais larga que a medida pedida).
        stretch_message = (
            "Quando sobra espaço na linha da folha, as peças podem ser esticadas na largura (até 20%) pra "
            "preencher a linha. Quer esticar, ou manter a medida exata de cada peça?")
        if has_customer_measure:
            stretch_message += "\n\nAtenção: nas peças com medida escolhida pela cliente, esticar deixa a medida um pouco maior."
        width_choice = gui_theme.ask_choice(
            self.app, "Largura das peças", stretch_message,
            [("Esticar pra preencher a linha (até 20% mais larga)", "stretch"),
             ("Manter a medida exata (sem esticar)", "original")],
            default_index=0,
        )
        if width_choice is None:
            return
        keep_original_size = width_choice == "original"

        base_name = _sanitize_filename(client_name) if client_name else "producao"
        suffix = " - faixas" if kind == "faixa" else ""
        default_filename = f"{base_name}{suffix}.cdr"
        save_path = file_picker.pick_save_path(default_filename)
        if not save_path:
            return

        self.log_panel.show(f"Gerando produção {'das FAIXAS' if kind == 'faixa' else ''} no CorelDRAW...\n\n")

        def task():
            if kind == "misto":
                # Aplique e faixa juntos, um arquivo só -- cada parte com sua própria passada de
                # layout (faixa sempre em pé), desenhadas no mesmo documento (ver
                # pa.do_generate_production_mixed / production_generator.generate_unified).
                return pa.do_generate_production_mixed(
                    save_path, profile_id, aplique_ids, faixa_ids, override_long_side_mm, copies_per_row,
                    force_orientation_aplique, by_catalog=by_catalog, keep_original_size=keep_original_size)
            return pa.do_generate_production(
                save_path, profile_id, queue_ids, override_long_side_mm, copies_per_row, force_orientation,
                by_catalog=by_catalog, keep_original_size=keep_original_size)

        def on_success(result):
            self.refresh()
            result = result or {}

            if result.get("failed"):
                # Painel de log se auto-esconde sozinho (hide_after) e o texto nele não dá pra
                # selecionar/copiar -- numa falha, o erro fica numa janela que NÃO fecha sozinha
                # e tem botão "Copiar erro", pra dar pra colar em outro lugar sem precisar
                # arrastar o mouse em cima de texto desabilitado.
                self.log_panel.hide()
                erro_texto = (
                    f"{result.get('status')}\n\n"
                    f"[{result.get('error_code')}] {result.get('error_message') or '(sem detalhe)'}")
                gui_theme.show_error_message(self.app, "Produção falhou", erro_texto)
                return

            self.log_panel.hide_after()
            # Peça com problema (arte sumida, CorelDRAW recusou) não derruba o pedido inteiro --
            # o resto gerou normal, só essa(s) ficou(ram) de fora e continua(m) pendente(s) na
            # fila. Avisa claro qual REF foi, em vez de só ficar escrito no painel de log.
            skipped = result.get("skipped_pieces") or []
            if skipped:
                linhas = "\n".join(
                    f"• {ref or f'id={cat_id}'}: {motivo}" for cat_id, ref, motivo in skipped)
                gui_theme.show_message(
                    self.app, "Produção concluída, com pendências",
                    f"O resto do pedido foi gerado normal. {len(skipped)} peça(s) NÃO entraram "
                    f"nessa produção (continuam na fila pra corrigir e gerar depois):\n\n{linhas}")

        gui_worker.run_task(self.app, task, on_log=self.log_panel.append, on_success=on_success)
