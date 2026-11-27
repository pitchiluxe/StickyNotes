from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, simpledialog
from tkinter import ttk


def _app_data_dir() -> Path:
    base = os.getenv("APPDATA")
    if base:
        return Path(base) / "StickyNotes"
    return Path.home() / ".stickynotes"


def _safe_alpha(window: tk.Tk | tk.Toplevel, alpha: float) -> bool:
    try:
        window.attributes("-alpha", alpha)
        return True
    except tk.TclError:
        return False


def _fade_in(window: tk.Tk | tk.Toplevel, ms: int = 160, steps: int = 10) -> None:
    if steps <= 0:
        return
    if not _safe_alpha(window, 0.0):
        return
    step_ms = max(1, ms // steps)

    def tick(i: int) -> None:
        _safe_alpha(window, min(1.0, i / steps))
        if i < steps:
            window.after(step_ms, tick, i + 1)

    window.after(0, tick, 0)


def _fade_out_destroy(window: tk.Tk | tk.Toplevel, ms: int = 140, steps: int = 10) -> None:
    if steps <= 0:
        window.destroy()
        return
    if not _safe_alpha(window, 1.0):
        window.destroy()
        return
    step_ms = max(1, ms // steps)

    def tick(i: int) -> None:
        _safe_alpha(window, max(0.0, 1.0 - (i / steps)))
        if i < steps:
            window.after(step_ms, tick, i + 1)
        else:
            window.destroy()

    window.after(0, tick, 0)


def _hex_darken(hex_color: str, factor: float = 0.12) -> str:
    c = hex_color.strip()
    if not c.startswith("#") or len(c) != 7:
        return hex_color
    try:
        r = int(c[1:3], 16)
        g = int(c[3:5], 16)
        b = int(c[5:7], 16)
    except ValueError:
        return hex_color
    r = max(0, min(255, int(r * (1.0 - factor))))
    g = max(0, min(255, int(g * (1.0 - factor))))
    b = max(0, min(255, int(b * (1.0 - factor))))
    return f"#{r:02X}{g:02X}{b:02X}"


class StickyNote:
    def __init__(
        self,
        app: StickyNoteApp,
        master: tk.Tk,
        note_id: str | None = None,
        color: str = "#FFF59D",
        title: str = "Sticky Note",
        text: str = "",
        geometry: str | None = None,
        file_path: str | None = None,
        collapsed: bool = False,
        opacity: float = 1.0,
        locked: bool = False,
        always_on_top: bool = False,
        starred: bool = False,
    ) -> None:
        self.app = app
        self.master = master
        self.id = note_id or str(uuid.uuid4())
        self.color = color
        self.title = title
        self.file_path = file_path
        self.collapsed = collapsed
        self.opacity = float(opacity)
        self.locked = bool(locked)
        self.always_on_top = bool(always_on_top)
        self.starred = bool(starred)
        self.hidden = False
        self._drag_origin: tuple[int, int] | None = None
        self._dragged = False
        self._resize_origin: tuple[int, int] | None = None
        self._resize_start_geometry: tuple[int, int, int, int] | None = None
        self._pending_note_save_after_id: str | None = None
        self._expanded_geometry: str | None = None
        self._is_editing_title = False
        self._toggle_after_id: str | None = None
        self._maximize_restore_geometry: str | None = None
        self._maximized = False
        self._normal_minsize: tuple[int, int] = (220, 160)

        self.win = tk.Toplevel(master)
        self.win.title(self.title)

        if geometry:
            self.win.geometry(geometry)
        else:
            self.win.geometry("280x220")
        self.win.minsize(*self._normal_minsize)
        self.win.configure(bg=self.color)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        try:
            self.win.attributes("-topmost", self.always_on_top)
        except tk.TclError:
            pass
        try:
            self.win.overrideredirect(True)
        except tk.TclError:
            pass
        self.set_opacity(self.opacity)

        self._build_menu()
        self._build_ui()
        self.set_color(self.color)
        self.set_text(text)
        self.set_title(self.title)

        if geometry and self.collapsed:
            self._expanded_geometry = geometry
        if self.collapsed:
            self.collapse(initial=True)
        _fade_in(self.win)
        if not geometry:
            self.win.after(0, self._center_on_screen)
        if not self.always_on_top:
            self.win.after(0, self._send_behind_app)

    def _send_behind_app(self) -> None:
        try:
            self.master.lift()
        except tk.TclError:
            pass

        try:
            self.win.lower(self.master)
        except tk.TclError:
            try:
                self.win.lower()
            except tk.TclError:
                pass

    def _center_on_screen(self) -> None:
        try:
            self.win.update_idletasks()
            w = max(220, int(self.win.winfo_width()))
            h = max(160, int(self.win.winfo_height()))
            sw = int(self.win.winfo_screenwidth())
            sh = int(self.win.winfo_screenheight())
        except tk.TclError:
            return

        x = max(0, (sw - w) // 2)
        y = max(40, (sh - h) // 2)
        try:
            self.win.geometry(f"{w}x{h}+{x}+{y}")
        except tk.TclError:
            pass

    def _update_header_buttons(self) -> None:
        return

    def _on_resize_press(self, event: tk.Event) -> None:
        self._resize_origin = (event.x_root, event.y_root)
        geo = self.win.geometry()
        parts = self._geometry_parts(geo)
        if parts:
            self._resize_start_geometry = parts
        else:
            self._resize_start_geometry = None

    def _on_resize_drag(self, event: tk.Event) -> None:
        if self.collapsed:
            return
        if not self._resize_origin or not self._resize_start_geometry:
            return
        _, oy = self._resize_origin
        w, h, x, y = self._resize_start_geometry
        dy = event.y_root - oy
        new_h = max(120, h + dy)
        try:
            self.win.geometry(f"{w}x{new_h}+{x}+{y}")
        except tk.TclError:
            pass
        self.app.request_session_autosave()

    def _build_menu(self) -> None:
        self.always_on_top_var = tk.BooleanVar(value=self.always_on_top)
        self.locked_var = tk.BooleanVar(value=self.locked)
        self.opacity_var = tk.IntVar(value=int(round(self.opacity * 100)))
        self.starred_var = tk.BooleanVar(value=self.starred)

        self.more_menu = tk.Menu(self.win, tearoff=0)
        self.more_menu.add_command(label="New Note", accelerator="Alt+N", command=lambda: self.app.new_note(self.color))

        self.more_menu.add_separator()
        self.more_menu.add_command(label="Load Note...", command=self.load_note)
        self.more_menu.add_command(label="Save Note", command=self.save_note)
        self.more_menu.add_command(label="Export...", command=self.save_note_as)

        self.more_menu.add_separator()
        color_menu = tk.Menu(self.more_menu, tearoff=0)
        color_menu.add_command(label="Palette...", command=self.pick_color)
        self.more_menu.add_cascade(label="Color", menu=color_menu)

        opacity_menu = tk.Menu(self.more_menu, tearoff=0)
        for pct in (100, 90, 80, 70, 60, 50, 40, 30):
            opacity_menu.add_radiobutton(
                label=f"{pct}%",
                variable=self.opacity_var,
                value=pct,
                command=lambda p=pct: self.set_opacity(p / 100.0),
            )
        self.more_menu.add_cascade(label="Opacity", menu=opacity_menu)

        size_menu = tk.Menu(self.more_menu, tearoff=0)
        size_menu.add_command(label="Small", command=lambda: self._set_size_preset("small"))
        size_menu.add_command(label="Medium", command=lambda: self._set_size_preset("medium"))
        size_menu.add_command(label="Large", command=lambda: self._set_size_preset("large"))
        self.more_menu.add_cascade(label="Size", menu=size_menu)

        self.more_menu.add_separator()
        self.more_menu.add_command(label="Alarm...", accelerator="Alt+A", command=self.set_alarm)
        self.more_menu.add_command(label="Edit title", accelerator="F2", command=self._start_title_edit)
        self.more_menu.add_checkbutton(label="Starred", variable=self.starred_var, command=self.toggle_starred)

        self.more_menu.add_separator()
        self.more_menu.add_command(label="Print...", accelerator="Ctrl+P", command=self.print_note)
        self.more_menu.add_command(label="Duplicate", accelerator="Alt+D", command=self.duplicate)
        self.more_menu.add_command(label="Locate in Explorer", command=self.locate_in_explorer)
        self.more_menu.add_command(label="Share", command=self.share_note)
        self.more_menu.add_command(label="Clear", command=self.clear)

        self.more_menu.add_separator()
        self.more_menu.add_checkbutton(label="Always On Top", accelerator="Alt+T", variable=self.always_on_top_var, command=self.toggle_always_on_top)
        self.more_menu.add_checkbutton(label="Lock Note", accelerator="Alt+L", variable=self.locked_var, command=self.toggle_lock)

        self.more_menu.add_separator()
        self.more_menu.add_command(label="Minimize", accelerator="Alt+M", command=self.collapse)
        self.more_menu.add_command(label="Hide", accelerator="Alt+F4", command=self.hide_note)
        self.more_menu.add_command(label="Hide Others", accelerator="Alt+F3", command=self.hide_others)

        move_menu = tk.Menu(self.more_menu, tearoff=0)
        move_menu.add_command(label="Top Left", command=lambda: self.move_to("top_left"))
        move_menu.add_command(label="Top Right", command=lambda: self.move_to("top_right"))
        move_menu.add_command(label="Bottom Left", command=lambda: self.move_to("bottom_left"))
        move_menu.add_command(label="Bottom Right", command=lambda: self.move_to("bottom_right"))
        move_menu.add_command(label="Center", command=lambda: self.move_to("center"))
        self.more_menu.add_cascade(label="Move To", menu=move_menu)

        self.more_menu.add_separator()
        self.more_menu.add_command(label="Delete Note", accelerator="Alt+Del", command=self.delete_note)

        self.win.bind("<Control-s>", lambda _e: self.save_note())
        self.win.bind("<Control-S>", lambda _e: self.save_note())
        self.win.bind("<Control-p>", lambda _e: self.print_note())
        self.win.bind("<Control-P>", lambda _e: self.print_note())
        self.win.bind("<F2>", lambda _e: self._start_title_edit())
        self.win.bind("<Alt-n>", lambda _e: self.app.new_note(self.color))
        self.win.bind("<Alt-N>", lambda _e: self.app.new_note(self.color))
        self.win.bind("<Alt-t>", lambda _e: self._toggle_menu_var(self.always_on_top_var, self.toggle_always_on_top))
        self.win.bind("<Alt-T>", lambda _e: self._toggle_menu_var(self.always_on_top_var, self.toggle_always_on_top))
        self.win.bind("<Alt-l>", lambda _e: self._toggle_menu_var(self.locked_var, self.toggle_lock))
        self.win.bind("<Alt-L>", lambda _e: self._toggle_menu_var(self.locked_var, self.toggle_lock))
        self.win.bind("<Alt-m>", lambda _e: self.collapse())
        self.win.bind("<Alt-M>", lambda _e: self.collapse())

    def _toggle_menu_var(self, var: tk.BooleanVar, fn: callable) -> None:
        var.set(not bool(var.get()))
        fn()

    def _build_ui(self) -> None:
        self.container = tk.Frame(self.win, bg=self.color, bd=1, relief="solid")
        self.container.pack(fill="both", expand=True)

        self.header = tk.Frame(self.container, bg=self.color)
        self.header.pack(fill="x")

        self.title_var = tk.StringVar(value=self.title)
        self.title_label = tk.Label(self.header, textvariable=self.title_var, bg=self.color, fg="#111827")
        self.title_label.pack(side="left", padx=(10, 6), pady=6)

        self.close_btn = tk.Button(
            self.header,
            text="×",
            width=3,
            command=self.close,
            bd=0,
            relief="flat",
            bg=self.color,
            activebackground=self.color,
            highlightthickness=0,
        )
        self.close_btn.pack(side="right", padx=(4, 6), pady=4)

        self.more_btn = tk.Button(
            self.header,
            text="⋯",
            width=3,
            command=self.show_more_menu,
            bd=0,
            relief="flat",
            bg=self.color,
            activebackground=self.color,
            highlightthickness=0,
        )
        self.more_btn.pack(side="right", padx=2, pady=4)

        self.body = tk.Frame(self.container, bg=self.color)
        self.body.pack(fill="both", expand=True)

        sb = ttk.Scrollbar(self.body, orient="vertical")
        sb.pack(side="right", fill="y")

        self.text = tk.Text(self.body, wrap="word", bd=0, highlightthickness=0, undo=True)
        self.text.pack(side="left", fill="both", expand=True)
        self.text.configure(yscrollcommand=sb.set)
        sb.configure(command=self.text.yview)

        self.footer = tk.Frame(self.container, bg=self.color)
        self.footer.pack(fill="x")

        self.status_var = tk.StringVar(value="")
        self.status = tk.Label(self.footer, textvariable=self.status_var, bg=self.color, fg="#111827")
        self.status.pack(side="left", padx=10, pady=4)

        for w in (self.header, self.title_label):
            w.bind("<Button-1>", self._on_header_press)
            w.bind("<B1-Motion>", self.move_note)
            w.bind("<ButtonRelease-1>", self._on_header_release)
            w.bind("<Double-Button-1>", lambda _e: self.toggle_collapse())
        self.win.bind("<Button-3>", lambda _e: self.show_more_menu())
        self.text.bind("<<Modified>>", self._on_modified)

        self.win.bind("<Escape>", lambda _e: self.close())

        self.resize_grip = tk.Frame(self.container, bg=_hex_darken(self.color, 0.08), height=8, cursor="sb_v_double_arrow")
        self.resize_grip.pack(side="bottom", fill="x")
        self.resize_grip.bind("<Button-1>", self._on_resize_press)
        self.resize_grip.bind("<B1-Motion>", self._on_resize_drag)
        self._update_header_buttons()

    def show_more_menu(self) -> None:
        try:
            x = self.more_btn.winfo_rootx()
            y = self.more_btn.winfo_rooty() + self.more_btn.winfo_height()
        except tk.TclError:
            return
        try:
            self.more_menu.tk_popup(x, y)
        finally:
            try:
                self.more_menu.grab_release()
            except tk.TclError:
                pass

    def set_opacity(self, alpha: float) -> None:
        a = max(0.25, min(1.0, float(alpha)))
        self.opacity = a
        try:
            self.win.attributes("-alpha", a)
        except tk.TclError:
            pass
        self.app.request_session_autosave()

    def toggle_always_on_top(self) -> None:
        self.always_on_top = bool(self.always_on_top_var.get())
        try:
            self.win.attributes("-topmost", self.always_on_top)
        except tk.TclError:
            pass
        if self.always_on_top:
            try:
                self.win.lift()
            except tk.TclError:
                pass
        self.app.request_session_autosave()

    def toggle_starred(self) -> None:
        self.starred = bool(self.starred_var.get())
        self.set_title(self.title)
        self.app.request_session_autosave()

    def toggle_lock(self) -> None:
        self.locked = bool(self.locked_var.get())
        try:
            self.text.configure(state=("disabled" if self.locked else "normal"))
        except tk.TclError:
            pass
        self.app.request_session_autosave()

    def hide_note(self) -> None:
        self.hidden = True
        try:
            self.win.withdraw()
        except tk.TclError:
            pass

    def show_note(self) -> None:
        self.hidden = False
        try:
            self.win.deiconify()
        except tk.TclError:
            pass

    def hide_others(self) -> None:
        self.app.hide_all_except(self.id)

    def delete_note(self) -> None:
        if messagebox.askyesno("Delete Note", "Delete this note? This cannot be undone."):
            if self.file_path and Path(self.file_path).exists():
                try:
                    Path(self.file_path).unlink(missing_ok=True)
                except OSError:
                    pass
            self.close()

    def locate_in_explorer(self) -> None:
        target = self.file_path
        if target and Path(target).exists():
            try:
                subprocess.Popen(["explorer", "/select,", str(Path(target))])
            except OSError:
                pass
        else:
            try:
                os.startfile(str(self.app.notes_dir))
            except OSError:
                pass

    def share_note(self) -> None:
        try:
            self.win.clipboard_clear()
            self.win.clipboard_append(self.get_text())
            self.win.update_idletasks()
        except tk.TclError:
            pass
        self.app.show_toast("Copied note text")

    def print_note(self) -> None:
        p = self._ensure_export_path(suffix=".txt")
        if not p:
            return
        try:
            p.write_text(self.get_text(), encoding="utf-8")
        except OSError:
            messagebox.showerror("Print Failed", "Could not prepare print file.")
            return
        try:
            os.startfile(str(p), "print")
        except OSError:
            try:
                os.startfile(str(p))
            except OSError:
                pass

    def _ensure_export_path(self, suffix: str = ".txt") -> Path | None:
        try:
            self.app.notes_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        name = f"note-{self.id[:8]}{suffix}"
        return self.app.notes_dir / name

    def set_alarm(self) -> None:
        minutes = simpledialog.askinteger("Alarm", "Remind me in how many minutes?", minvalue=1, maxvalue=7 * 24 * 60)
        if not minutes:
            return

        def _fire() -> None:
            try:
                messagebox.showinfo("Alarm", f"{self.title}\n\n{self.get_text()[:2000]}")
            except tk.TclError:
                pass

        try:
            self.win.after(int(minutes * 60 * 1000), _fire)
        except tk.TclError:
            pass

    def move_to(self, where: str) -> None:
        parts = self._geometry_parts(self.win.geometry())
        if not parts:
            return
        w, h, _x, _y = parts
        try:
            sw = self.win.winfo_screenwidth()
            sh = self.win.winfo_screenheight()
        except tk.TclError:
            return
        pad = 16
        if where == "top_left":
            x, y = pad, pad
        elif where == "top_right":
            x, y = max(pad, sw - w - pad), pad
        elif where == "bottom_left":
            x, y = pad, max(pad, sh - h - pad)
        elif where == "bottom_right":
            x, y = max(pad, sw - w - pad), max(pad, sh - h - pad)
        else:
            x, y = max(pad, (sw - w) // 2), max(pad, (sh - h) // 2)
        try:
            self.win.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass
        self.app.request_session_autosave()

    def _set_size_preset(self, preset: str) -> None:
        geo = self.win.geometry()
        parts = self._geometry_parts(geo)
        if not parts:
            return
        _w, _h, x, y = parts
        if preset == "small":
            w, h = 240, 180
        elif preset == "large":
            w, h = 380, 320
        else:
            w, h = 280, 220
        try:
            self.win.geometry(f"{w}x{h}+{x}+{y}")
        except tk.TclError:
            pass
        self.app.request_session_autosave()

    def _on_header_press(self, event: tk.Event) -> None:
        self._dragged = False
        self.start_move(event)

    def _on_header_release(self, _event: tk.Event) -> None:
        return

    def _geometry_parts(self, geometry: str) -> tuple[int, int, int, int] | None:
        m = re.match(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$", geometry.strip())
        if not m:
            return None
        try:
            w = int(m.group(1))
            h = int(m.group(2))
            x = int(m.group(3))
            y = int(m.group(4))
        except ValueError:
            return None
        return w, h, x, y

    def collapse(self, initial: bool = False) -> None:
        if self.collapsed and not initial:
            return
        if not initial:
            try:
                self._expanded_geometry = self.win.geometry()
            except tk.TclError:
                self._expanded_geometry = None

        geo = self._expanded_geometry or self.win.geometry()
        parts = self._geometry_parts(geo)
        if parts:
            w, _h, x, y = parts
        else:
            try:
                self.win.update_idletasks()
                w = int(self.win.winfo_width())
                x = int(self.win.winfo_x())
                y = int(self.win.winfo_y())
            except tk.TclError:
                w, x, y = 280, 0, 40

        y = max(40, y)
        try:
            self.header.update_idletasks()
            ch = max(34, int(self.header.winfo_reqheight()) + 2)
        except tk.TclError:
            ch = 38

        try:
            self.win.minsize(self._normal_minsize[0], ch)
        except tk.TclError:
            pass

        try:
            self.title_label.pack_configure(pady=2)
            self.more_btn.pack_configure(pady=2)
            self.close_btn.pack_configure(pady=2)
        except tk.TclError:
            pass

        try:
            self.win.geometry(f"{w}x{ch}+{x}+{y}")
        except tk.TclError:
            pass

        try:
            self.body.pack_forget()
            self.footer.pack_forget()
            self.resize_grip.pack_forget()
        except tk.TclError:
            pass

        self.collapsed = True
        self.app.request_session_autosave()

    def expand(self) -> None:
        if not self.collapsed:
            return

        try:
            self.win.minsize(*self._normal_minsize)
        except tk.TclError:
            pass

        try:
            self.title_label.pack_configure(pady=6)
            self.more_btn.pack_configure(pady=4)
            self.close_btn.pack_configure(pady=4)
        except tk.TclError:
            pass

        try:
            self.body.pack(fill="both", expand=True)
            self.footer.pack(fill="x")
            self.resize_grip.pack(side="bottom", fill="x")
        except tk.TclError:
            pass

        if self._expanded_geometry:
            try:
                self.win.geometry(self._expanded_geometry)
            except tk.TclError:
                pass

        self.collapsed = False
        self.app.request_session_autosave()

    def toggle_collapse(self) -> None:
        if self.hidden:
            self.show_note()
        if self.collapsed:
            self.expand()
        else:
            self.collapse()

    def start_move(self, event: tk.Event) -> None:
        self._drag_origin = (event.x, event.y)

    def move_note(self, event: tk.Event) -> None:
        if not self._drag_origin:
            return
        ox, oy = self._drag_origin
        if event.x != ox or event.y != oy:
            self._dragged = True
        self.win.geometry(f"+{self.win.winfo_x() + (event.x - ox)}+{self.win.winfo_y() + (event.y - oy)}")
        self.app.request_session_autosave()

    def set_color(self, color: str) -> None:
        self.color = color
        self.win.configure(bg=color)
        self.text.configure(bg=color)
        try:
            self.container.configure(bg=color)
            self.header.configure(bg=color)
            self.body.configure(bg=color)
            self.footer.configure(bg=color)
            self.title_label.configure(bg=color)
            self.status.configure(bg=color)
            self.more_btn.configure(bg=color)
            self.close_btn.configure(bg=color)
            self.resize_grip.configure(bg=_hex_darken(color, 0.08))
        except tk.TclError:
            pass

        try:
            self.status.configure(background=color)
        except tk.TclError:
            pass

    def pick_color(self) -> None:
        popup = tk.Toplevel(self.win)
        popup.title("Palette")
        try:
            popup.transient(self.win)
        except tk.TclError:
            pass

        root = ttk.Frame(popup, padding=(12, 12))
        root.pack(fill="both", expand=True)

        colors = getattr(self.app, "colors", None)
        if not isinstance(colors, list) or not colors:
            colors = [("Classic", self.color)]

        cols = 4
        for i, (name, hex_color) in enumerate(colors):
            btn = tk.Button(
                root,
                text=name,
                bg=hex_color,
                fg="#111827",
                activebackground=hex_color,
                relief="flat",
                bd=0,
                command=lambda c=hex_color: self._select_palette_color(popup, c),
            )
            btn.grid(row=i // cols, column=i % cols, sticky="ew", padx=6, pady=6, ipadx=10, ipady=10)

        for c in range(cols):
            root.grid_columnconfigure(c, weight=1)

        actions = ttk.Frame(root)
        actions.grid(row=(len(colors) + cols - 1) // cols, column=0, columnspan=cols, sticky="ew", pady=(10, 0))
        actions.grid_columnconfigure(0, weight=1)
        ttk.Button(actions, text="Cancel", command=popup.destroy).grid(row=0, column=0, sticky="e")

        try:
            popup.grab_set()
        except tk.TclError:
            pass

        popup.update_idletasks()
        w = max(280, popup.winfo_reqwidth())
        h = max(220, popup.winfo_reqheight())
        self._center_popup(popup, width=w, height=h)
        popup.bind("<Escape>", lambda _e: popup.destroy())

    def _select_palette_color(self, popup: tk.Toplevel, color: str) -> None:
        self.set_color(color)
        self.app.request_session_autosave()
        try:
            popup.destroy()
        except tk.TclError:
            pass

    def _center_popup(self, popup: tk.Toplevel, width: int | None = None, height: int | None = None) -> None:
        popup.update_idletasks()
        try:
            w = int(width or popup.winfo_width())
            h = int(height or popup.winfo_height())
        except tk.TclError:
            return

        try:
            px = self.win.winfo_rootx()
            py = self.win.winfo_rooty()
            pw = self.win.winfo_width()
            ph = self.win.winfo_height()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
        except tk.TclError:
            try:
                sw = popup.winfo_screenwidth()
                sh = popup.winfo_screenheight()
            except tk.TclError:
                return
            x = (sw - w) // 2
            y = (sh - h) // 2

        popup.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")

    def set_title(self, title: str) -> None:
        t = (title or "Sticky Note").strip()
        self.title = t
        self.title_var.set(("★ " if self.starred else "") + t)

    def _start_title_edit(self, _event: tk.Event | None = None) -> None:
        if self._is_editing_title:
            return
        self._is_editing_title = True

        self._title_edit = ttk.Entry(self.header)
        try:
            self._title_edit.insert(0, self.title)
        except tk.TclError:
            pass

        try:
            self.title_label.pack_forget()
        except tk.TclError:
            pass

        self._title_edit.pack(side="left", fill="x", expand=True, padx=(10, 6), pady=6)
        try:
            self._title_edit.focus_set()
            self._title_edit.selection_range(0, "end")
        except tk.TclError:
            pass

        self._title_edit.bind("<Return>", lambda _e: self._finish_title_edit())
        self._title_edit.bind("<Escape>", lambda _e: self._cancel_title_edit())
        self._title_edit.bind("<FocusOut>", lambda _e: self._finish_title_edit())

    def _finish_title_edit(self) -> None:
        if not self._is_editing_title:
            return
        new_title = self.title
        try:
            new_title = self._title_edit.get().strip()
        except tk.TclError:
            new_title = self.title

        try:
            self._title_edit.destroy()
        except tk.TclError:
            pass

        self.title_label.pack(side="left", padx=(10, 6), pady=6)
        self._is_editing_title = False
        self.set_title(new_title)
        self.app.request_session_autosave()

    def _cancel_title_edit(self) -> None:
        if not self._is_editing_title:
            return
        try:
            self._title_edit.destroy()
        except tk.TclError:
            pass
        self.title_label.pack(side="left", padx=(10, 6), pady=6)
        self._is_editing_title = False

    def set_text(self, text: str) -> None:
        try:
            self.text.configure(state="normal")
        except tk.TclError:
            pass
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        try:
            self.text.edit_modified(False)
        except tk.TclError:
            pass
        if self.locked:
            try:
                self.text.configure(state="disabled")
            except tk.TclError:
                pass

    def _on_modified(self, _event: tk.Event) -> None:
        try:
            self.text.edit_modified(False)
        except tk.TclError:
            return
        self.app.request_session_autosave()
        self._schedule_note_autosave()

    def _schedule_note_autosave(self) -> None:
        if not self.file_path:
            return
        if self._pending_note_save_after_id:
            try:
                self.win.after_cancel(self._pending_note_save_after_id)
            except tk.TclError:
                pass
        self._pending_note_save_after_id = self.win.after(800, self.save_note)

    def get_text(self) -> str:
        return self.text.get("1.0", "end-1c")

    def duplicate(self) -> None:
        state = self.to_dict()
        state["id"] = str(uuid.uuid4())
        state["file_path"] = None
        state["geometry"] = None
        state["collapsed"] = False
        self.app.new_note(state=state)

    def clear(self) -> None:
        self.set_text("")
        self.status_var.set("Cleared")
        self.app.show_toast("Note cleared")
        self.app.request_session_autosave()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "color": self.color,
            "text": self.get_text(),
            "geometry": self._expanded_geometry or self.win.geometry(),
            "file_path": self.file_path,
            "collapsed": self.collapsed,
            "opacity": self.opacity,
            "locked": self.locked,
            "always_on_top": self.always_on_top,
            "starred": self.starred,
        }

    @staticmethod
    def load_note_file(path: str) -> dict:
        p = Path(path)
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Invalid note file")
        data["file_path"] = str(p)
        return data

    def load_note(self) -> None:
        selected = filedialog.askopenfilename(
            title="Load Note",
            initialdir=str(self.app.notes_dir),
            filetypes=[("Sticky Note", "*.snote.json"), ("JSON", "*.json"), ("All Files", "*.*")],
        )
        if not selected:
            return
        try:
            state = StickyNote.load_note_file(selected)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            messagebox.showerror("Load Failed", f"Could not load note:\n{e}")
            return

        self.file_path = state.get("file_path")
        if state.get("geometry"):
            self._expanded_geometry = state.get("geometry")
        self.set_title(state.get("title", self.title))
        self.set_color(state.get("color", self.color))
        self.set_text(state.get("text", ""))
        self.starred_var.set(bool(state.get("starred", False)))
        self.toggle_starred()
        self.always_on_top_var.set(bool(state.get("always_on_top", self.always_on_top)))
        self.locked_var.set(bool(state.get("locked", self.locked)))
        self.toggle_always_on_top()
        self.toggle_lock()

        try:
            self.opacity_var.set(int(round(float(state.get("opacity", self.opacity)) * 100)))
        except (TypeError, ValueError):
            pass
        self.set_opacity(float(state.get("opacity", self.opacity)))

        if bool(state.get("collapsed", False)):
            self.collapse()
        else:
            self.expand()

        self.status_var.set(f"Loaded {time.strftime('%H:%M:%S')}")
        self.app.request_session_autosave()

    def save_note(self) -> None:
        if not self.file_path:
            self.save_note_as()
            return
        p = Path(self.file_path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            messagebox.showerror("Save Failed", f"Could not save note:\n{e}")
            return
        self.status_var.set(f"Saved {time.strftime('%H:%M:%S')}")

    def save_note_as(self) -> None:
        initial_dir = str(self.app.notes_dir)
        initial_file = f"note-{self.id[:8]}.snote.json"
        selected = filedialog.asksaveasfilename(
            title="Save Note As",
            initialdir=initial_dir,
            initialfile=initial_file,
            defaultextension=".json",
            filetypes=[("Sticky Note", "*.snote.json"), ("JSON", "*.json"), ("All Files", "*.*")],
        )
        if not selected:
            return
        self.file_path = selected
        self.save_note()
        self.app.request_session_autosave()

    def close(self) -> None:
        self.app.unregister(self.id)
        _fade_out_destroy(self.win)


class StickyNoteApp:
    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        self.notes: dict[str, StickyNote] = {}
        self.app_dir = _app_data_dir()
        self.notes_dir = self.app_dir / "notes"
        self.session_path = self.app_dir / "session.json"
        self._pending_session_save_after_id: str | None = None

        try:
            self.app_dir.mkdir(parents=True, exist_ok=True)
            self.notes_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

        self._configure_style()
        self._build_ui()
        self._build_menu()
        self._bind_shortcuts()

        self.load_session(silent=True)
        _fade_in(self.master)

    def _configure_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Drawer.TFrame", background="#1F2937")
        style.configure("Header.TFrame", background="#111827")
        style.configure("Title.TLabel", background="#111827", foreground="#F9FAFB", font=("Segoe UI", 14, "bold"))
        style.configure("Sub.TLabel", background="#111827", foreground="#9CA3AF", font=("Segoe UI", 9))
        style.configure("Status.TLabel", background="#1F2937", foreground="#D1D5DB")
        style.configure("Primary.TButton", padding=(10, 8))

    def _build_ui(self) -> None:
        self.master.title("Sticky Note Drawer")
        self.master.geometry("320x650")
        self.master.minsize(320, 420)

        root = ttk.Frame(self.master, style="Drawer.TFrame")
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root, style="Header.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="Sticky Note Drawer", style="Title.TLabel", padding=(14, 14, 14, 4)).pack(anchor="w")
        ttk.Label(
            header,
            text="Ctrl+N New | Ctrl+S Save session | Ctrl+O Load session",
            style="Sub.TLabel",
            padding=(14, 0, 14, 12),
        ).pack(anchor="w")

        content = ttk.Frame(root, style="Drawer.TFrame", padding=(14, 14))
        content.pack(fill="both", expand=True)

        ttk.Button(content, text="New Note", style="Primary.TButton", command=self.new_note).pack(fill="x")

        ttk.Label(content, text="Palette", style="Status.TLabel", padding=(0, 12, 0, 6)).pack(anchor="w")
        palette = ttk.Frame(content, style="Drawer.TFrame")
        palette.pack(fill="x")

        self.colors: list[tuple[str, str]] = [
            ("Classic", "#FFF59D"),
            ("Sky", "#BAE6FD"),
            ("Mint", "#BBF7D0"),
            ("Rose", "#FBCFE8"),
            ("Slate", "#E5E7EB"),
            ("Lavender", "#DDD6FE"),
            ("Peach", "#FED7AA"),
            ("Lemon", "#FEF08A"),
            ("Aqua", "#99F6E4"),
            ("Teal", "#5EEAD4"),
            ("Periwinkle", "#C7D2FE"),
            ("Lilac", "#E9D5FF"),
            ("Coral", "#FCA5A5"),
            ("Sand", "#F5E6CA"),
            ("Sage", "#D9F99D"),
            ("Charcoal", "#CBD5E1"),
        ]

        for i, (name, color) in enumerate(self.colors):
            btn = tk.Button(
                palette,
                text=name,
                bg=color,
                fg="#111827",
                activebackground=color,
                relief="flat",
                bd=0,
            )
            btn.configure(command=lambda c=color, b=btn: self._palette_press(b, c))
            btn.grid(row=i // 2, column=i % 2, sticky="ew", padx=6, pady=6, ipadx=6, ipady=10)

        palette.grid_columnconfigure(0, weight=1)
        palette.grid_columnconfigure(1, weight=1)

        status = ttk.Frame(root, style="Drawer.TFrame")
        status.pack(fill="x")
        self.stats_var = tk.StringVar(value="0 notes")
        self.autosave_var = tk.StringVar(value="")
        ttk.Label(status, textvariable=self.stats_var, style="Status.TLabel", padding=(14, 8)).pack(side="left")
        ttk.Label(status, textvariable=self.autosave_var, style="Status.TLabel", padding=(14, 8)).pack(side="right")

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.master)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Note", command=self.new_note)
        file_menu.add_separator()
        file_menu.add_command(label="Save Session", command=self.save_session)
        file_menu.add_command(label="Load Session...", command=self.load_session_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Import Note...", command=self.import_note)
        file_menu.add_command(label="Show All Notes", command=self.show_all_notes)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.master.config(menu=menubar)

    def _bind_shortcuts(self) -> None:
        self.master.bind("<Control-n>", lambda _e: self.new_note())
        self.master.bind("<Control-N>", lambda _e: self.new_note())
        self.master.bind("<Control-s>", lambda _e: self.save_session())
        self.master.bind("<Control-S>", lambda _e: self.save_session())
        self.master.bind("<Control-o>", lambda _e: self.load_session_dialog())
        self.master.bind("<Control-O>", lambda _e: self.load_session_dialog())
        self.master.protocol("WM_DELETE_WINDOW", self.quit)

    def show_toast(self, message: str, duration_ms: int = 1400) -> None:
        toast = tk.Toplevel(self.master)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        frame = ttk.Frame(toast, padding=(12, 10))
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=message).pack()
        toast.update_idletasks()
        x = self.master.winfo_x() + self.master.winfo_width() - toast.winfo_width() - 20
        y = self.master.winfo_y() + self.master.winfo_height() - toast.winfo_height() - 20
        toast.geometry(f"+{max(0, x)}+{max(0, y)}")
        _fade_in(toast, ms=120)
        toast.after(duration_ms, lambda: _fade_out_destroy(toast, ms=140))

    def about(self) -> None:
        messagebox.showinfo(
            "About",
            "Sticky Note Drawer\n\n"
            "Session autosaves automatically.\n\n"
            "Shortcuts:\n"
            "  Ctrl+N New note\n"
            "  Ctrl+S Save session\n"
            "  Ctrl+O Load session\n\n"
            "Tip: Right-click a note to recolor it.",
        )

    def _palette_press(self, btn: tk.Button, color: str) -> None:
        try:
            orig_bg = btn.cget("bg")
            orig_relief = btn.cget("relief")
        except tk.TclError:
            self.new_note(color)
            return

        try:
            btn.configure(bg=_hex_darken(orig_bg, 0.14), relief="sunken")
        except tk.TclError:
            pass

        def _finish() -> None:
            try:
                btn.configure(bg=orig_bg, relief=orig_relief)
            except tk.TclError:
                pass
            self.new_note(color)

        self.master.after(90, _finish)

    def new_note(self, color: str = "#FFF59D", state: dict | None = None) -> StickyNote:
        if state:
            note = StickyNote(
                app=self,
                master=self.master,
                note_id=state.get("id"),
                color=state.get("color", color),
                title=state.get("title", "Sticky Note"),
                text=state.get("text", ""),
                geometry=state.get("geometry"),
                file_path=state.get("file_path"),
                collapsed=bool(state.get("collapsed", False)),
                opacity=float(state.get("opacity", 1.0) or 1.0),
                locked=bool(state.get("locked", False)),
                always_on_top=bool(state.get("always_on_top", False)),
                starred=bool(state.get("starred", False)),
            )
        else:
            note = StickyNote(app=self, master=self.master, color=color)

        self.notes[note.id] = note
        self._update_stats()
        self.request_session_autosave()
        return note

    def unregister(self, note_id: str) -> None:
        self.notes.pop(note_id, None)
        self._update_stats()
        self.request_session_autosave()

    def hide_all_except(self, keep_note_id: str) -> None:
        for nid, note in self.notes.items():
            if nid == keep_note_id:
                note.show_note()
                try:
                    note.win.lift()
                except tk.TclError:
                    pass
            else:
                note.hide_note()

    def show_all_notes(self) -> None:
        for note in self.notes.values():
            note.show_note()
        try:
            self.master.lift()
        except tk.TclError:
            pass

    def _update_stats(self) -> None:
        n = len(self.notes)
        self.stats_var.set(f"{n} note" + ("" if n == 1 else "s"))

    def request_session_autosave(self) -> None:
        if self._pending_session_save_after_id:
            try:
                self.master.after_cancel(self._pending_session_save_after_id)
            except tk.TclError:
                pass
        self.autosave_var.set("Autosaving...")

        def _do_autosave() -> None:
            self._pending_session_save_after_id = None
            self.save_session(silent=True)

        self._pending_session_save_after_id = self.master.after(900, _do_autosave)

    def session_dict(self) -> dict:
        return {"version": 1, "notes": [n.to_dict() for n in self.notes.values()]}

    def save_session(self, silent: bool = False) -> None:
        data = self.session_dict()
        try:
            self.app_dir.mkdir(parents=True, exist_ok=True)
            self.session_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            if not silent:
                messagebox.showerror("Save Failed", f"Could not save session:\n{e}")
            self.autosave_var.set("")
            return
        self.autosave_var.set(f"Saved {time.strftime('%H:%M:%S')}")
        if not silent:
            self.show_toast("Session saved")

    def _load_session_from_path(self, path: Path, silent: bool = False) -> None:
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            notes = data.get("notes", []) if isinstance(data, dict) else []
        except (OSError, json.JSONDecodeError) as e:
            if not silent:
                messagebox.showerror("Load Failed", f"Could not load session:\n{e}")
            return

        for note in list(self.notes.values()):
            try:
                note.win.destroy()
            except tk.TclError:
                pass
        self.notes.clear()

        if isinstance(notes, list):
            for st in notes:
                if isinstance(st, dict):
                    self.new_note(state=st)
        self._update_stats()
        self.autosave_var.set(f"Loaded {time.strftime('%H:%M:%S')}")

    def load_session(self, silent: bool = False) -> None:
        if self.session_path.exists():
            self._load_session_from_path(self.session_path, silent=silent)

    def load_session_dialog(self) -> None:
        selected = filedialog.askopenfilename(
            title="Load Session",
            initialdir=str(self.app_dir),
            filetypes=[("Session", "*.json"), ("All Files", "*.*")],
        )
        if not selected:
            return
        self._load_session_from_path(Path(selected), silent=False)
        self.show_toast("Session loaded")

    def import_note(self) -> None:
        selected = filedialog.askopenfilename(
            title="Import Note",
            initialdir=str(self.notes_dir),
            filetypes=[("Sticky Note", "*.snote.json"), ("JSON", "*.json"), ("All Files", "*.*")],
        )
        if not selected:
            return
        try:
            state = StickyNote.load_note_file(selected)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            messagebox.showerror("Import Failed", f"Could not import note:\n{e}")
            return
        self.new_note(state=state)
        self.show_toast("Note imported")

    def quit(self) -> None:
        self.save_session(silent=True)
        _fade_out_destroy(self.master)


def _self_test() -> int:
    root = tk.Tk()
    root.withdraw()
    app = StickyNoteApp(root)
    app.master.update_idletasks()
    note = app.new_note()
    note.set_text("test")
    app.save_session(silent=True)
    app.load_session(silent=True)
    try:
        root.destroy()
    except tk.TclError:
        pass
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        raise SystemExit(_self_test())

    root = tk.Tk()
    StickyNoteApp(root)
    root.mainloop()