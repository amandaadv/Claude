"""Native Windows file-picker dialogs (Explorer), via tkinter -- part of the
Python standard library, no extra install needed.
"""
import tkinter
from tkinter import filedialog


def _with_hidden_root(action):
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return action()
    finally:
        root.destroy()


def pick_cdr_file(title="Selecione o arquivo CorelDRAW (.cdr ou .zip)") -> str | None:
    """Same accepted formats as pick_master_file (a .cdr, or a .zip
    containing/being one -- see master_artwork.ensure_valid_cdr_file), just
    with a title that doesn't assume the file is a catalog -- used by
    generic .cdr tools (e.g. the version converter) with no catalog
    context of their own."""
    def action():
        path = filedialog.askopenfilename(
            title=title, filetypes=[("Arquivo CorelDRAW", "*.cdr *.zip"), ("Todos os arquivos", "*.*")],
        )
        return path or None
    return _with_hidden_root(action)


def pick_cdr_files() -> list[str]:
    """Same accepted formats as pick_cdr_file, letting several files be
    chosen at once -- for importing many designer master files straight
    into one merged catalog (see pa.do_import_from_multiple_masters)."""
    def action():
        paths = filedialog.askopenfilenames(
            title="Selecione os arquivos CorelDRAW (.cdr ou .zip) -- pode escolher vários",
            filetypes=[("Arquivo CorelDRAW", "*.cdr *.zip"), ("Todos os arquivos", "*.*")],
        )
        return list(paths)
    return _with_hidden_root(action)


def pick_master_file() -> str | None:
    """Opens Explorer for the designer's master file: a .cdr, or a .zip
    containing/being one. Returns the path, or None if cancelled."""
    def action():
        path = filedialog.askopenfilename(
            title="Selecione o arquivo original do catálogo (.cdr ou .zip)",
            filetypes=[("Arquivo original", "*.cdr *.zip"), ("Todos os arquivos", "*.*")],
        )
        return path or None
    return _with_hidden_root(action)


def pick_save_path(default_name: str) -> str | None:
    """Opens Explorer's "save as" dialog for a .cdr file. Returns the path, or None if cancelled."""
    def action():
        path = filedialog.asksaveasfilename(
            title="Salvar arquivo de produção do CorelDRAW",
            defaultextension=".cdr",
            initialfile=default_name,
            filetypes=[("Arquivo CorelDRAW", "*.cdr"), ("Todos os arquivos", "*.*")],
        )
        return path or None
    return _with_hidden_root(action)


def pick_save_path_pdf(default_name: str) -> str | None:
    """Opens Explorer's "save as" dialog for a .pdf file. Returns the path, or None if cancelled."""
    def action():
        path = filedialog.asksaveasfilename(
            title="Salvar folha de etiquetas",
            defaultextension=".pdf",
            initialfile=default_name,
            filetypes=[("PDF", "*.pdf"), ("Todos os arquivos", "*.*")],
        )
        return path or None
    return _with_hidden_root(action)


def pick_save_path_png(default_name: str) -> str | None:
    """Opens Explorer's "save as" dialog for a .png file. Returns the path, or None if cancelled."""
    def action():
        path = filedialog.asksaveasfilename(
            title="Salvar figura (PNG)",
            defaultextension=".png",
            initialfile=default_name,
            filetypes=[("Imagem PNG", "*.png"), ("Todos os arquivos", "*.*")],
        )
        return path or None
    return _with_hidden_root(action)


def pick_save_path_xlsx(default_name: str) -> str | None:
    """Opens Explorer's "save as" dialog for a .xlsx file. Returns the path, or None if cancelled."""
    def action():
        path = filedialog.asksaveasfilename(
            title="Salvar orçamento",
            defaultextension=".xlsx",
            initialfile=default_name,
            filetypes=[("Planilha Excel", "*.xlsx"), ("Todos os arquivos", "*.*")],
        )
        return path or None
    return _with_hidden_root(action)


def pick_output_folder(title="Selecione a pasta onde salvar") -> str | None:
    """Opens Explorer's folder-browse dialog. Returns the path, or None if cancelled."""
    def action():
        path = filedialog.askdirectory(title=title)
        return path or None
    return _with_hidden_root(action)


def pick_image_files() -> list[str]:
    """Opens Explorer allowing multiple image selection. Returns a list (possibly empty)."""
    def action():
        paths = filedialog.askopenfilenames(
            title="Selecione a(s) foto(s) do cliente",
            filetypes=[
                ("Imagens", "*.jpg *.jpeg *.png *.bmp *.webp"),
                ("Todos os arquivos", "*.*"),
            ],
        )
        return list(paths)
    return _with_hidden_root(action)


def pick_figure_files() -> list[str]:
    """Same file types as pick_image_files, just a title that doesn't
    assume these are a customer's photos -- used when building a catalog
    from scratch out of loose already-cut figures (AI-generated,
    separated from a sheet, etc)."""
    def action():
        paths = filedialog.askopenfilenames(
            title="Selecione as figuras (uma peça por arquivo)",
            filetypes=[
                ("Imagens", "*.png *.jpg *.jpeg *.bmp *.webp"),
                ("Todos os arquivos", "*.*"),
            ],
        )
        return list(paths)
    return _with_hidden_root(action)
