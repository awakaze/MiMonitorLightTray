"""Modal dialogs whose button captions follow the application's language."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .i18n import FONT, t


def _show(title: str, message: str, *, parent: tk.Misc | None = None,
          question: bool = False) -> bool:
    owns_root = parent is None and tk._default_root is None
    if owns_root:
        parent = tk.Tk()
        parent.withdraw()
    parent = parent or tk._default_root
    previous_grab = parent.grab_current()
    window = tk.Toplevel(parent)
    window.withdraw()
    window.title(title)
    window.resizable(False, False)
    if parent.winfo_viewable():
        window.transient(parent)
    result = [False]

    def close(value=False):
        result[0] = value
        window.destroy()

    body = ttk.Frame(window, padding=20)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text=message, wraplength=560, justify="left",
              font=(FONT, 10)).pack(fill="x", pady=(0, 18))
    buttons = ttk.Frame(body)
    buttons.pack(anchor="e")
    if question:
        primary = ttk.Button(buttons, text=t("Yes"), command=lambda: close(True))
        primary.pack(side="left", padx=4)
        ttk.Button(buttons, text=t("No"), command=close).pack(side="left", padx=4)
    else:
        primary = ttk.Button(buttons, text=t("OK"), command=lambda: close(True))
        primary.pack(side="left")
    window.protocol("WM_DELETE_WINDOW", close)
    window.bind("<Escape>", lambda _e: close())

    def enter(_event):
        focused = window.focus_get()
        if isinstance(focused, ttk.Button) and focused.winfo_toplevel() == window:
            focused.invoke()
        else:
            primary.invoke()
        return "break"

    window.bind("<Return>", enter)
    window.update_idletasks()
    width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    x = (window.winfo_screenwidth() - width) // 2
    y = (window.winfo_screenheight() - height) // 2
    window.geometry(f"+{max(0, x)}+{max(0, y)}")
    window.deiconify()
    window.grab_set()
    primary.focus_set()
    window.wait_window()
    if previous_grab is not None and previous_grab.winfo_exists():
        previous_grab.grab_set()
    if owns_root:
        parent.destroy()
    return result[0]


def showinfo(title: str, message: str, *, parent: tk.Misc | None = None) -> None:
    _show(title, message, parent=parent)


def showwarning(title: str, message: str, *, parent: tk.Misc | None = None) -> None:
    _show(title, message, parent=parent)


def showerror(title: str, message: str, *, parent: tk.Misc | None = None) -> None:
    _show(title, message, parent=parent)


def askyesno(title: str, message: str, *, parent: tk.Misc | None = None) -> bool:
    return _show(title, message, parent=parent, question=True)
