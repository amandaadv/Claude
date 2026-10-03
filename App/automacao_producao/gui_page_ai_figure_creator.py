"""Criar Figura (IA) page: describe a figure in plain Portuguese, get a
whole BATCH of different drafts back in one shot (fast -- one API call
with n=count, not one call per draft), then clean up (remove background)
only whichever ones actually look good enough to keep. See
figure_generator.py for why generation and cleanup are two separate,
on-demand steps instead of one automatic pipeline -- doing that
automatically for every draft was the whole reason this used to feel slow.
"""
import io
import os

import customtkinter as ctk
from PIL import Image

import figure_generator
import file_picker
import gui_theme
import gui_worker

THUMB_PX = 160


def _fit_image(pil_image: Image.Image, box_px: int) -> ctk.CTkImage:
    image = pil_image.convert("RGBA")
    scale = min(box_px / image.width, box_px / image.height, 1.0)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return ctk.CTkImage(light_image=image, dark_image=image, size=size)


class AiFigureCreatorPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        # index -> {"raw": bytes, "cleaned": bytes | None}
        self._drafts: dict[int, dict] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Criar Figura (IA)").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Descreve em português o tema/estilo (ex: \"ursinho fofo com balão rosa, aquarela\") -- gera "
                 "um LOTE de modelos diferentes nesse mesmo estilo, todos de uma vez. O fundo NÃO sai "
                 "transparente automaticamente (confirmado: essa parte da IA não obedece isso de forma "
                 "confiável) -- clica em \"Limpar fundo\" só na(s) que você realmente quiser aproveitar, "
                 "pra não esperar isso em todas.",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=860, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        input_row = ctk.CTkFrame(self, fg_color="transparent")
        input_row.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 12))
        input_row.grid_columnconfigure(0, weight=1)
        self.description_entry = ctk.CTkEntry(
            input_row, placeholder_text="Descreva o tema/estilo da figura (em português)...", height=38)
        self.description_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.description_entry.bind("<Return>", lambda _e: self._generate_batch())
        ctk.CTkLabel(input_row, text="Quantas:", font=ctk.CTkFont(size=12)).grid(row=0, column=1, padx=(0, 6))
        self.count_entry = ctk.CTkEntry(input_row, width=50, height=38)
        self.count_entry.insert(0, "10")
        self.count_entry.grid(row=0, column=2, padx=(0, 10))
        self.generate_button = gui_theme.primary_button(
            input_row, text="Gerar lote", width=130, height=38, command=self._generate_batch)
        self.generate_button.grid(row=0, column=3)

        self.status_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12), text_color="gray60")
        self.status_label.grid(row=1, column=0, sticky="w", padx=28, pady=(40, 0))

        self.results_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.results_frame.grid(row=2, column=0, sticky="nsew", padx=28, pady=(4, 8))
        for col in range(5):
            self.results_frame.grid_columnconfigure(col, weight=1)

        self.log_panel = gui_worker.LogPanel(self)
        self.log_panel.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 20))

    def on_show(self):
        pass

    def _generate_batch(self):
        description = self.description_entry.get().strip()
        if not description:
            gui_theme.show_message(self, "Descreva a figura", "Escreve o tema/estilo antes de gerar.")
            return
        try:
            count = int(self.count_entry.get().strip())
            if not (1 <= count <= 10):
                raise ValueError
        except ValueError:
            gui_theme.show_message(self, "Quantidade inválida", "Informe um número de 1 a 10.")
            return

        for child in self.results_frame.winfo_children():
            child.destroy()
        self._drafts = {}
        self.generate_button.configure(state="disabled")
        self.status_label.configure(text=f"Gerando {count} modelo(s) (uma chamada só, pode levar meio minuto)...")
        self.log_panel.show("Chamando a IA...\n\n")

        def task():
            return figure_generator.generate_batch(description, count)

        def on_success(raw_list):
            self.generate_button.configure(state="normal")
            self.status_label.configure(text=f"{len(raw_list)} modelo(s) gerado(s). Escolha o que quiser limpar/salvar.")
            self.log_panel.hide_after()
            self._build_grid(raw_list)

        def on_error(ex):
            self.generate_button.configure(state="normal")
            self.status_label.configure(text="Falhou.")
            gui_theme.show_message(self, "Erro ao gerar", str(ex))

        gui_worker.run_task(self.app, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)

    def _build_grid(self, raw_list):
        for i, raw_bytes in enumerate(raw_list):
            self._drafts[i] = {"raw": raw_bytes, "cleaned": None}
            card = ctk.CTkFrame(self.results_frame, corner_radius=10, fg_color=("gray92", "gray17"))
            card.grid(row=i // 5, column=i % 5, sticky="new", padx=6, pady=6)

            image_container = ctk.CTkFrame(card, fg_color="gray50", width=THUMB_PX, height=THUMB_PX)
            image_container.pack(padx=10, pady=(10, 6))
            image_container.grid_propagate(False)
            self._render_thumb(image_container, raw_bytes)

            status_label = ctk.CTkLabel(card, text="bruta", font=ctk.CTkFont(size=10), text_color="gray50")
            status_label.pack(pady=(0, 4))

            clean_button = gui_theme.secondary_button(
                card, text="Limpar fundo", width=130, height=26, font=ctk.CTkFont(size=10),
                command=lambda idx=i, container=image_container, lbl=status_label:
                    self._clean_one(idx, container, lbl),
            )
            clean_button.pack(padx=10, pady=(0, 4))
            save_button = gui_theme.secondary_button(
                card, text="Salvar", width=130, height=26, font=ctk.CTkFont(size=10),
                command=lambda idx=i: self._save_one(idx),
            )
            save_button.pack(padx=10, pady=(0, 10))

    @staticmethod
    def _render_thumb(container, image_bytes):
        for child in container.winfo_children():
            child.destroy()
        image = Image.open(io.BytesIO(image_bytes))
        ctk_image = _fit_image(image, THUMB_PX)
        label = ctk.CTkLabel(container, image=ctk_image, text="")
        label.image = ctk_image  # mantém referência viva
        label.place(relx=0.5, rely=0.5, anchor="center")

    def _clean_one(self, idx, container, status_label):
        draft = self._drafts[idx]
        status_label.configure(text="limpando...")

        def task():
            return figure_generator.clean_figure(draft["raw"])

        def on_success(cleaned_bytes):
            draft["cleaned"] = cleaned_bytes
            self._render_thumb(container, cleaned_bytes)
            status_label.configure(text="sem fundo")

        def on_error(ex):
            status_label.configure(text="falhou")
            gui_theme.show_message(self, "Erro ao limpar fundo", str(ex))

        gui_worker.run_task(self.app, task, on_success=on_success, on_error=on_error)

    def _save_one(self, idx):
        draft = self._drafts[idx]
        image_bytes = draft["cleaned"] or draft["raw"]
        default_name = f"figura_ia_{idx + 1}.png"
        save_path = file_picker.pick_save_path_png(default_name)
        if not save_path:
            return
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        self.status_label.configure(text=f"Salvo em: {os.path.basename(save_path)}")
