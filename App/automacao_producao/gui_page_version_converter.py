"""Conversor de Versão page: opens a .cdr file, shows which CorelDRAW
version it was last saved with (when that can be detected -- see
master_artwork.detect_cdr_app_version), and saves a converted copy at
whichever version the operator picks. For sending a file to someone whose
CorelDRAW is older than the one used here.
"""
import customtkinter as ctk

import coreldraw_service
import file_picker
import gui_theme
import gui_worker
import master_artwork
import pa

# Confirmed for 22-27 against real file metadata + gui_page_settings.py's
# own version field; older ones follow the same year = version + 1998
# convention but aren't independently confirmed here.
_VERSION_YEAR_LABELS = {
    19: "2017", 20: "2018", 21: "2019", 22: "2020", 23: "2021",
    24: "2022", 25: "2023", 26: "2024", 27: "2025", 28: "2026",
}


def _version_label(version: int) -> str:
    year = _VERSION_YEAR_LABELS.get(version)
    return f"CorelDRAW {year} (v{version})" if year else f"versão {version}"


class VersionConverterPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._input_path = None

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(28, 20))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Conversor de Versão").pack(anchor="w")
        ctk.CTkLabel(
            header, text="Abre um arquivo CorelDRAW, mostra a versão dele, e salva uma cópia convertida "
                         "pra outra versão (pra abrir num computador com CorelDRAW mais antigo).",
            font=ctk.CTkFont(size=12), text_color="gray50", wraplength=560, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        card = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray92", "gray17"))
        card.pack(fill="x", padx=28, pady=8)

        gui_theme.primary_button(
            card, text="+ Importar arquivo (.cdr)", command=self._pick_file,
        ).pack(anchor="w", padx=20, pady=(20, 8))

        self.detected_label = ctk.CTkLabel(
            card, text="Nenhum arquivo escolhido ainda.", font=ctk.CTkFont(size=13), text_color="gray50",
        )
        self.detected_label.pack(anchor="w", padx=20, pady=(0, 16))

        ctk.CTkLabel(card, text="Converter para:", font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", padx=20)

        # The FULL range down to 15 (matching CorelDRAW's own "Salvar como"
        # version dropdown -- confirmed live it offers every version back
        # to 15.0, not just whatever's installed), capped above at the
        # highest version actually installed here: get_installed_versions()
        # is only ever a proxy for "which ProgID this machine can launch",
        # completely unrelated to which legacy FILE FORMATS the Save As
        # dialog can write -- using it as the choice LIST itself (instead
        # of just its max as the upper bound) was the bug that made this
        # dropdown show only one option instead of a real range to convert
        # down to.
        installed = coreldraw_service.get_installed_versions()
        highest_installed = max(installed) if installed else 27
        self._version_choices = list(range(highest_installed, 14, -1))
        labels = [_version_label(v) for v in self._version_choices]
        self.version_var = ctk.StringVar(value=labels[0] if labels else "")
        ctk.CTkComboBox(
            card, values=labels, variable=self.version_var, width=280, state="readonly",
        ).pack(anchor="w", padx=20, pady=(4, 16))

        self.convert_button = gui_theme.primary_button(
            card, text="Converter e Salvar", command=self._convert, state="disabled",
        )
        self.convert_button.pack(anchor="w", padx=20, pady=(0, 20))

        self.log_panel = gui_worker.LogPanel(self)
        self.log_panel.pack(fill="x", padx=28, pady=(0, 20))

    def on_show(self):
        pass

    def _pick_file(self):
        path = file_picker.pick_cdr_file()
        if not path:
            return
        self._input_path = path

        try:
            detected_version = master_artwork.detect_cdr_app_version(path)
        except Exception:
            detected_version = None

        filename = path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        if detected_version is not None:
            self.detected_label.configure(
                text=f"\"{filename}\" -- versão detectada: {_version_label(detected_version)}.",
                text_color=("gray20", "gray85"),
            )
        else:
            self.detected_label.configure(
                text=f"\"{filename}\" -- não consegui detectar a versão exata (formato antigo do CorelDRAW). "
                     f"Ainda pode escolher a versão de destino e converter normalmente.",
                text_color="gray50",
            )
        self.convert_button.configure(state="normal")

    def _convert(self):
        if not self._input_path:
            return
        label_to_version = dict(zip([_version_label(v) for v in self._version_choices], self._version_choices))
        target_version = label_to_version.get(self.version_var.get())
        if target_version is None:
            gui_theme.show_message(self.app, "Escolha inválida", "Escolha uma versão de destino na lista.")
            return

        default_name = "convertido.cdr"
        save_path = file_picker.pick_save_path(default_name)
        if not save_path:
            return

        self.log_panel.show("Convertendo...\n\n")

        def task():
            pa.do_convert_cdr_version(self._input_path, save_path, target_version)

        def on_success(_result):
            self.log_panel.hide_after()
            gui_theme.show_message(self.app, "Convertido", f"Arquivo salvo em:\n{save_path}")

        def on_error(ex):
            gui_theme.show_message(self.app, "Erro ao converter", str(ex))

        gui_worker.run_task(
            self.app, task, on_log=self.log_panel.append, on_success=on_success, on_error=on_error)
