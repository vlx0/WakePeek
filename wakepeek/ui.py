"""Окно WakePeek."""

from __future__ import annotations

import ctypes
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from . import __version__
from .instance import WINDOW_TITLE
from .log import LogError, fetch_events
from .sessions import (
    Event,
    Session,
    build_sessions,
    clip_sessions,
    format_span,
    format_when,
    row_kind,
)
from .settings import CHOICES, load_days, save_days

BG = "#111111"
FG = "#ffffff"
MUTED = "#999999"
CARD = "#1c1c1c"
CARD_ON = "#243044"
BTN = "#2a2a2a"
ACCENT = "#93c5fd"
OK = "#86efac"
BAD = "#fca5a5"

_KIND_COLOR = {
    "кнопка питания": ACCENT,
    "кнопка сна": ACCENT,
    "крышка": ACCENT,
    "таймер": OK,
    "устройство": OK,
    "журнал не записал": BAD,
}


def _count_word(count: int) -> str:
    tail = abs(count) % 100
    if 11 <= tail <= 14:
        return "записей"
    last = tail % 10
    if last == 1:
        return "запись"
    if 2 <= last <= 4:
        return "записи"
    return "записей"


def _event(row: dict) -> Event | None:
    try:
        when = datetime.fromisoformat(str(row["t"]).strip())
        number = int(row["id"])
    except (KeyError, TypeError, ValueError):
        return None
    src = str(row.get("src") or "")
    if src not in {"pt", "kp"}:
        src = "pt" if number == 1 else "kp"
    props = row.get("p") or []
    if not isinstance(props, list):
        props = []
    return Event(when, number, src, tuple(str(item) for item in props))


def _same_day(start: datetime, end: datetime) -> bool:
    a = start.astimezone() if start.tzinfo else start
    b = end.astimezone() if end.tzinfo else end
    return (a.year, a.month, a.day) == (b.year, b.month, b.day)


def _span_line(session: Session) -> str:
    if session.wake is None:
        return format_when(session.sleep)
    if _same_day(session.sleep, session.wake):
        end = session.wake.astimezone() if session.wake.tzinfo else session.wake
        return f"{format_when(session.sleep)}   →   {end:%H:%M}"
    return f"{format_when(session.sleep)}   →   {format_when(session.wake)}"


def _duration(session: Session) -> str:
    if session.wake is None:
        return "—"
    return format_span(session.sleep, session.wake)


class _Card:
    def __init__(self, parent: tk.Frame, session: Session, index: int, on_pick) -> None:
        self.session = session
        self._parts: list[tk.Widget] = []
        kind = row_kind(session)
        self._stripe_color = _KIND_COLOR.get(kind, FG)
        self.box = tk.Frame(parent, bg=CARD, cursor="hand2", highlightthickness=0)
        self.box.pack(fill="x", pady=(0, 8))
        stripe = tk.Frame(self.box, bg=self._stripe_color, width=6)
        stripe.pack(side="left", fill="y")
        stripe.pack_propagate(False)
        self._parts.append(stripe)
        self.inner = tk.Frame(self.box, bg=CARD)
        self.inner.pack(side="left", fill="both", expand=True, padx=12, pady=10)
        self._parts.append(self.inner)

        top = tk.Frame(self.inner, bg=CARD)
        top.pack(fill="x")
        self._parts.append(top)
        when = tk.Label(
            top, text=_span_line(session), bg=CARD, fg=FG,
            font=("Segoe UI Semibold", 12),
        )
        when.pack(side="left")
        self._parts.append(when)
        dur = tk.Label(
            top, text=_duration(session), bg=CARD, fg=FG,
            font=("Segoe UI Semibold", 14),
        )
        dur.pack(side="right")
        self._parts.append(dur)

        kind_label = tk.Label(
            self.inner, text=kind, bg=CARD, fg=self._stripe_color,
            font=("Segoe UI Semibold", 12),
        )
        kind_label.pack(anchor="w", pady=(4, 0))
        self._parts.append(kind_label)

        extra = "  ·  ".join(part for part in (session.mode, session.why) if part)
        if extra:
            sub = tk.Label(self.inner, text=extra, bg=CARD, fg=MUTED, font=("Segoe UI", 12))
            sub.pack(anchor="w", pady=(3, 0))
            self._parts.append(sub)

        def pick(_event=None, i=index) -> None:
            on_pick(i)

        for widget in self._parts:
            widget.bind("<Button-1>", pick)
        self.box.bind("<Button-1>", pick)
        self.set_selected(False)

    def set_selected(self, on: bool) -> None:
        bg = CARD_ON if on else CARD
        self.box.configure(bg=bg)
        for widget in self._parts:
            if widget is self._parts[0]:
                continue
            try:
                widget.configure(bg=bg)
            except tk.TclError:
                pass

    def bind_wheel(self, handler) -> None:
        self.box.bind("<MouseWheel>", handler)
        for widget in self._parts:
            widget.bind("<MouseWheel>", handler)


class WakePeekApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("645x675")
        self.minsize(540, 570)
        self.configure(bg=BG)
        self._q: queue.Queue = queue.Queue()
        self._gen = 0
        self._sessions: list[Session] = []
        self._cards: list[_Card] = []
        self._selected = 0
        self._days = load_days()
        self._day_btns: dict[int, tk.Button] = {}

        pad = tk.Frame(self, bg=BG)
        pad.pack(fill="both", expand=True, padx=16, pady=14)

        foot = tk.Frame(pad, bg=BG)
        foot.pack(fill="x", side="bottom", pady=(8, 0))
        tk.Label(foot, text="неделя 10 · день 65", bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
        tk.Label(foot, text=f"v{__version__} · darkshade", bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="right")

        self._facts = tk.Frame(pad, bg=BG)
        self._facts.pack(fill="x", side="bottom", pady=(10, 0))

        head = tk.Frame(pad, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="WakePeek", bg=BG, fg=FG, font=("Segoe UI Semibold", 20)).pack(side="left")
        self._reload = tk.Button(
            head,
            text="Обновить",
            command=self._load,
            bg=ACCENT,
            fg=BG,
            relief="flat",
            bd=0,
            cursor="hand2",
            font=("Segoe UI Semibold", 9),
            activebackground=ACCENT,
            activeforeground=BG,
            padx=6,
            pady=1,
        )
        self._reload.pack(side="right", pady=6)
        self._note = tk.Label(
            pad, text="Сон и пробуждение",
            bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w",
        )
        self._note.pack(fill="x", pady=(3, 12))

        periods = tk.Frame(pad, bg=BG)
        periods.pack(fill="x", pady=(0, 12))
        for days in CHOICES:
            btn = tk.Button(
                periods,
                text=f"{days} дней",
                command=lambda d=days: self._pick_days(d),
                relief="flat",
                bd=0,
                cursor="hand2",
                font=("Segoe UI", 9),
                padx=6,
                pady=1,
            )
            btn.pack(side="left", padx=(0, 6))
            self._day_btns[days] = btn
        self._paint_days()

        body = tk.Frame(pad, bg=BG)
        body.pack(fill="both", expand=True)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Wake.Vertical.TScrollbar",
            gripcount=0,
            background="#3a3a3a",
            darkcolor="#3a3a3a",
            lightcolor="#3a3a3a",
            troughcolor=BG,
            bordercolor=BG,
            arrowcolor=MUTED,
            relief="flat",
            width=12,
        )
        style.map("Wake.Vertical.TScrollbar", background=[("active", "#555555")])
        self._scroll = ttk.Scrollbar(body, orient="vertical", style="Wake.Vertical.TScrollbar")
        self._scroll.pack(side="right", fill="y")
        self._canvas = tk.Canvas(body, bg=BG, highlightthickness=0, bd=0, yscrollcommand=self._scroll.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        self._scroll.configure(command=self._canvas.yview)
        self._list = tk.Frame(self._canvas, bg=BG)
        self._window = self._canvas.create_window((0, 0), window=self._list, anchor="nw")
        self._list.bind("<Configure>", self._fit_scroll)
        self._list.bind("<MouseWheel>", self._wheel)
        self._canvas.bind("<Configure>", self._fit_width)
        self._canvas.bind("<MouseWheel>", self._wheel)

        self.bind("<Up>", lambda _e: self._move(-1))
        self.bind("<Down>", lambda _e: self._move(1))
        self.bind("<MouseWheel>", self._wheel)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(20, self._place)
        self.after(80, self._poll)
        self.after(60, self._load)

    def _paint_days(self) -> None:
        for days, btn in self._day_btns.items():
            on = days == self._days
            btn.configure(
                bg=ACCENT if on else CARD,
                fg=BG if on else FG,
                activebackground=ACCENT if on else BTN,
                activeforeground=BG if on else FG,
            )

    def _fit_scroll(self, _event=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _fit_width(self, event) -> None:
        self._canvas.itemconfig(self._window, width=event.width)

    def _wheel(self, event) -> str:
        self._canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _place(self) -> None:
        width, height = 645, 675
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        x = max(0, (sw - width) // 2)
        y = max(0, (sh - height) // 8)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _close(self) -> None:
        self.destroy()

    def _pick_days(self, days: int) -> None:
        if days == self._days:
            return
        self._days = days
        self._paint_days()
        save_days(days)
        self._load()

    def _load(self) -> None:
        self._gen += 1
        gen = self._gen
        self._reload.configure(text="Читаю…", state="disabled")
        self._note.configure(text="читаю журнал…", fg=MUTED)
        threading.Thread(target=self._work, args=(gen,), daemon=True).start()

    def _work(self, gen: int) -> None:
        try:
            rows = fetch_events()
            events = [item for item in (_event(row) for row in rows) if item is not None]
            now = datetime.now().astimezone()
            sessions = clip_sessions(build_sessions(events), self._days, now)
            self._q.put(("ok", gen, sessions, now))
        except LogError as exc:
            self._q.put(("err", gen, str(exc)))
        except Exception as exc:
            self._q.put(("err", gen, str(exc)))

    def _clear_cards(self) -> None:
        for child in self._list.winfo_children():
            child.destroy()
        self._cards.clear()

    def _apply(self, sessions: list[Session], _now: datetime) -> None:
        self._sessions = sessions
        self._selected = 0
        self._clear_cards()
        self._reload.configure(text="Обновить", state="normal")
        if not sessions:
            tk.Label(
                self._list,
                text="За эти дни сна в журнале нет.",
                bg=BG, fg=MUTED, font=("Segoe UI", 9),
            ).pack(anchor="w", pady=9)
            self._note.configure(text="За эти дни сна в журнале нет.", fg=MUTED)
            self._show()
            self._fit_scroll()
            return
        for index, session in enumerate(sessions):
            card = _Card(self._list, session, index, self._pick)
            card.bind_wheel(self._wheel)
            self._cards.append(card)
        self._cards[0].set_selected(True)
        self._canvas.yview_moveto(0)
        self._note.configure(text=f"{len(sessions)} {_count_word(len(sessions))} за {self._days} дн.", fg=MUTED)
        self._show()
        self._fit_scroll()

    def _pick(self, index: int) -> None:
        if index < 0 or index >= len(self._cards):
            return
        self._selected = index
        for i, card in enumerate(self._cards):
            card.set_selected(i == index)
        self._show()
        self._reveal(index)

    def _move(self, step: int) -> None:
        if not self._sessions:
            return
        self._pick(max(0, min(len(self._sessions) - 1, self._selected + step)))

    def _reveal(self, index: int) -> None:
        if index < 0 or index >= len(self._cards):
            return
        self.update_idletasks()
        box = self._cards[index].box
        y = box.winfo_y()
        height = box.winfo_height()
        total = max(1, self._list.winfo_height())
        view = self._canvas.winfo_height()
        top = self._canvas.canvasy(0)
        if y < top:
            self._canvas.yview_moveto(max(0, y / total))
        elif y + height > top + view:
            self._canvas.yview_moveto(max(0, (y + height - view) / total))

    def _fact_rows(self, session: Session) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        rows.append(("Источник", session.source or "журнал не записал"))
        if session.device:
            rows.append(("Устройство", session.device))
        if session.timer:
            rows.append(("Таймер", session.timer))
        if session.mode:
            rows.append(("Как уснул", session.mode))
        if session.why:
            rows.append(("Почему уснул", session.why))
        return rows

    def _show(self) -> None:
        for child in self._facts.winfo_children():
            child.destroy()
        if not self._sessions:
            return
        rows = self._fact_rows(self._sessions[self._selected])
        if not rows:
            return
        width = max(240, self.winfo_width() - 68)
        columns = 1 if len(rows) == 1 else 2
        col_w = width if columns == 1 else max(180, width // 2 - 12)
        for index, (caption, value) in enumerate(rows):
            cell = tk.Frame(self._facts, bg=CARD)
            cell.grid(
                row=index // columns,
                column=index % columns,
                columnspan=columns if len(rows) == 1 else 1,
                sticky="nsew",
                padx=(0, 8),
                pady=(0, 8),
            )
            tk.Label(cell, text=caption, bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack(
                anchor="w", padx=12, pady=(9, 0)
            )
            tk.Label(
                cell, text=value, bg=CARD, fg=FG,
                font=("Segoe UI Semibold", 12), wraplength=col_w, justify="left",
            ).pack(anchor="w", padx=12, pady=(2, 10))
        for column in range(columns):
            self._facts.grid_columnconfigure(column, weight=1)

    def _on_msg(self, msg) -> None:
        if msg[1] != self._gen:
            return
        if msg[0] == "ok":
            self._apply(msg[2], msg[3])
        else:
            self._reload.configure(text="Обновить", state="normal")
            self._note.configure(text=msg[2], fg=BAD)

    def _poll(self) -> None:
        if not self._alive():
            return
        try:
            while True:
                self._on_msg(self._q.get_nowait())
        except queue.Empty:
            pass
        except tk.TclError:
            return
        if self._alive():
            self.after(80, self._poll)


def run() -> None:
    WakePeekApp().mainloop()
