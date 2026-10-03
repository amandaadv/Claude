"""Shared "WebPedido" button behavior: generates (or reuses, if this client
already has one) the read-only "meu pedido" link and opens it straight in
the browser. Used by both the pending-orders list (gui_page_website.py) and
Fila de Produção / "Produções anteriores" (gui_page_queue.py), so the two
can never drift apart.

Two kinds of link (see pa.py):
- pending orders (production_id=None): the page MERGES every order of the
  same client (same nome+telefone) -- pa.do_create_pedido_link.
- a past production (production_id=N): the page shows exactly what that
  production produced -- pa.do_create_pedido_link_for_production.
"""
import webbrowser

import gui_theme
import gui_worker
import pa


def make_button(master, page, nome, telefone, width=110, height=30, production_id=None):
    """Returns an unpacked WebPedido button (caller places it). `page` is any
    widget with .app and the Tk after method (the owning page)."""
    button = gui_theme.secondary_button(master, text="WebPedido", width=width, height=height)
    button.configure(command=lambda: open_link(page, button, nome, telefone, production_id))
    return button


def open_link(page, button, nome, telefone, production_id=None):
    """Only feedback is the button's own label ("Abrindo..." -> restores),
    an error still gets a popup so a failed open is never mistaken for a
    successful one. The one other popup: a production link whose figures
    aren't all published on the site -- those would be missing from the
    page, which is exactly the kind of mismatch worth saying out loud."""
    original_text = button.cget("text")
    button.configure(text="Abrindo...", state="disabled")

    def restore():
        try:
            button.configure(text=original_text, state="normal")
        except Exception:
            pass  # list was refreshed and this button no longer exists

    def task():
        if production_id is not None:
            return pa.do_create_pedido_link_for_production(production_id)
        return pa.do_create_pedido_link(nome, telefone), [], 0

    def on_success(result):
        link, missing, missing_total = result
        webbrowser.open(link)
        restore()
        if missing_total:
            shown = "\n".join(f"• {item}" for item in missing[:15])
            more = f"\n… e mais {missing_total - 15}" if missing_total > 15 else ""
            gui_theme.show_message(
                page.app, "Pedido aberto, mas faltam figuras",
                f"A página abriu, porém {missing_total} figura(s) dessa produção não estão publicadas "
                f"no site e NÃO aparecem nela:\n\n{shown}{more}\n\n"
                f"Publique o catálogo no site pra elas aparecerem.")

    def on_error(ex):
        restore()
        gui_theme.show_message(page.app, "Erro ao gerar link", str(ex))

    gui_worker.run_task(page.app, task, on_success=on_success, on_error=on_error)
