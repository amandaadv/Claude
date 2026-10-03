"""Corrigir Tamanho: acha peças fora da medida certa no documento ABERTO e ATIVO no CorelDRAW
(qualquer página) e ajusta cada uma pro tamanho mais próximo de uma lista de medidas cadastradas
aqui -- pra quando a produção saiu com alguma peça na medida errada e não vale a pena gerar tudo
de novo, só corrigir o que está torto direto no arquivo já aberto."""
import customtkinter as ctk

import gui_theme
import gui_worker
import pa


class FixShapeSizesPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._size_rows: list[dict] = []

        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Corrigir Tamanho").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Confere TODAS as páginas do documento que está aberto e ativo agora no CorelDRAW. "
                 "Cada peça é comparada com as medidas cadastradas abaixo (pelo lado mais comprido dela, "
                 "não importa se está deitada ou em pé) e, se estiver fora da medida certa, é ajustada "
                 "pra ficar exata -- sem mudar a posição dela na folha. Peça que já está certa não é "
                 "mexida.",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=860, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        form = ctk.CTkFrame(self, fg_color=("gray92", "gray17"), corner_radius=10)
        form.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 8))

        ctk.CTkLabel(
            form, text="Medidas certas (comprido x curto, em mm):",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(16, 6))

        self.rows_frame = ctk.CTkFrame(form, fg_color="transparent")
        self.rows_frame.pack(anchor="w", fill="x", padx=16)

        gui_theme.secondary_button(
            form, text="+ Adicionar outra medida", width=190, height=30, command=self._add_row,
        ).pack(anchor="w", padx=16, pady=(6, 8))

        tol_row = ctk.CTkFrame(form, fg_color="transparent")
        tol_row.pack(anchor="w", padx=16, pady=(0, 16))
        ctk.CTkLabel(tol_row, text="Tolerância (mm) -- diferença abaixo disso é ignorada:",
                     font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 8))
        self.tolerance_entry = ctk.CTkEntry(tol_row, width=80)
        self.tolerance_entry.insert(0, "1.0")
        self.tolerance_entry.pack(side="left")

        # Já vem com as duas medidas de faixa mais usadas -- edite/apague se for outro caso.
        self._add_row(488.0, 111.0)
        self._add_row(290.0, 111.0)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 8))
        gui_theme.primary_button(
            footer, text="Corrigir agora", width=200, height=36, command=self._fix,
        ).pack(side="left")
        self.status_label = ctk.CTkLabel(footer, text="", font=ctk.CTkFont(size=12), text_color="gray60")
        self.status_label.pack(side="left", padx=(16, 0))

        self.log_panel = gui_worker.LogPanel(self)
        self.log_panel.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 20))

    def on_show(self):
        pass

    def _add_row(self, long_mm: float | None = None, short_mm: float | None = None):
        row = ctk.CTkFrame(self.rows_frame, fg_color="transparent")
        row.pack(anchor="w", pady=3)

        long_entry = ctk.CTkEntry(row, width=90, placeholder_text="comprido")
        if long_mm is not None:
            long_entry.insert(0, f"{long_mm:g}")
        long_entry.pack(side="left")

        ctk.CTkLabel(row, text="x", font=ctk.CTkFont(size=13)).pack(side="left", padx=6)

        short_entry = ctk.CTkEntry(row, width=90, placeholder_text="curto")
        if short_mm is not None:
            short_entry.insert(0, f"{short_mm:g}")
        short_entry.pack(side="left")

        entry_dict = {"frame": row, "long": long_entry, "short": short_entry}

        remove_button = gui_theme.danger_button(
            row, text="Remover", width=80, height=28,
            command=lambda: self._remove_row(entry_dict),
        )
        remove_button.pack(side="left", padx=(10, 0))

        self._size_rows.append(entry_dict)

    def _remove_row(self, entry_dict: dict):
        entry_dict["frame"].destroy()
        self._size_rows.remove(entry_dict)

    def _read_sizes(self) -> list[tuple[float, float]] | None:
        sizes = []
        for entry_dict in self._size_rows:
            long_text = entry_dict["long"].get().strip().replace(",", ".")
            short_text = entry_dict["short"].get().strip().replace(",", ".")
            if not long_text and not short_text:
                continue
            try:
                long_mm = float(long_text)
                short_mm = float(short_text)
                if long_mm <= 0 or short_mm <= 0:
                    raise ValueError
            except ValueError:
                gui_theme.show_message(
                    self, "Medida inválida", "Cada medida precisa dos dois números (comprido e curto), maiores que 0.")
                return None
            sizes.append((long_mm, short_mm))
        if not sizes:
            gui_theme.show_message(self, "Sem medidas", "Cadastre pelo menos uma medida certa.")
            return None
        return sizes

    def _fix(self):
        sizes = self._read_sizes()
        if sizes is None:
            return
        try:
            tolerance_mm = float(self.tolerance_entry.get().strip().replace(",", "."))
            if tolerance_mm < 0:
                raise ValueError
        except ValueError:
            gui_theme.show_message(self, "Valor inválido", "A tolerância precisa ser 0 ou maior (em mm).")
            return

        sizes_text = ", ".join(f"{long_mm:g}x{short_mm:g}mm" for long_mm, short_mm in sizes)
        if not gui_theme.ask_confirm(
            self, "Corrigir tamanho",
            f"Vou conferir TODAS as páginas do documento aberto no CorelDRAW e ajustar toda peça que "
            f"não estiver em uma dessas medidas (tolerância {tolerance_mm:g}mm): {sizes_text}. Continuar?",
            confirm_text="Corrigir",
        ):
            return

        self.status_label.configure(text="Corrigindo...")
        self.log_panel.show("Conferindo peças no CorelDRAW...\n\n")

        def task():
            return pa.do_fix_shape_sizes_in_active_document(sizes, tolerance_mm)

        def on_success(result):
            fixed_count, already_ok_count = result
            self.status_label.configure(text=f"{fixed_count} corrigida(s), {already_ok_count} já certa(s).")
            self.log_panel.hide_after()
            gui_theme.show_message(
                self, "Correção concluída",
                f"{fixed_count} peça(s) corrigida(s).\n{already_ok_count} já estavam na medida certa.")

        def on_error(ex):
            self.status_label.configure(text="Falhou.")
            gui_theme.show_message(self, "Erro ao corrigir", str(ex))

        gui_worker.run_task(self.app, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)
