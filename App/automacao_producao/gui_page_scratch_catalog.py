"""Criar Catálogo do Zero page: builds a brand-new catalog straight from
loose figure files -- no master .cdr, no REF captions to read. For a batch
of AI-generated figures (Criar Figura + Separador de Figuras) that never
went through a real catalog. Guided as a wizard (pick figures -> name ->
sizing mode -> starting REF -> where to save the preview), one question at
a time, reusing the same modal dialogs the rest of the app already uses
(gui_theme.ask_text/ask_choice/ask_size) -- not a form with everything
visible at once. See pa.do_create_catalog_from_images for how size and REF
numbers get decided when there's no real file to read them from.
"""
import os

import customtkinter as ctk
from PIL import Image

import db
import file_picker
import gui_theme
import gui_worker
import pa

THUMB_PX = 90


class ScratchCatalogPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._thumb_refs = []  # mantém CTkImage vivo

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Criar Catálogo do Zero").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Escolhe várias figuras soltas (uma peça por arquivo) e o sistema guia o resto passo a "
                 "passo: nome do catálogo, como definir o tamanho de cada peça, qual REF começar a contar "
                 "e onde salvar a prévia. Nada é publicado no site -- só cria o catálogo local e abre a "
                 "prévia no CorelDRAW pra você conferir.",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=860, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        pick_row = ctk.CTkFrame(self, fg_color="transparent")
        pick_row.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 8))
        gui_theme.primary_button(
            pick_row, text="+ Escolher figuras", width=180, command=self._start_wizard,
        ).pack(side="left")
        self.status_label = ctk.CTkLabel(pick_row, text="Nenhuma figura escolhida ainda.",
                                          font=ctk.CTkFont(size=12), text_color="gray60")
        self.status_label.pack(side="left", padx=(16, 0))

        self.thumbs_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.thumbs_frame.grid(row=2, column=0, sticky="nsew", padx=28, pady=(4, 8))
        for col in range(8):
            self.thumbs_frame.grid_columnconfigure(col, weight=1)

        self.log_panel = gui_worker.LogPanel(self)
        self.log_panel.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 20))

    def on_show(self):
        pass

    def _build_thumbs(self, image_paths):
        for child in self.thumbs_frame.winfo_children():
            child.destroy()
        self._thumb_refs = []
        for i, path in enumerate(image_paths):
            try:
                image = Image.open(path).convert("RGBA")
                scale = min(THUMB_PX / image.width, THUMB_PX / image.height, 1.0)
                size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
                ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=size)
            except Exception:
                ctk_image = None
            self._thumb_refs.append(ctk_image)

            card = ctk.CTkFrame(self.thumbs_frame, fg_color=("gray92", "gray17"), corner_radius=8)
            card.grid(row=i // 8, column=i % 8, sticky="new", padx=4, pady=4)
            if ctk_image is not None:
                ctk.CTkLabel(card, image=ctk_image, text="").pack(padx=6, pady=(6, 2))
            else:
                ctk.CTkLabel(card, text="(erro)", text_color=gui_theme.DANGER,
                             width=THUMB_PX, height=THUMB_PX).pack(padx=6, pady=(6, 2))
            ctk.CTkLabel(
                card, text=os.path.basename(path), font=ctk.CTkFont(size=9), text_color="gray50",
                wraplength=THUMB_PX,
            ).pack(padx=6, pady=(0, 6))

    def _start_wizard(self):
        # Passo 1: escolher as figuras.
        image_paths = file_picker.pick_figure_files()
        if not image_paths:
            return
        self.status_label.configure(text=f"{len(image_paths)} figura(s) escolhida(s).")
        self._build_thumbs(image_paths)

        # Passo 2: nome do catálogo.
        name = gui_theme.ask_text(
            self.app, "Nome do catálogo", "Digite o nome do novo catálogo:")
        if not name:
            return

        # Passo 3: modo de tamanho.
        size_mode = gui_theme.ask_choice(
            self.app, "Tamanho das figuras", "Como definir o tamanho de cada peça?",
            [("Proporcional (só o lado maior)", "proportional"), ("Definir altura e largura exatas", "fixed")])
        if size_mode is None:
            return

        target_long_side_mm = None
        fixed_width_mm = None
        fixed_height_mm = None
        if size_mode == "proportional":
            value_str = gui_theme.ask_text(
                self.app, "Lado maior", "Tamanho do lado maior de CADA peça (mm) -- o outro lado ajusta "
                                        "sozinho, mantendo a proporção de cada figura:", default="90")
            if not value_str:
                return
            try:
                target_long_side_mm = float(value_str.strip().replace(",", "."))
                if target_long_side_mm <= 0:
                    raise ValueError
            except ValueError:
                gui_theme.show_message(self.app, "Medida inválida", "Informe um número positivo (em mm).")
                return
        else:
            size_result = gui_theme.ask_size(
                self.app, "Altura e largura exatas",
                "Toda peça vai sair com essa medida exata (pode distorcer figuras com proporção diferente):")
            if size_result is None:
                return
            fixed_width_mm, fixed_height_mm, _apply_to_catalog = size_result

        # Passo 4: a partir de qual REF continuar.
        current_max = db.get_max_reference_number()
        last_ref_str = gui_theme.ask_text(
            self.app, "Última referência usada",
            "Qual foi a última referência (número) usada em algum catálogo? O catálogo novo começa a "
            "contar a partir do número seguinte a esse:",
            default=str(current_max))
        if not last_ref_str:
            return
        try:
            last_reference_number = int(last_ref_str.strip())
            if last_reference_number < 0:
                raise ValueError
        except ValueError:
            gui_theme.show_message(self.app, "Número inválido", "Informe um número inteiro (0 ou maior).")
            return
        start_reference_number = last_reference_number + 1

        # Passo 5: onde salvar a prévia em CorelDRAW.
        save_path = file_picker.pick_save_path(f"{name}.cdr")
        if not save_path:
            return

        self._create_catalog(
            name, image_paths, target_long_side_mm, fixed_width_mm, fixed_height_mm,
            start_reference_number, save_path)

    def _create_catalog(
        self, name, image_paths, target_long_side_mm, fixed_width_mm, fixed_height_mm,
        start_reference_number, save_path,
    ):
        self.log_panel.show(f"Criando catálogo '{name}'...\n\n")

        def task():
            catalog_id = pa.do_create_catalog_from_images(
                name, image_paths, target_long_side_mm, fixed_width_mm, fixed_height_mm,
                start_reference_number)
            # Só salva no banco/local -- NUNCA publica no site sozinho;
            # abre uma prévia real em CorelDRAW pra conferir antes de
            # decidir publicar (isso é feito manualmente depois, na tela
            # de Catálogos, igual qualquer outro catálogo).
            pa.do_export_catalog_preview(catalog_id, save_path)
            return catalog_id

        def on_success(catalog_id):
            self.log_panel.hide_after()
            gui_theme.show_message(
                self.app, "Catálogo criado",
                f"\"{name}\" criado (id={catalog_id}) -- NÃO foi publicado no site. "
                f"A prévia foi salva e já está aberta no CorelDRAW:\n{save_path}")
            self.status_label.configure(text="Nenhuma figura escolhida ainda.")
            self._build_thumbs([])

        def on_error(ex):
            gui_theme.show_message(self.app, "Erro ao criar catálogo", str(ex))

        gui_worker.run_task(
            self.app, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)
