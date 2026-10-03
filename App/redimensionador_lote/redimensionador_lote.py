"""Redimensionador em Lote: imports several already-cut figure PNGs and
resizes all of them into two (or more) target sizes at once, each size
landing in its own numbered folder -- e.g. the same 15 stickers exported
once at 90x56mm and once at 50x30mm, ready to hand off for production
without resizing each figure by hand in CorelDRAW one at a time.

Run with:
    python redimensionador_lote.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

import customtkinter as ctk
from PIL import Image

import file_picker
import gui_theme
import redimensionador_ia

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

THUMB_SIZE = 70


class SizeColumn(ctk.CTkFrame):
    """One target-size profile: a title, height/width (mm) entries, and a
    live-updating folder-name preview so the person can see exactly what
    they'll get ("90x56mm") before clicking Gerar."""

    def __init__(self, master, title: str):
        super().__init__(master, fg_color=("gray95", "gray14"), corner_radius=12)
        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(16, 12), padx=20, anchor="w")

        ctk.CTkLabel(self, text="Altura (mm):").pack(padx=20, anchor="w")
        self.height_entry = ctk.CTkEntry(self, placeholder_text="ex: 90")
        self.height_entry.pack(padx=20, pady=(2, 12), fill="x")

        ctk.CTkLabel(self, text="Largura (mm):").pack(padx=20, anchor="w")
        self.width_entry = ctk.CTkEntry(self, placeholder_text="ex: 56")
        self.width_entry.pack(padx=20, pady=(2, 12), fill="x")

        self.preview_label = ctk.CTkLabel(self, text="Pasta: —", font=ctk.CTkFont(size=11), text_color="gray60")
        self.preview_label.pack(padx=20, pady=(0, 16), anchor="w")

        self.height_entry.bind("<KeyRelease>", lambda _e: self._update_preview())
        self.width_entry.bind("<KeyRelease>", lambda _e: self._update_preview())

    def _update_preview(self):
        values = self.get_values()
        if values:
            height_mm, width_mm = values
            self.preview_label.configure(
                text=f"Pasta: {redimensionador_ia.folder_name_for_size(height_mm, width_mm)}")
        else:
            self.preview_label.configure(text="Pasta: —")

    def get_values(self) -> tuple[float, float] | None:
        try:
            height_mm = float(self.height_entry.get().strip().replace(",", "."))
            width_mm = float(self.width_entry.get().strip().replace(",", "."))
            if height_mm <= 0 or width_mm <= 0:
                return None
            return height_mm, width_mm
        except ValueError:
            return None


class BatchResizePage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.image_paths: list[str] = []

        gui_theme.back_button(self, self.app).pack(anchor="w", padx=20, pady=(16, 0))

        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.pack(fill="x", padx=20, pady=16)
        ctk.CTkLabel(
            top_bar, text="Redimensionador em Lote", font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(side="left")
        gui_theme.primary_button(
            top_bar, text="📂 Importar Figuras", width=180, command=self.import_images,
        ).pack(side="right")

        self.count_label = ctk.CTkLabel(
            self, text="Nenhuma figura importada ainda.", font=ctk.CTkFont(size=13), text_color="gray60")
        self.count_label.pack(anchor="w", padx=24)

        self.thumbs_frame = ctk.CTkScrollableFrame(
            self, fg_color=("gray95", "gray14"), corner_radius=10, height=110,
            orientation="horizontal", **gui_theme.SCROLLBAR_KWARGS)
        self.thumbs_frame.pack(fill="x", padx=20, pady=(8, 20))

        columns_frame = ctk.CTkFrame(self, fg_color="transparent")
        columns_frame.pack(fill="x", padx=20)
        columns_frame.grid_columnconfigure(0, weight=1)
        columns_frame.grid_columnconfigure(1, weight=1)

        self.column1 = SizeColumn(columns_frame, "Tamanho 1")
        self.column1.grid(row=0, column=0, padx=(0, 10), sticky="nsew")
        self.column2 = SizeColumn(columns_frame, "Tamanho 2")
        self.column2.grid(row=0, column=1, padx=(10, 0), sticky="nsew")

        gui_theme.primary_button(
            self, text="⚙ Gerar", width=200, height=42,
            font=ctk.CTkFont(size=14, weight="bold"), command=self.generate,
        ).pack(pady=24)

        self.status_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12), text_color="gray60")
        self.status_label.pack()

    def import_images(self):
        paths = file_picker.pick_image_files()
        if not paths:
            return
        self.image_paths = paths
        self.count_label.configure(text=f"{len(paths)} figura(s) importada(s).")

        for widget in self.thumbs_frame.winfo_children():
            widget.destroy()
        for path in paths:
            try:
                im = Image.open(path).convert("RGBA")
                im.thumbnail((THUMB_SIZE, THUMB_SIZE))
                thumb = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
            except Exception:
                continue
            card = ctk.CTkFrame(self.thumbs_frame, fg_color="transparent")
            card.pack(side="left", padx=6, pady=6)
            ctk.CTkLabel(card, image=thumb, text="").pack()
            ctk.CTkLabel(
                card, text=os.path.basename(path), font=ctk.CTkFont(size=9),
                text_color="gray60", wraplength=THUMB_SIZE,
            ).pack()
            card._image_ref = thumb  # keep alive

    def generate(self):
        if not self.image_paths:
            gui_theme.show_message(self, "Redimensionar", "Importe as figuras primeiro.")
            return

        profiles = []
        for i, column in enumerate((self.column1, self.column2), start=1):
            values = column.get_values()
            if values is None:
                gui_theme.show_message(
                    self, "Redimensionar",
                    f"Preencha altura e largura (em mm, maiores que zero) no \"Tamanho {i}\".")
                return
            profiles.append(values)

        output_dir = file_picker.pick_output_folder("Selecione onde criar as pastas com as figuras redimensionadas")
        if not output_dir:
            return

        self.status_label.configure(text="Gerando...")
        self.update_idletasks()
        try:
            results = redimensionador_ia.generate_batch(self.image_paths, profiles, output_dir)
        except Exception as ex:
            self.status_label.configure(text="")
            gui_theme.show_message(self, "Erro ao gerar", str(ex))
            return

        self.status_label.configure(text="")
        summary = "\n".join(f"• {folder}: {count} figura(s)" for folder, count in results.items())
        gui_theme.show_message(
            self, "Gerado", f"Pronto! Pastas criadas em:\n{output_dir}\n\n{summary}")


if __name__ == "__main__":
    root = ctk.CTk()
    root.title("Baby Luz - Redimensionador em Lote")
    root.geometry("900x640")

    class _StandaloneApp:
        def show_page(self, _key):
            root.destroy()

    BatchResizePage(root, _StandaloneApp()).pack(fill="both", expand=True)
    root.mainloop()
