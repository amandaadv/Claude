"""Runs a slow action (CorelDRAW automation, catalog import, website calls) on a
background thread so the GUI never freezes, while streaming its print() output
back to a log panel on the main thread -- Tk widgets can only be touched safely
from the thread running mainloop(), so everything crosses back via `app.after`.
"""
import contextlib
import io
import queue
import threading
import traceback

import pythoncom
import customtkinter as ctk


class _QueueWriter(io.TextIOBase):
    def __init__(self, target_queue):
        self._queue = target_queue

    def write(self, text):
        if text:
            self._queue.put(text)
        return len(text)

    def flush(self):
        pass


def run_task(app, fn, on_success=None, on_error=None, on_log=None):
    """fn is called with no arguments on a worker thread (COM-initialized for
    CorelDRAW automation). Its print() output is forwarded to on_log(str) as it
    happens; on_success(result) or on_error(exception) fires once, back on the
    main thread, when it finishes."""
    log_queue = queue.Queue()
    state = {"thread": None}

    def worker():
        pythoncom.CoInitialize()
        try:
            writer = _QueueWriter(log_queue)
            with contextlib.redirect_stdout(writer):
                result = fn()
            if on_success:
                app.after(0, lambda: on_success(result))
        except Exception as ex:
            log_queue.put(f"\nERRO: {ex}\n{traceback.format_exc()}\n")
            if on_error:
                # `except ... as ex` auto-deletes `ex` once this block ends,
                # but the lambda only runs later via app.after() -- capture
                # it as a default argument so it survives past that point.
                app.after(0, lambda ex=ex: on_error(ex))
        finally:
            pythoncom.CoUninitialize()

    def poll():
        try:
            while True:
                chunk = log_queue.get_nowait()
                if on_log:
                    on_log(chunk)
        except queue.Empty:
            pass
        if state["thread"].is_alive() or not log_queue.empty():
            app.after(80, poll)

    thread = threading.Thread(target=worker, daemon=True)
    state["thread"] = thread
    thread.start()
    app.after(80, poll)


class LogPanel(ctk.CTkFrame):
    """A collapsible read-only text box for showing an operation's progress
    output. Stays invisible (zero height) until show() is first called."""
    def __init__(self, master):
        # height=1: CTkFrame defaults to a 200px-tall canvas even with zero
        # packed children, so left at the default this frame silently ate
        # 200px of its parent row's height at all times -- not just while
        # visible -- starving whatever else shared that row (e.g. a
        # scrollable list above it) of real estate it should have had.
        super().__init__(master, fg_color="transparent", height=1)
        self.textbox = ctk.CTkTextbox(
            self, height=130, font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=("gray95", "gray14"), corner_radius=8)
        self.textbox.configure(state="disabled")
        self._visible = False

    def show(self, initial_text=""):
        if not self._visible:
            self.textbox.pack(fill="x")
            self._visible = True
        self.clear()
        if initial_text:
            self.append(initial_text)

    def hide(self):
        if self._visible:
            self.textbox.pack_forget()
            self._visible = False

    def hide_after(self, delay_ms=4000):
        """Auto-collapses the log a little after a successful operation --
        otherwise the last run's text just sits there forever, looking like
        stale/broken output even though the page above already refreshed."""
        self.after(delay_ms, self.hide)

    def clear(self):
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")

    def append(self, text):
        self.textbox.configure(state="normal")
        self.textbox.insert("end", text)
        self.textbox.see("end")
        self.textbox.configure(state="disabled")
