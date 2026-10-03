"""Separador de Figuras (IA): imports one or more "sheet" images (several
Santa Clauses, snowmen, ornaments etc. generated together in a grid by an
AI image tool) and splits each into individual PNGs, one per figure, with a
transparent background and no bleed from its neighbors.

Fully automatic for the common case (see separador_ia.py for how); for the
two ways that can still go wrong -- two figures read as one because they're
touching, or one design read as several because of a big detached
decoration -- this GUI lets a person fix it by hand (Juntar/Dividir/Excluir)
before saving, rather than silently trusting the algorithm.

Run with:
    python separador_figuras.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

import customtkinter as ctk
from PIL import Image

import file_picker
import gui_theme
import separador_ia

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

THUMB_MAX = 150


def _thumb_image(pil_image: Image.Image) -> ctk.CTkImage:
    w, h = pil_image.size
    scale = min(THUMB_MAX / w, THUMB_MAX / h, 1.0)
    size = (max(1, int(w * scale)), max(1, int(h * scale)))
    return ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=size)


class PieceCard(ctk.CTkFrame):
    """One figure's thumbnail plus its own small toolbar. `merge_var` is a
    plain BooleanVar the section header reads to know which cards to merge
    when "Juntar marcadas" is clicked -- kept on the card so the section
    doesn't need a separate parallel list to stay in sync with reordering."""

    def __init__(self, master, section: "SheetSection", piece, thumb: ctk.CTkImage):
        super().__init__(master, fg_color=("gray90", "gray17"), corner_radius=10)
        self.section = section
        self.piece = piece

        self._image_ref = thumb
        ctk.CTkLabel(self, image=thumb, text="").pack(padx=8, pady=(8, 4))

        self.merge_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self, text="marcar p/ juntar", variable=self.merge_var,
            font=ctk.CTkFont(size=10), checkbox_width=16, checkbox_height=16,
        ).pack(pady=(0, 4))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=(0, 8))
        ctk.CTkButton(
            row, text="✂ Dividir", width=70, height=26, font=ctk.CTkFont(size=11),
            fg_color=gui_theme.ACCENT_BLUE, hover_color=gui_theme.ACCENT_BLUE_HOVER, text_color="#1a1a1f",
            command=lambda: section.split_piece(piece),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            row, text="✕", width=30, height=26, font=ctk.CTkFont(size=11),
            fg_color=gui_theme.DANGER, hover_color=gui_theme.DANGER_HOVER,
            command=lambda: section.delete_piece(piece),
        ).pack(side="left")


class SheetSection(ctk.CTkFrame):
    """Everything for one imported source image: a header with its own
    Juntar/Excluir-marcadas actions, and a wrapping grid of PieceCards
    below. Rebuilt from scratch (rebuild()) after every edit -- piece counts
    are always small enough (a handful, rarely more than a dozen) that
    redrawing everything is simpler than patching the grid in place, and it
    guarantees the on-screen cards can never drift out of sync with
    `sheet.pieces`."""

    def __init__(self, master, app: "FigureSplitterPage", sheet: separador_ia.Sheet):
        super().__init__(master, fg_color=("gray95", "gray14"), corner_radius=12)
        self.app = app
        self.sheet = sheet
        self.cards: list[PieceCard] = []

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(14, 4))
        self.title_label = ctk.CTkLabel(
            header, text="", font=ctk.CTkFont(size=14, weight="bold"), anchor="w")
        self.title_label.pack(side="left")

        button_row = ctk.CTkFrame(header, fg_color="transparent")
        button_row.pack(side="right")
        gui_theme.secondary_button(
            button_row, text="Juntar marcadas", width=130, height=28,
            font=ctk.CTkFont(size=11, weight="bold"), command=self.merge_marked,
        ).pack(side="left", padx=4)
        gui_theme.danger_button(
            button_row, text="Excluir marcadas", width=130, height=28,
            font=ctk.CTkFont(size=11, weight="bold"), command=self.delete_marked,
        ).pack(side="left")

        self.grid_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.grid_frame.pack(fill="x", padx=16, pady=(4, 16))

        self.rebuild()

    def _marked_pieces(self):
        return [c.piece for c in self.cards if c.merge_var.get()]

    def merge_marked(self):
        marked = self._marked_pieces()
        if len(marked) < 2:
            gui_theme.show_message(self.app, "Juntar figuras", "Marque pelo menos 2 figuras (\"marcar p/ juntar\") antes de juntar.")
            return
        merged_labels = set()
        for p in marked:
            merged_labels |= p.labels
        self.sheet.pieces = [p for p in self.sheet.pieces if p not in marked]
        self.sheet.pieces.append(separador_ia.Piece(merged_labels))
        self.rebuild()

    def delete_marked(self):
        marked = self._marked_pieces()
        if not marked:
            gui_theme.show_message(self.app, "Excluir figuras", "Marque as figuras (\"marcar p/ juntar\") que quer excluir.")
            return
        self.sheet.pieces = [p for p in self.sheet.pieces if p not in marked]
        self.rebuild()

    def delete_piece(self, piece):
        self.sheet.pieces = [p for p in self.sheet.pieces if p is not piece]
        self.rebuild()

    def split_piece(self, piece):
        new_pieces = self.sheet.split_piece(piece)
        if len(new_pieces) == 1:
            gui_theme.show_message(
                self.app, "Dividir figura",
                "Não achei um ponto claro de separação nessa figura -- ela deve ser realmente uma peça só.")
            return
        self.sheet.pieces = [p for p in self.sheet.pieces if p is not piece] + new_pieces
        self.rebuild()

    def rebuild(self):
        for card in self.cards:
            card.destroy()
        self.cards = []
        self.title_label.configure(
            text=f"{os.path.basename(self.sheet.path)}  —  {len(self.sheet.pieces)} figura(s)")

        columns = 5
        for i, piece in enumerate(self.sheet.pieces):
            thumb_img = self.sheet.render(piece)
            thumb = _thumb_image(thumb_img)
            card = PieceCard(self.grid_frame, self, piece, thumb)
            card.grid(row=i // columns, column=i % columns, padx=6, pady=6, sticky="n")
            self.cards.append(card)
        self.app.refresh_save_button()


class FigureSplitterPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.sheets: dict[str, separador_ia.Sheet] = {}
        self.sections: dict[str, SheetSection] = {}

        gui_theme.back_button(self, self.app).pack(anchor="w", padx=20, pady=(16, 0))

        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.pack(fill="x", padx=20, pady=16)
        ctk.CTkLabel(
            top_bar, text="Separador de Figuras (IA)", font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(side="left")

        button_row = ctk.CTkFrame(top_bar, fg_color="transparent")
        button_row.pack(side="right")
        gui_theme.primary_button(
            button_row, text="📂 Importar Imagens", width=180, command=self.import_images,
        ).pack(side="left", padx=6)
        self.save_button = gui_theme.secondary_button(
            button_row, text="💾 Salvar Tudo", width=150, command=self.save_all,
        )
        self.save_button.pack(side="left", padx=6)
        self.save_button.configure(state="disabled")

        self.status_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12), text_color="gray60")
        self.status_label.pack(anchor="w", padx=24)

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.scroll.pack(fill="both", expand=True, padx=20, pady=(4, 20))

        self.empty_label = ctk.CTkLabel(
            self.scroll, text="Nenhuma imagem importada ainda.\nClique em \"Importar Imagens\" pra começar.",
            font=ctk.CTkFont(size=14), text_color="gray50")
        self.empty_label.pack(pady=60)

    def import_images(self):
        paths = file_picker.pick_image_files()
        if not paths:
            return
        self.empty_label.pack_forget()
        self.status_label.configure(text=f"Processando {len(paths)} imagem(ns)...")
        self.update_idletasks()

        for path in paths:
            try:
                sheet = separador_ia.load_sheet(path)
            except Exception as ex:
                gui_theme.show_message(self, "Erro ao processar", f"Não consegui processar\n{path}\n\n{ex}")
                continue
            self.sheets[path] = sheet
            if path in self.sections:
                self.sections[path].destroy()
            section = SheetSection(self.scroll, self, sheet)
            section.pack(fill="x", pady=(0, 16))
            self.sections[path] = section

        self.status_label.configure(text="")
        self.refresh_save_button()

    def refresh_save_button(self):
        has_pieces = any(s.pieces for s in self.sheets.values())
        self.save_button.configure(state="normal" if has_pieces else "disabled")

    def save_all(self):
        # Uma pasta só pra TODAS as folhas -- usada antes era uma pasta
        # "..._separadas" por folha de origem, o que espalhava as peças de
        # um lote gerado em várias pastas diferentes; ficar tudo junto é o
        # que deixa fácil importar direto no "Criar Catálogo do Zero"
        # depois, sem ter que catar peça por peça em pastas separadas.
        out_dir = file_picker.pick_output_folder("Selecione a pasta onde salvar TODAS as figuras")
        if not out_dir:
            return

        total_saved = 0
        for path, sheet in self.sheets.items():
            if not sheet.pieces:
                continue
            base = os.path.splitext(os.path.basename(path))[0]
            for i, piece in enumerate(sheet.pieces, start=1):
                image = sheet.render(piece)
                # Duas folhas de origem com o mesmo nome (fácil de acontecer
                # com nomes genéricos tipo "lote_0.png" de origens
                # diferentes) não podem mais cair em pastas separadas pra
                # não colidir -- agora that's exatamente o ponto de ter uma
                # pasta só, então garante um nome livre em vez de
                # sobrescrever uma peça já salva.
                out_path = os.path.join(out_dir, f"{base}_{i}.png")
                suffix = 1
                while os.path.exists(out_path):
                    out_path = os.path.join(out_dir, f"{base}_{i}_{suffix}.png")
                    suffix += 1
                image.save(out_path)
                total_saved += 1
        gui_theme.show_message(self, "Salvo", f"{total_saved} figura(s) salva(s) em:\n{out_dir}")


if __name__ == "__main__":
    root = ctk.CTk()
    root.title("Baby Luz - Separador de Figuras (IA)")
    root.geometry("1100x750")

    class _StandaloneApp:
        def show_page(self, _key):
            root.destroy()

    FigureSplitterPage(root, _StandaloneApp()).pack(fill="both", expand=True)
    root.mainloop()
