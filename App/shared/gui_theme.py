"""Shared look-and-feel constants and small reusable dialogs for the desktop
GUI. Colors match the customer-facing website (babyluzconfeccao.com.br) so
the desktop app and the site feel like the same product.
"""
import customtkinter as ctk

# Passed to every ctk.CTkScrollableFrame(...) call so the scrollbar blends
# into the page background instead of showing as a thick gray bar -- mouse
# wheel and dragging still work, it just doesn't stand out visually.
SCROLLBAR_KWARGS = dict(
    scrollbar_fg_color="transparent",
    # Visibly darker/lighter than the page and card backgrounds (both are
    # gray92/gray14-ish) so the thumb is actually visible to click-and-drag,
    # not just usable by mouse wheel.
    scrollbar_button_color=("gray65", "gray40"),
    scrollbar_button_hover_color=("gray50", "gray55"),
)


def center_over_master(toplevel, master, width, height):
    """Popups otherwise land wherever the OS feels like (often a corner) --
    this centers a dialog over the main window instead, so it reads as part
    of the app rather than a stray window."""
    master.update_idletasks()
    x = master.winfo_rootx() + (master.winfo_width() - width) // 2
    y = master.winfo_rooty() + (master.winfo_height() - height) // 2
    toplevel.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")

ACCENT = "#ff8fab"        # rosa (site: --rosa)
ACCENT_HOVER = "#e0607f"  # rosa escuro (site: --rosa-escuro)
ACCENT_BLUE = "#8ecae6"   # azul (site: --azul)
ACCENT_BLUE_HOVER = "#6ba3c4"
ACCENT_PURPLE = "#b185db"
ACCENT_PURPLE_HOVER = "#9a6bc4"
ACCENT_MINT = "#7fd8b8"
ACCENT_MINT_HOVER = "#5fb897"
ACCENT_SLATE = "#a0aec0"
ACCENT_SLATE_HOVER = "#8291ab"
DANGER = "#c0392b"
DANGER_HOVER = "#922b21"


def primary_button(master, **kwargs):
    defaults = dict(
        fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="white",
        font=ctk.CTkFont(size=13, weight="bold"), corner_radius=8, height=36)
    defaults.update(kwargs)
    return ctk.CTkButton(master, **defaults)


def secondary_button(master, **kwargs):
    defaults = dict(
        fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER, text_color="#1a1a1f",
        font=ctk.CTkFont(size=13, weight="bold"), corner_radius=8, height=36)
    defaults.update(kwargs)
    return ctk.CTkButton(master, **defaults)


def danger_button(master, **kwargs):
    defaults = dict(
        fg_color=DANGER, hover_color=DANGER_HOVER, text_color="white",
        font=ctk.CTkFont(size=13, weight="bold"), corner_radius=8, height=36)
    defaults.update(kwargs)
    return ctk.CTkButton(master, **defaults)


def card_button(master, icon, text, command, color=ACCENT, hover_color=ACCENT_HOVER,
                 text_color="white", width=150, height=86):
    """A small clickable card (icon over label) -- same look as the Início
    page's big cards, sized for a header/toolbar. Built as a plain frame with
    manual click/hover bindings rather than a CTkButton: a CTkButton with
    child widgets placed on top of it shows an ugly mismatched-background
    flash on click/hover, since the overlay's "transparent" doesn't resolve
    to the button's own color."""
    card = ctk.CTkFrame(master, fg_color=color, corner_radius=12, width=width, height=height)
    card.grid_propagate(False)
    card.pack_propagate(False)

    content = ctk.CTkFrame(card, fg_color="transparent")
    content.place(relx=0.5, rely=0.5, anchor="center")
    ctk.CTkLabel(content, text=icon, font=ctk.CTkFont(size=22), text_color=text_color).pack()
    ctk.CTkLabel(content, text=text, font=ctk.CTkFont(size=12, weight="bold"), text_color=text_color,
                 wraplength=width - 16, justify="center").pack(pady=(2, 0))

    def on_enter(_event=None):
        card.configure(fg_color=hover_color)

    def on_leave(_event=None):
        card.configure(fg_color=color)

    for widget in [card, content] + content.winfo_children():
        widget.configure(cursor="hand2")
        widget.bind("<Button-1>", lambda _e: command())
        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)

    return card


STATUS_PILL_COLORS = {
    "Ready": ("#e4f8ea", "#1e8a4c"),
    "Processing": ("#fff3d6", "#a1720a"),
    "Failed": ("#fde3e3", DANGER_HOVER),
}


def pill(master, text, bg="#f3ecfb", fg="#7a4fb0"):
    return ctk.CTkLabel(
        master, text=text, font=ctk.CTkFont(size=11, weight="bold"),
        fg_color=bg, text_color=fg, corner_radius=10, height=22, padx=10)


def status_pill(master, status):
    bg, fg = STATUS_PILL_COLORS.get(status, ("#eef1f6", "#5a6472"))
    return pill(master, f"● {status}", bg, fg)


def back_button(master, app, text="← Início"):
    return ctk.CTkButton(
        master, text=text, fg_color="gray40", hover_color="gray30",
        font=ctk.CTkFont(size=13, weight="bold"), corner_radius=8, height=36, width=110,
        command=lambda: app.show_page("home"))


def section_title(master, text):
    return ctk.CTkLabel(master, text=text, font=ctk.CTkFont(size=20, weight="bold"), anchor="w")


class ConfirmDialog(ctk.CTkToplevel):
    def __init__(self, master, title, message, confirm_text="Confirmar", danger=False):
        super().__init__(master)
        self.title(title)
        center_over_master(self, master, 420, 190)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.result = False

        ctk.CTkLabel(self, text=message, wraplength=380, justify="left", font=ctk.CTkFont(size=13)).pack(
            padx=24, pady=(28, 20), fill="both", expand=True)

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=(0, 20))
        ctk.CTkButton(button_row, text="Cancelar", fg_color="gray40", hover_color="gray30",
                      width=110, command=self._cancel).pack(side="left", padx=8)
        button = danger_button if danger else primary_button
        button(button_row, text=confirm_text, width=110, command=self._confirm).pack(side="left", padx=8)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Return>", lambda _e: self._confirm())
        self.bind("<Escape>", lambda _e: self._cancel())

    def _confirm(self):
        self.result = True
        self.destroy()

    def _cancel(self):
        self.result = False
        self.destroy()


def ask_confirm(master, title, message, confirm_text="Confirmar", danger=False) -> bool:
    dialog = ConfirmDialog(master, title, message, confirm_text, danger)
    master.wait_window(dialog)
    return dialog.result


class MessageDialog(ctk.CTkToplevel):
    def __init__(self, master, title, message):
        super().__init__(master)
        self.title(title)
        center_over_master(self, master, 380, 170)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        ctk.CTkLabel(self, text=message, wraplength=340, justify="left", font=ctk.CTkFont(size=13)).pack(
            padx=24, pady=(28, 16), fill="both", expand=True)
        primary_button(self, text="OK", width=100, command=self.destroy).pack(pady=(0, 20))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Return>", lambda _e: self.destroy())
        self.bind("<Escape>", lambda _e: self.destroy())


def show_message(master, title, message) -> None:
    dialog = MessageDialog(master, title, message)
    master.wait_window(dialog)


class ErrorDialog(ctk.CTkToplevel):
    """Como MessageDialog, mas pra erro técnico (ex: o que o CorelDRAW devolveu quando uma
    produção falha): fica aberta até fechar manualmente (nunca some sozinha, diferente do painel
    de log que se auto-esconde) e tem um botão "Copiar erro" -- selecionar texto arrastando o
    mouse num CTkLabel não funciona, então copiar era a única forma confiável de levar o erro pra
    outro lugar (ex: colar aqui pro Claude ler)."""
    def __init__(self, master, title, message):
        super().__init__(master)
        self.title(title)
        center_over_master(self, master, 480, 320)
        self.minsize(360, 220)
        self.transient(master)
        self.grab_set()

        box = ctk.CTkTextbox(
            self, font=ctk.CTkFont(family="Consolas", size=12), fg_color=("gray95", "gray14"), corner_radius=8)
        box.pack(padx=20, pady=(20, 10), fill="both", expand=True)
        box.insert("1.0", message)
        box.configure(state="disabled")

        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(pady=(0, 20))

        def copiar():
            self.clipboard_clear()
            self.clipboard_append(message)
            copiar_btn.configure(text="Copiado ✓")
            self.after(1500, lambda: copiar_btn.configure(text="Copiar erro"))

        copiar_btn = secondary_button(botoes, text="Copiar erro", width=140, command=copiar)
        copiar_btn.pack(side="left", padx=(0, 8))
        primary_button(botoes, text="Fechar", width=100, command=self.destroy).pack(side="left")

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _e: self.destroy())


def show_error_message(master, title, message) -> None:
    dialog = ErrorDialog(master, title, message)
    master.wait_window(dialog)


class ReportDialog(ctk.CTkToplevel):
    """Like MessageDialog, but for a result that's a LIST of REFs instead of
    a sentence -- MessageDialog's fixed 380x170 box just clips a long
    "; ".join(skipped_refs) string with no scrollbar (the wall-of-text popup
    "Montar Pedido" used to show), impossible to actually read which REFs
    made it in and which didn't. This is resizable, scrolls, and splits the
    two outcomes into their own clearly labeled, colored sections instead of
    one paragraph."""
    def __init__(self, master, title, summary, ok_label, ok_items, problem_label, problem_items):
        super().__init__(master)
        self.title(title)
        center_over_master(self, master, 460, 520)
        self.minsize(360, 300)
        self.transient(master)
        self.grab_set()

        ctk.CTkLabel(
            self, text=summary, font=ctk.CTkFont(size=14, weight="bold"), wraplength=420,
            justify="left",
        ).pack(padx=20, pady=(20, 10), anchor="w")

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", **SCROLLBAR_KWARGS)
        scroll.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        if ok_items:
            ctk.CTkLabel(
                scroll, text=f"✅ {ok_label} ({len(ok_items)})",
                font=ctk.CTkFont(size=13, weight="bold"), text_color=ACCENT_MINT,
            ).pack(anchor="w", pady=(0, 4))
            for item in ok_items:
                ctk.CTkLabel(
                    scroll, text=f"  {item}", font=ctk.CTkFont(size=12), text_color="gray70",
                    wraplength=400, justify="left", anchor="w",
                ).pack(anchor="w")

        if problem_items:
            ctk.CTkLabel(
                scroll, text=f"❌ {problem_label} ({len(problem_items)})",
                font=ctk.CTkFont(size=13, weight="bold"), text_color=DANGER,
                anchor="w",
            ).pack(anchor="w", pady=(14 if ok_items else 0, 4))
            for item in problem_items:
                ctk.CTkLabel(
                    scroll, text=f"  {item}", font=ctk.CTkFont(size=12), text_color="gray70",
                    wraplength=400, justify="left", anchor="w",
                ).pack(anchor="w")

        primary_button(self, text="OK", width=100, command=self.destroy).pack(pady=(0, 20))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _e: self.destroy())


def show_ref_report(master, title, summary, ok_label, ok_items, problem_label, problem_items) -> None:
    dialog = ReportDialog(master, title, summary, ok_label, ok_items, problem_label, problem_items)
    master.wait_window(dialog)


class SizeDialog(ctk.CTkToplevel):
    """Asks for one piece's width/height in mm -- used wherever a REF has no
    size locked by the master file and a manual value is required. When
    catalog_name is given, offers to remember this size for the whole
    catalog so it's never asked again for that catalog's other pieces."""
    def __init__(self, master, title, subtitle="", catalog_name=None, initial_size=None):
        super().__init__(master)
        self.title(title)
        # Generous fixed height: CTkToplevel doesn't auto-grow to fit packed
        # content, so a longer subtitle (this dialog's callers often pass
        # 2-line explanations) can silently push the Confirmar/Pular buttons
        # below the window's visible bottom edge -- looks like the dialog is
        # just broken/unresponsive, since there's nothing left to click.
        center_over_master(self, master, 380, 400 if catalog_name else 340)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.result = None

        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=16, weight="bold"), wraplength=330,
                     justify="left").pack(pady=(24, 4), padx=24, anchor="w")
        if subtitle:
            ctk.CTkLabel(self, text=subtitle, font=ctk.CTkFont(size=12), text_color="gray60",
                         wraplength=330, justify="left").pack(padx=24, anchor="w", pady=(0, 12))

        # Height asked (and shown) before width -- the width_entry/height_entry
        # names and the (width_mm, height_mm, ...) result order stay as they
        # were, only the on-screen order changed, so every existing caller
        # that unpacks the result keeps working unmodified.
        ctk.CTkLabel(self, text="Altura de UMA peça (mm):").pack(padx=24, anchor="w")
        self.height_entry = ctk.CTkEntry(self, placeholder_text="ex: 90")
        self.height_entry.pack(padx=24, pady=(2, 12), fill="x")

        ctk.CTkLabel(self, text="Largura de UMA peça (mm):").pack(padx=24, anchor="w")
        self.width_entry = ctk.CTkEntry(self, placeholder_text="ex: 90")
        self.width_entry.pack(padx=24, pady=(2, 16), fill="x")

        if initial_size:
            self.width_entry.insert(0, str(initial_size[0]))
            self.height_entry.insert(0, str(initial_size[1]))

        # Desmarcado por padrão -- isso aplica o tamanho digitado a TODO o catálogo, não só à peça
        # que está na tela. Vinha marcado sempre que catalog_name existia (ou seja, quase sempre),
        # então um "Confirmar" mais rápido (ex: corrigindo uma peça achada na Busca de Produto)
        # aplicava o tamanho errado a todo o catálogo por engano.
        self.apply_to_catalog_var = ctk.BooleanVar(value=False)
        if catalog_name:
            # CTkCheckBox doesn't support wraplength/justify (passing them
            # raises ValueError, which Tkinter's default callback handler
            # swallows -- silently aborting __init__() right here, before the
            # buttons below ever get created). The explanation goes in a
            # separate CTkLabel (which does wrap); the checkbox itself stays
            # short enough to never need wrapping.
            ctk.CTkLabel(
                self, text=f"Usar esse tamanho pra todas as peças de \"{catalog_name}\" (não perguntar de novo):",
                font=ctk.CTkFont(size=11), text_color="gray60", wraplength=330, justify="left",
            ).pack(padx=24, pady=(0, 4), anchor="w")
            ctk.CTkCheckBox(
                self, variable=self.apply_to_catalog_var, text="Aplicar a todo o catálogo",
                font=ctk.CTkFont(size=11),
            ).pack(padx=24, pady=(0, 12), anchor="w")

        self.error_label = ctk.CTkLabel(self, text="", text_color=DANGER, font=ctk.CTkFont(size=11))
        self.error_label.pack(padx=24, anchor="w")

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=(4, 20))
        ctk.CTkButton(button_row, text="Pular", fg_color="gray40", hover_color="gray30",
                      width=100, command=self._skip).pack(side="left", padx=6)
        primary_button(button_row, text="Confirmar", width=120, command=self._confirm).pack(side="left", padx=6)

        self.protocol("WM_DELETE_WINDOW", self._skip)
        self.bind("<Return>", lambda _e: self._confirm())
        self.bind("<Escape>", lambda _e: self._skip())
        self.height_entry.focus()

    def _confirm(self):
        try:
            width_mm = float(self.width_entry.get().strip().replace(",", "."))
            height_mm = float(self.height_entry.get().strip().replace(",", "."))
            if width_mm <= 0 or height_mm <= 0:
                raise ValueError
        except ValueError:
            self.error_label.configure(text="Informe dois números positivos.")
            return
        self.result = (width_mm, height_mm, self.apply_to_catalog_var.get())
        self.destroy()

    def _skip(self):
        self.result = None
        self.destroy()


def ask_size(master, title, subtitle="", catalog_name=None, initial_size=None):
    """Returns (width_mm, height_mm, apply_to_whole_catalog) or None if skipped."""
    dialog = SizeDialog(master, title, subtitle, catalog_name, initial_size)
    master.wait_window(dialog)
    return dialog.result


class ChoiceDialog(ctk.CTkToplevel):
    def __init__(self, master, title, message, choices, default_index=0):
        super().__init__(master)
        self.title(title)
        center_over_master(self, master, 380, 260)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.result = None
        self._choices = choices

        ctk.CTkLabel(self, text=message, wraplength=340, justify="left", font=ctk.CTkFont(size=13)).pack(
            padx=24, pady=(24, 12), anchor="w")

        labels = [label for label, _ in choices]
        self.var = ctk.StringVar(value=labels[default_index])
        ctk.CTkComboBox(self, values=labels, variable=self.var, width=320).pack(padx=24, pady=(0, 20))

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=(0, 20))
        ctk.CTkButton(button_row, text="Cancelar", fg_color="gray40", hover_color="gray30",
                      width=100, command=self._cancel).pack(side="left", padx=6)
        primary_button(button_row, text="Confirmar", width=120, command=self._confirm).pack(side="left", padx=6)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Return>", lambda _e: self._confirm())
        self.bind("<Escape>", lambda _e: self._cancel())

    def _confirm(self):
        selected_label = self.var.get()
        for label, value in self._choices:
            if label == selected_label:
                self.result = value
                break
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def ask_choice(master, title, message, choices, default_index=0):
    dialog = ChoiceDialog(master, title, message, choices, default_index)
    master.wait_window(dialog)
    return dialog.result


class SizeOverrideChoiceDialog(ctk.CTkToplevel):
    """"Usar tamanho original do catálogo" vs "Mudar a medida" -- the second
    option asks for just ONE number (the longer side of every piece; the
    shorter side scales along with it to keep each piece's own aspect
    ratio), same rule gerador_catalogos.py's batch-apply already uses."""

    def __init__(self, master, title, message="", use_order_measure=False):
        super().__init__(master)
        self.title(title)
        center_over_master(self, master, 380, 320)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.result = None

        if message:
            ctk.CTkLabel(self, text=message, wraplength=330, justify="left", font=ctk.CTkFont(size=13)).pack(
                padx=24, pady=(24, 14), anchor="w")

        self.modo_var = ctk.StringVar(value="original")
        ctk.CTkRadioButton(
            self, text=("Usar a medida do pedido (a que a cliente escolheu)" if use_order_measure
                        else "Usar tamanho original do catálogo"),
            variable=self.modo_var, value="original",
            command=self._on_modo_changed,
        ).pack(padx=24, pady=(0, 10), anchor="w")
        ctk.CTkRadioButton(
            self, text="Mudar a medida de TODAS as peças" if use_order_measure else "Mudar a medida",
            variable=self.modo_var, value="override",
            command=self._on_modo_changed,
        ).pack(padx=24, pady=(0, 6), anchor="w")

        ctk.CTkLabel(
            self, text="Medida do lado maior de CADA peça (mm) -- o lado menor ajusta sozinho, mantendo a proporção:",
            font=ctk.CTkFont(size=11), text_color="gray60", wraplength=330, justify="left",
        ).pack(padx=24, pady=(2, 4), anchor="w")
        self.entry = ctk.CTkEntry(self, placeholder_text="ex: 90")
        self.entry.pack(padx=24, pady=(0, 8), fill="x")
        self._on_modo_changed()

        self.error_label = ctk.CTkLabel(self, text="", text_color=DANGER, font=ctk.CTkFont(size=11))
        self.error_label.pack(padx=24, anchor="w")

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=(6, 20))
        ctk.CTkButton(button_row, text="Cancelar", fg_color="gray40", hover_color="gray30",
                      width=100, command=self._cancel).pack(side="left", padx=6)
        primary_button(button_row, text="Confirmar", width=120, command=self._confirm).pack(side="left", padx=6)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Return>", lambda _e: self._confirm())
        self.bind("<Escape>", lambda _e: self._cancel())

    def _on_modo_changed(self):
        self.entry.configure(state="normal" if self.modo_var.get() == "override" else "disabled")

    def _confirm(self):
        if self.modo_var.get() == "original":
            self.result = ("original", None)
            self.destroy()
            return
        try:
            value_mm = float(self.entry.get().strip().replace(",", "."))
            if value_mm <= 0:
                raise ValueError
        except ValueError:
            self.error_label.configure(text="Informe um número positivo (em mm).")
            return
        self.result = ("override", value_mm)
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def ask_size_override_choice(master, title, message="", use_order_measure=False):
    """Returns (mode, value) where mode is "original" (value None) or
    "override" (value the target mm for every piece's longer side), or
    None if cancelled."""
    dialog = SizeOverrideChoiceDialog(master, title, message, use_order_measure)
    master.wait_window(dialog)
    return dialog.result


class CopiesPerRowDialog(ctk.CTkToplevel):
    """Asks how many copies of each figure per row: "automático" (None)
    or a specific integer -- same pattern as SizeOverrideChoiceDialog."""

    def __init__(self, master):
        super().__init__(master)
        self.title("Figuras por linha")
        center_over_master(self, master, 380, 290)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.result = None

        ctk.CTkLabel(
            self, text="Quantas cópias de cada figura por linha?",
            wraplength=330, justify="left", font=ctk.CTkFont(size=13),
        ).pack(padx=24, pady=(24, 14), anchor="w")

        self.modo_var = ctk.StringVar(value="auto")
        ctk.CTkRadioButton(
            self, text="Automático (preencher a linha com o que couber)", variable=self.modo_var, value="auto",
            command=self._on_modo_changed,
        ).pack(padx=24, pady=(0, 10), anchor="w")
        ctk.CTkRadioButton(
            self, text="Número fixo de cópias por figura", variable=self.modo_var, value="fixed",
            command=self._on_modo_changed,
        ).pack(padx=24, pady=(0, 6), anchor="w")

        ctk.CTkLabel(
            self, text="Cópias por figura (coloca exatamente esse número de cada figura; a linha continua sendo preenchida pela próxima figura quando sobrar espaço):",
            font=ctk.CTkFont(size=11), text_color="gray60", wraplength=330, justify="left",
        ).pack(padx=24, pady=(2, 4), anchor="w")
        self.entry = ctk.CTkEntry(self, placeholder_text="ex: 3")
        self.entry.pack(padx=24, pady=(0, 8), fill="x")
        self._on_modo_changed()

        self.error_label = ctk.CTkLabel(self, text="", text_color=DANGER, font=ctk.CTkFont(size=11))
        self.error_label.pack(padx=24, anchor="w")

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=(6, 20))
        ctk.CTkButton(button_row, text="Cancelar", fg_color="gray40", hover_color="gray30",
                      width=100, command=self._cancel).pack(side="left", padx=6)
        primary_button(button_row, text="Confirmar", width=120, command=self._confirm).pack(side="left", padx=6)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Return>", lambda _e: self._confirm())
        self.bind("<Escape>", lambda _e: self._cancel())

    def _on_modo_changed(self):
        self.entry.configure(state="normal" if self.modo_var.get() == "fixed" else "disabled")

    def _confirm(self):
        if self.modo_var.get() == "auto":
            self.result = None
            self.destroy()
            return
        try:
            n = int(self.entry.get().strip())
            if n < 1:
                raise ValueError
        except ValueError:
            self.error_label.configure(text="Informe um número inteiro positivo (ex: 3).")
            return
        self.result = n
        self.destroy()

    def _cancel(self):
        self.result = "cancelled"
        self.destroy()


def ask_copies_per_row(master) -> int | None | str:
    """Returns an int (fixed copies per row), None (automatic), or the
    string "cancelled" if the user closed the dialog."""
    dialog = CopiesPerRowDialog(master)
    master.wait_window(dialog)
    return dialog.result


class TextInputDialog(ctk.CTkToplevel):
    def __init__(self, master, title, message, placeholder="", default=""):
        super().__init__(master)
        self.title(title)
        center_over_master(self, master, 380, 230)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.result = None

        ctk.CTkLabel(self, text=message, wraplength=330, justify="left", font=ctk.CTkFont(size=13)).pack(
            padx=24, pady=(24, 10), anchor="w")
        self.entry = ctk.CTkEntry(self, placeholder_text=placeholder)
        if default:
            self.entry.insert(0, default)
        self.entry.pack(padx=24, pady=(0, 16), fill="x")

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=(0, 20))
        ctk.CTkButton(button_row, text="Cancelar", fg_color="gray40", hover_color="gray30",
                      width=110, command=self._cancel).pack(side="left", padx=8)
        primary_button(button_row, text="Confirmar", width=110, command=self._confirm).pack(side="left", padx=8)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Return>", lambda _e: self._confirm())
        self.bind("<Escape>", lambda _e: self._cancel())
        self.entry.focus()

    def _confirm(self):
        self.result = self.entry.get().strip()
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def ask_text(master, title, message, placeholder="", default=""):
    dialog = TextInputDialog(master, title, message, placeholder, default)
    master.wait_window(dialog)
    return dialog.result
