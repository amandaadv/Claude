"""Testar Melhoria (IA): pick one catalog, pick one figure from it, and see
the before/after of the AI enhance+background-removal right in the app --
same underlying call as the batch tool (image_enhancer.py), just one figure
at a time and nothing gets touched in the catalog unless "Usar este
resultado" is clicked. Meant to be used first, to check the result looks
good, before trusting the batch tool with a whole catalog.
"""
import datetime
import io
import os

import customtkinter as ctk
from PIL import Image

import db
import gui_theme
import gui_worker
import image_enhancer
import image_storage

PREVIEW_BOX_PX = 320
# Every "Testar" result lands here too, not just in memory -- otherwise
# looking at a result closely (zoomed in, on a real monitor) meant either
# spending another API call to regenerate it or committing it to the
# catalog first just to get a file out.
TEST_OUTPUT_FOLDER = os.path.join(os.path.expanduser("~"), "Desktop", "BabyLuz-Testes-IA")


def _fit_image(pil_image: Image.Image, box_px: int) -> ctk.CTkImage:
    image = pil_image.convert("RGBA")
    scale = min(box_px / image.width, box_px / image.height, 1.0)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return ctk.CTkImage(light_image=image, dark_image=image, size=size)


class ImageTestPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app

        self._catalogs: list[tuple] = []
        self._catalog_id: int | None = None
        self._rows: list[dict] = []
        self._selected_row: dict | None = None
        self._selected_item_frame: ctk.CTkFrame | None = None
        self._enhanced_bytes: bytes | None = None
        self._before_image_ref = None
        self._after_image_ref = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=28, pady=(24, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Testar Melhoria (IA)").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Escolhe um catálogo, clica numa figura da lista e depois em \"Testar\" pra ver o antes "
                 "e depois -- nada é alterado no catálogo até você clicar em \"Usar este resultado\". Use "
                 "isso pra conferir a qualidade antes de rodar o \"Melhorador de Imagens\" no catálogo inteiro.",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=820, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        # -- coluna esquerda: catálogo + lista de figuras --------------------
        left = ctk.CTkFrame(self, fg_color="transparent", width=260)
        left.grid(row=1, column=0, sticky="nsw", padx=(28, 12), pady=(0, 20))
        left.grid_propagate(False)
        left.grid_rowconfigure(1, weight=1)

        self.catalog_var = ctk.StringVar(value="")
        self.catalog_combo = ctk.CTkComboBox(
            left, values=[], variable=self.catalog_var, width=260,
            command=self._on_catalog_selected, state="readonly")
        self.catalog_combo.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.list_frame = ctk.CTkScrollableFrame(
            left, fg_color="transparent", width=260, **gui_theme.SCROLLBAR_KWARGS)
        self.list_frame.grid(row=1, column=0, sticky="nsew")

        # -- coluna direita: antes / depois -----------------------------------
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew", padx=(0, 28), pady=(0, 20))
        right.grid_columnconfigure((0, 1), weight=1)
        right.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(right, text="Antes", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 4))
        ctk.CTkLabel(right, text="Depois", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=1, sticky="w", pady=(0, 4))

        # A label whose `image` is repeatedly reconfigured in place is a known
        # customtkinter trap (TclError: image "pyimageN" doesn't exist) once
        # the previous CTkImage gets garbage-collected -- every other tool in
        # this app that swaps thumbnails destroys and recreates the label
        # instead (see montador_folha.py's import_images), so these are
        # empty containers; _set_panel shows content by building a fresh
        # child label inside, never reusing one.
        self.before_container = ctk.CTkFrame(
            right, fg_color="gray50", corner_radius=8, width=PREVIEW_BOX_PX, height=PREVIEW_BOX_PX)
        self.before_container.grid(row=1, column=0, sticky="n", padx=(0, 8))
        self.before_container.grid_propagate(False)
        self.after_container = ctk.CTkFrame(
            right, fg_color="gray50", corner_radius=8, width=PREVIEW_BOX_PX, height=PREVIEW_BOX_PX)
        self.after_container.grid(row=1, column=1, sticky="n", padx=(8, 0))
        self.after_container.grid_propagate(False)

        footer = ctk.CTkFrame(right, fg_color="transparent")
        footer.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.test_button = gui_theme.primary_button(
            footer, text="Testar", width=160, height=36, command=self._start_test)
        self.test_button.pack(side="left")
        self.use_button = gui_theme.secondary_button(
            footer, text="Usar este resultado", width=180, height=36, command=self._use_result)
        self.use_button.pack(side="left", padx=(8, 0))
        self.use_button.configure(state="disabled")
        self.status_label = ctk.CTkLabel(footer, text="", font=ctk.CTkFont(size=12), text_color="gray60")
        self.status_label.pack(side="left", padx=(16, 0))

        self.log_panel = gui_worker.LogPanel(right)
        self.log_panel.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        self._load_catalogs()

    def on_show(self):
        self._load_catalogs()

    # -- catálogo / lista ------------------------------------------------

    def _load_catalogs(self):
        self._catalogs = db.get_all_catalogs()
        values = [f"{name}  ({total_arts} figura(s))" for _id, name, _s, _c, total_arts, _a, _r, _p in self._catalogs]
        self.catalog_combo.configure(values=values)
        if values and self.catalog_var.get() not in values:
            self.catalog_var.set(values[0])
            self._on_catalog_selected(values[0])
        elif not values:
            self.catalog_var.set("")
            self._catalog_id = None
            self._rows = []
            self._build_list_ui()

    def _on_catalog_selected(self, _choice):
        index = self.catalog_combo.cget("values").index(self.catalog_var.get())
        catalog_id = self._catalogs[index][0]
        self._catalog_id = catalog_id

        arts = db.get_arts_with_paths_by_catalog_id(catalog_id)
        self._rows = [
            {
                "art_id": art_id, "reference": reference or f"#{art_id}",
                "original_image_path": original_image_path, "preview_path": preview_path,
            }
            for art_id, reference, _page_number, original_image_path, preview_path, _review_status in arts
            if original_image_path
        ]
        self._selected_row = None
        self._build_list_ui()
        self._clear_previews()

    def _build_list_ui(self):
        for child in self.list_frame.winfo_children():
            child.destroy()
        self._selected_item_frame = None

        if not self._rows:
            ctk.CTkLabel(
                self.list_frame, text="Esse catálogo não tem figuras.",
                font=ctk.CTkFont(size=12), text_color="gray60").pack(anchor="w", pady=10)
            return

        for row in self._rows:
            item = ctk.CTkFrame(self.list_frame, fg_color=("gray90", "gray17"), corner_radius=6, cursor="hand2")
            item.pack(fill="x", pady=2)
            label = ctk.CTkLabel(item, text=row["reference"], font=ctk.CTkFont(size=12), anchor="w")
            label.pack(fill="x", padx=10, pady=6)
            for widget in (item, label):
                widget.bind("<Button-1>", lambda _e, row=row, frame=item: self._select_row(row, frame))

    def _select_row(self, row, frame):
        if self._selected_item_frame is not None:
            self._selected_item_frame.configure(fg_color=("gray90", "gray17"))
        frame.configure(fg_color=gui_theme.ACCENT_BLUE)
        self._selected_item_frame = frame
        self._selected_row = row
        self._clear_previews()
        self._show_before(row)

    # -- preview -----------------------------------------------------------

    @staticmethod
    def _set_panel(container, ctk_image=None, error_text=""):
        for child in container.winfo_children():
            child.destroy()
        if ctk_image is not None:
            ctk.CTkLabel(container, image=ctk_image, text="").place(relx=0.5, rely=0.5, anchor="center")
        elif error_text:
            ctk.CTkLabel(
                container, text=error_text, text_color=gui_theme.DANGER, wraplength=PREVIEW_BOX_PX - 20,
                justify="center").place(relx=0.5, rely=0.5, anchor="center")

    def _clear_previews(self):
        self._set_panel(self.before_container)
        self._set_panel(self.after_container)
        self._before_image_ref = None
        self._after_image_ref = None
        self._enhanced_bytes = None
        self.use_button.configure(state="disabled")
        self.status_label.configure(text="")

    def _show_before(self, row):
        try:
            image = Image.open(row["original_image_path"])
            self._before_image_ref = _fit_image(image, PREVIEW_BOX_PX)
            self._set_panel(self.before_container, ctk_image=self._before_image_ref)
        except Exception as ex:
            self._before_image_ref = None
            self._set_panel(self.before_container, error_text=f"Erro ao abrir:\n{ex}")

    def _start_test(self):
        if not self._selected_row:
            gui_theme.show_message(self, "Nada selecionado", "Clique numa figura da lista primeiro.")
            return

        row = self._selected_row
        self.status_label.configure(text="Chamando a IA...")
        self.log_panel.show(f"Testando {row['reference']}...\n\n")
        self._set_panel(self.after_container)
        self._after_image_ref = None
        self._enhanced_bytes = None
        self.use_button.configure(state="disabled")

        def task():
            with open(row["original_image_path"], "rb") as f:
                original_bytes = f.read()
            return image_enhancer.enhance_and_remove_background(original_bytes)

        def on_success(enhanced_bytes):
            self._enhanced_bytes = enhanced_bytes
            image = Image.open(io.BytesIO(enhanced_bytes))
            self._after_image_ref = _fit_image(image, PREVIEW_BOX_PX)
            self._set_panel(self.after_container, ctk_image=self._after_image_ref)

            os.makedirs(TEST_OUTPUT_FOLDER, exist_ok=True)
            safe_reference = "".join(c if c.isalnum() else "_" for c in row["reference"])
            saved_path = os.path.join(TEST_OUTPUT_FOLDER, f"{safe_reference}_depois.png")
            with open(saved_path, "wb") as f:
                f.write(enhanced_bytes)

            self.status_label.configure(text=f"Pronto. Salvo em Desktop\\BabyLuz-Testes-IA\\{os.path.basename(saved_path)}")
            self.use_button.configure(state="normal")
            self.log_panel.hide_after()

        def on_error(ex):
            self.status_label.configure(text="Falhou.")
            gui_theme.show_message(self, "Erro ao testar", str(ex))

        gui_worker.run_task(self, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)

    def _use_result(self):
        if not self._selected_row or not self._enhanced_bytes:
            return
        row = self._selected_row
        if not gui_theme.ask_confirm(
            self, "Usar este resultado",
            f"Isso vai SUBSTITUIR a imagem original de {row['reference']} no catálogo pela versão que "
            f"você acabou de ver em \"Depois\" -- o original fica guardado num backup antes disso. Quer continuar?",
            confirm_text="Substituir", danger=False,
        ):
            return

        backup_tag = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        image_storage.backup_and_replace_art_image(
            self._catalog_id, row["original_image_path"], row["preview_path"], self._enhanced_bytes, backup_tag)
        db.mark_art_enhanced(row["art_id"], backup_tag)
        self.status_label.configure(text="Substituído no catálogo.")
        self.use_button.configure(state="disabled")


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.title("Baby Luz — Testar Melhoria (IA)")
    root.geometry("900x760")

    class _StandaloneApp:
        def show_page(self, _key):
            root.destroy()

    ImageTestPage(root, _StandaloneApp()).pack(fill="both", expand=True)
    root.mainloop()
