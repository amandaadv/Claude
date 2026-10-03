"""Configurações page: the one setting that matters -- which CorelDRAW file
version production sheets get saved as, for compatibility with older machines.
"""
import customtkinter as ctk

import gui_theme
import pa


class SettingsPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(28, 20))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Configurações").pack(anchor="w")

        card = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray92", "gray17"))
        card.pack(fill="x", padx=28, pady=8)

        ctk.CTkLabel(card, text="Versão do CorelDRAW de destino", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=20, pady=(16, 4))
        ctk.CTkLabel(
            card,
            text="Os arquivos de produção são salvos nessa versão, para abrir sem erro em qualquer computador "
                 "que use uma versão igual ou mais nova do CorelDRAW. Use a versão mais ANTIGA do CorelDRAW que "
                 "alguém realmente precisa abrir esse arquivo.\n"
                 "Exemplos: 2021=23, 2020=22, 2019=21, 2018=20, 2017=19 (confira em Ajuda > Sobre).",
            font=ctk.CTkFont(size=12), text_color="gray50", wraplength=560, justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 12))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(anchor="w", padx=20, pady=(0, 20))
        self.version_entry = ctk.CTkEntry(row, width=100)
        self.version_entry.insert(0, str(pa.get_target_corel_version()))
        self.version_entry.pack(side="left", padx=(0, 12))
        gui_theme.primary_button(row, text="Salvar", width=100, command=self._save).pack(side="left")
        self.status_label = ctk.CTkLabel(row, text="", font=ctk.CTkFont(size=12))
        self.status_label.pack(side="left", padx=12)

    def on_show(self):
        self.version_entry.delete(0, "end")
        self.version_entry.insert(0, str(pa.get_target_corel_version()))
        self.status_label.configure(text="")

    def _save(self):
        try:
            version = int(self.version_entry.get().strip())
        except ValueError:
            self.status_label.configure(text="Número inválido.", text_color=gui_theme.DANGER)
            return
        pa.set_target_corel_version(version)
        self.status_label.configure(text="Salvo.", text_color=gui_theme.ACCENT_BLUE)
