"""Modern desktop GUI for the production-automation workflow -- same database,
storage and business logic as pa.py's terminal menu (nothing here duplicates
or replaces it: every action calls straight into pa.py's do_* functions), just
a nicer way to drive it than typing menu numbers.

Navigation is dashboard-based: the Início page is the one hub every other
screen is reached from, and each other screen has its own "← Início" button
to go back -- one place to go looking for "where's X". No sidebar: it used to
carry a live catálogo/fila counter, but that duplicated the badges already
shown on the Início page's own cards, so it was dropped rather than kept
around just to hold a logo.

Pages are lazily imported and instantiated on first access so that heavy
dependencies (onnxruntime, clip_embedding, coreldraw_service, etc.) are
only loaded when the operator actually opens that screen -- not all at once
at startup, which used to make the app take several seconds to appear.

Run with:
    python gui_app.py
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gerador_catalogos"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gerador_etiquetas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "montador_folha"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "redimensionador_lote"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "separador_figuras"))

import customtkinter as ctk

import db
import gui_worker
import image_storage
import website_sync

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

# (module_name, ClassName) for each page key -- imported lazily on first use.
_PAGE_SPECS: dict[str, tuple[str, str]] = {
    "home":                 ("gui_page_home",               "HomePage"),
    "catalogs":             ("gui_page_catalogs",           "CatalogsPage"),
    "search":               ("gui_page_search",             "SearchPage"),
    "queue":                ("gui_page_queue",              "QueuePage"),
    "order":                ("gui_page_order",              "OrderPage"),
    "profiles":             ("gui_page_profiles",           "ProfilesPage"),
    "website":              ("gui_page_website",            "WebsitePage"),
    "representantes":       ("gui_page_representantes",     "RepresentantesPage"),
    "prices":               ("gui_page_prices",              "PricesPage"),
    "settings":             ("gui_page_settings",           "SettingsPage"),
    "catalog_generator":    ("gerador_catalogos",           "CatalogGeneratorPage"),
    "catalog_3_sizes":      ("gui_page_catalog_3_sizes",    "Catalog3SizesPage"),
    "catalog_production":   ("gui_page_catalog_production", "CatalogProductionPage"),
    "join_pages":           ("gui_page_join_pages",         "JoinPagesPage"),
    "personalized_catalog": ("gui_page_personalized_catalog", "PersonalizedCatalogPage"),
    "label_generator":      ("gerador_etiquetas",           "LabelGeneratorPage"),
    "sheet_assembler":      ("montador_folha",              "SheetAssemblerPage"),
    "batch_resize":         ("redimensionador_lote",        "BatchResizePage"),
    "figure_splitter":      ("separador_figuras",           "FigureSplitterPage"),
    "image_enhancer":       ("gui_page_image_enhancer",     "ImageEnhancerPage"),
    "trim_borders":         ("gui_page_trim_borders",       "TrimBordersPage"),
    "image_test":           ("gui_page_image_test",         "ImageTestPage"),
    "version_converter":    ("gui_page_version_converter",  "VersionConverterPage"),
    "ai_figure_creator":    ("gui_page_ai_figure_creator",  "AiFigureCreatorPage"),
    "scratch_catalog":      ("gui_page_scratch_catalog",    "ScratchCatalogPage"),
    "merge_catalogs":       ("gui_page_merge_catalogs",     "MergeCatalogsPage"),
    "fix_shape_sizes":      ("gui_page_fix_shape_sizes",    "FixShapeSizesPage"),
}


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Baby Luz — Automação de Produção")
        self.geometry("1240x780")
        self.minsize(1024, 650)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._container = ctk.CTkFrame(self, fg_color="transparent")
        self._container.grid(row=0, column=0, sticky="nsew")
        self._container.grid_rowconfigure(0, weight=1)
        self._container.grid_columnconfigure(0, weight=1)
        self._pages: dict = {}

        self.show_page("home")
        self._sync_catalogs_with_site()

    def _sync_catalogs_with_site(self):
        """Best-effort, runs on every startup: deactivates any catalog still
        showing on the public site that no longer exists locally -- the fix
        for residue left behind when the local database gets wiped (a
        Windows reinstall, say) without each old catalog getting a proper
        "Excluir catálogo" click first. Silent on success/failure since
        there's no console to print to (pythonw) -- a stale site is a
        nuisance to notice and fix here, not worth a popup on every launch."""
        def task():
            local_names = {row[1] for row in db.get_all_catalogs()}
            result = website_sync.sync_catalogs(local_names)
            # Também alinha a ORDEM dos catálogos no site com a do sistema (catálogo novo, renomeado ou
            # excluído desalinhava as duas listas) -- ver pa.sync_catalog_order_to_site.
            try:
                import pa
                pa.sync_catalog_order_to_site()
            except Exception:
                pass
            return result

        gui_worker.run_task(self, task)

    def _get_page(self, key: str):
        if key not in self._pages:
            module_name, class_name = _PAGE_SPECS[key]
            module = importlib.import_module(module_name)
            page = getattr(module, class_name)(self._container, self)
            page.grid(row=0, column=0, sticky="nsew")
            self._pages[key] = page
        return self._pages[key]

    def show_page(self, key: str):
        page = self._get_page(key)
        page.tkraise()
        if hasattr(page, "on_show"):
            page.on_show()


if __name__ == "__main__":
    db.ensure_schema_extensions()
    for _abandoned_id, _abandoned_name in db.delete_abandoned_empty_catalogs():
        image_storage.delete_catalog_images(_abandoned_id)
    App().mainloop()
