#!/usr/bin/env python3
"""Read-only Everhour status widget. Click anywhere → opens Everhour.

SG branding: black background, Poppins, #00C853 accent.
"""

import json
import random
import subprocess
import threading
import tkinter as tk
from tkinter import font as tkfont
from pathlib import Path

TOKEN_FILE = Path.home() / ".everhour-token"
POS_FILE = Path.home() / ".everhour-widget-pos"
LOG_FILE = Path.home() / "Library/Logs/everhour-widget.log"
SNOOZE_FILE = Path.home() / ".everhour-nag-snooze"
API_URL = "https://api.everhour.com/timers/current"
EVERHOUR_URL = "https://app.everhour.com/#/time"
NAG_SCRIPT = Path.home() / "bin" / "everhour_nag.py"
NAG_LABEL = "com.wojtek.everhour-nag"
NAG_PLIST = Path.home() / "Library/LaunchAgents" / f"{NAG_LABEL}.plist"

TICK_MS = 1000      # local clock + event-loop pump
SYNC_MS = 5000      # network sync

BLACK = "#0F0F10"   # active-state background
WHITE = "#FFFFFF"
GREEN = "#00C853"
MUTED = "#9CA3AF"
RED = "#EF4444"
IDLE_BG = "#7F1D1D"        # red-900 — alarm-status background, not loud
IDLE_MUTED = "#FCA5A5"     # red-300 — muted text on the dark red bg
ACCENT_H = 4        # height of the top accent stripe (under title bar)

IDLE_QUIPS = [
    "Czas to pieniądz. A ty go nie trackujesz.",
    "Zegar tyka, faktura nie.",
    "Past you traci kasę. Present you — stop it.",
    "Klient zapyta „co robiłeś dzisiaj?”…",
    "Nieotrackowane godziny trafiają do otchłani.",
    "Twoje przyszłe ja patrzy z dezaprobatą.",
    "PMO wie. PMO zawsze wie.",
    "Stawka godzinowa: 0 zł/h. Brawo.",
    "Co się nie zmierzy — tego nie ma.",
    "Roboty AI się rozliczają. Ty też możesz.",
    "TimingApp mruga ostrzegawczo.",
    "Nawet ChatGPT taryfikuje per token.",
    "Każda nieotrackowana godzina to jedno espresso mniej.",
    "Niech twój dzień ma narratora.",
    "Skalski by nie tolerował.",
    "Robisz coś? Udowodnij to slotem.",
    "Excel kolumna H cicho płacze.",
    "Bez timera jesteś niewidzialny.",
    "Tak, to passive-aggressive. I co?",
    "Trackuj, albo żyj w grzechu.",
    "Brak timera = wolny strzelec bez fakturki.",
    "Twój hourly rate właśnie spada do zera.",
    "Ten widget też się nie zrobił sam.",
]
QUIP_ROTATE_MS = 25000   # nowy żart co ~25s w stanie idle


def log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    with LOG_FILE.open("a") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")


def read_token() -> str | None:
    return TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else None


def fetch_timer(token: str) -> dict | None:
    try:
        r = subprocess.run(
            ["curl", "-fsS", "--max-time", "10",
             "-H", f"X-Api-Key: {token}", API_URL],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return None
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except Exception:
        return None


def fmt_duration(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:01d}:{m:02d}:{s:02d}"


def nag_status() -> tuple[str, str]:
    """Return (state, label). state ∈ {'active','snoozed','stopped'}."""
    import os
    uid = os.getuid()
    r = subprocess.run(
        ["launchctl", "print", f"gui/{uid}/{NAG_LABEL}"],
        capture_output=True, text=True,
    )
    loaded = r.returncode == 0
    if not loaded:
        return "stopped", "🔕  NAG: STOPPED"
    # loaded — check snooze
    if SNOOZE_FILE.exists():
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            until = datetime.fromisoformat(SNOOZE_FILE.read_text().strip())
            now = datetime.now(ZoneInfo("Europe/Warsaw"))
            if now < until:
                return "snoozed", f"💤  NAG: SNOOZED until {until.strftime('%H:%M')}"
        except Exception:
            pass
    return "active", "🔔  NAG: ACTIVE (every 10 min)"


def pick_font(preferred: str, fallback: str) -> str:
    return preferred if preferred in set(tkfont.families()) else fallback


class Widget:
    DRAG_THRESHOLD = 4  # px before a click becomes a drag

    def __init__(self) -> None:
        self.token = read_token()
        self.root = tk.Tk()
        self.root.title("Everhour")
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BLACK)
        # Dark title bar (macOS native dark appearance for this window).
        try:
            self.root.tk.call(
                "::tk::unsupported::MacWindowStyle",
                "appearance", self.root._w, "dark",
            )
        except tk.TclError:
            pass

        fam = pick_font("Poppins", "Helvetica Neue")
        F_BIG = (fam, 44, "bold")
        F_IDLE = (fam, 32, "bold")
        F_TASK = (fam, 13)
        F_STATUS = (fam, 10, "bold")
        F_HINT = (fam, 11)
        F_DOT = (fam, 14)
        self._F_BIG = F_BIG
        self._F_IDLE = F_IDLE

        x, y = self._load_pos()
        self.root.geometry(f"460x230+{x}+{y}")

        # Top accent stripe (single SG-green line under the title bar).
        tk.Frame(self.root, bg=GREEN, height=ACCENT_H).pack(fill="x")

        # Footer (nag controls) — packed FIRST at bottom so main fills remaining.
        # Green divider mirrors the top accent stripe → frames the main area.
        sep = tk.Frame(self.root, bg=GREEN, height=2)
        sep.pack(fill="x", side="bottom")
        footer = tk.Frame(self.root, bg=BLACK, padx=20, pady=10)
        footer.pack(fill="x", side="bottom")

        self.nag_lbl = tk.Label(footer, text="NAG: …",
                                fg=MUTED, bg=BLACK, font=(fam, 10, "bold"))
        self.nag_lbl.pack(side="left")

        actions = tk.Frame(footer, bg=BLACK)
        actions.pack(side="right")

        def mk_action(text, cmd):
            lbl = tk.Label(actions, text=text, fg=GREEN, bg=BLACK,
                           font=(fam, 10, "bold"), cursor="pointinghand",
                           padx=8)
            lbl.pack(side="left")
            lbl.bind("<ButtonRelease-1>", lambda _e: cmd())
            return lbl

        self.btn_1h = mk_action("1H", lambda: self._nag_run("snooze", "1h"))
        self.btn_eod = mk_action("EOD", lambda: self._nag_run("snooze", "eod"))
        self.btn_toggle = mk_action("STOP", self._nag_toggle)

        # Main container
        outer = tk.Frame(self.root, bg=BLACK, padx=24, pady=14)
        outer.pack(fill="both", expand=True)
        self._outer = outer

        # Top bar
        top = tk.Frame(outer, bg=BLACK)
        top.pack(fill="x")
        self.dot = tk.Label(top, text="●", fg=MUTED, bg=BLACK, font=F_DOT)
        self.dot.pack(side="left")
        self.status = tk.Label(top, text="…", fg=MUTED, bg=BLACK, font=F_STATUS)
        self.status.pack(side="left", padx=(6, 0))
        # Green CTA pill on the right — cały widget i tak klikalny, ale CTA daje affordance
        self.cta = tk.Label(top, text="OPEN EVERHOUR ↗",
                            fg=BLACK, bg=GREEN, font=(fam, 10, "bold"),
                            padx=10, pady=4, cursor="pointinghand")
        self.cta.pack(side="right")

        # Center (static widgets — never re-created)
        center = tk.Frame(outer, bg=BLACK)
        center.pack(fill="both", expand=True, pady=(8, 0))
        self._center = center
        self._top = top
        self.task_lbl = tk.Label(center, text="", fg=MUTED, bg=BLACK,
                                 font=F_TASK, anchor="w")
        self.task_lbl.pack(fill="x")
        self.big_lbl = tk.Label(center, text="", fg=WHITE, bg=BLACK,
                                font=F_BIG, anchor="w")
        self.big_lbl.pack(fill="x")

        # Click-anywhere-but-close opens Everhour. Drag from top bar moves window.
        self._press_xy = None
        self._press_root = None
        click_targets = [outer, top, self.dot, self.status, self.cta, center,
                         self.task_lbl, self.big_lbl]
        for w in click_targets:
            w.bind("<ButtonPress-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_motion)
            w.bind("<ButtonRelease-1>", self._on_release)

        self._state = None
        self._duration = 0
        self._previous = 0  # seconds previously logged on this task
        self._dragging = False
        self._nag_state = None

        self._render_idle()
        self._refresh_nag()
        self.sync()
        self.tick()
        self.root.mainloop()

    # --- nag controls ---
    def _nag_run(self, *args):
        log(f"nag {args}")
        def worker():
            subprocess.run([str(NAG_SCRIPT), *args],
                           capture_output=True, timeout=10)
            self.root.after(0, self._refresh_nag)
        threading.Thread(target=worker, daemon=True).start()

    def _nag_toggle(self):
        # If running → bootout (stop). If stopped → bootstrap (start).
        if self._nag_state in ("active", "snoozed"):
            log("nag stop")
            cmd = ["launchctl", "bootout", f"gui/{__import__('os').getuid()}/{NAG_LABEL}"]
        else:
            log("nag start")
            cmd = ["launchctl", "bootstrap",
                   f"gui/{__import__('os').getuid()}", str(NAG_PLIST)]

        def worker():
            subprocess.run(cmd, capture_output=True, timeout=10)
            # If we resumed from "stopped", also clear any stale snooze
            if self._nag_state == "stopped":
                SNOOZE_FILE.unlink(missing_ok=True)
            self.root.after(0, self._refresh_nag)
        threading.Thread(target=worker, daemon=True).start()

    def _refresh_nag(self):
        def worker():
            state, label = nag_status()
            self.root.after(0, lambda: self._apply_nag(state, label))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_nag(self, state: str, label: str):
        self._nag_state = state
        status_color = {"active": GREEN, "snoozed": MUTED, "stopped": RED}[state]
        self.nag_lbl.config(text=label, fg=status_color)
        if state == "stopped":
            self.btn_toggle.config(text="START", fg=GREEN)
            self.btn_1h.config(fg=MUTED, cursor="arrow")
            self.btn_eod.config(fg=MUTED, cursor="arrow")
        else:
            self.btn_toggle.config(text="STOP", fg=RED)
            self.btn_1h.config(fg=GREEN, cursor="pointinghand")
            self.btn_eod.config(fg=GREEN, cursor="pointinghand")

    # --- click vs drag dispatch ---
    def _on_press(self, e):
        self._press_xy = (e.x_root, e.y_root)
        self._press_root = (self.root.winfo_x(), self.root.winfo_y())
        self._dragging = False

    def _on_motion(self, e):
        if self._press_xy is None:
            return
        dx = e.x_root - self._press_xy[0]
        dy = e.y_root - self._press_xy[1]
        if not self._dragging and (abs(dx) > self.DRAG_THRESHOLD or abs(dy) > self.DRAG_THRESHOLD):
            self._dragging = True
        if self._dragging:
            nx = self._press_root[0] + dx
            ny = self._press_root[1] + dy
            self.root.geometry(f"+{nx}+{ny}")

    def _on_release(self, _e):
        if self._dragging:
            try:
                POS_FILE.write_text(f"{self.root.winfo_x()},{self.root.winfo_y()}")
            except Exception:
                pass
        else:
            # Treat as click → open Everhour immediately, in background
            self._open_everhour()
        self._press_xy = None
        self._dragging = False

    def _open_everhour(self):
        log("click → open everhour")
        threading.Thread(
            target=lambda: subprocess.run(
                ["osascript", "-e", f'open location "{EVERHOUR_URL}"'],
                capture_output=True, timeout=10,
            ),
            daemon=True,
        ).start()

    # --- position ---
    def _load_pos(self) -> tuple[int, int]:
        try:
            x, y = POS_FILE.read_text().split(",")
            return int(x), int(y)
        except Exception:
            return 80, 80

    # --- state rendering: only mutates existing widgets, no rebuild ---
    def _set_main_bg(self, bg: str):
        """Repaint top + center (not footer, not accent stripes, not CTA)."""
        for w in (self.root, self._outer, self._top, self._center,
                  self.dot, self.status, self.task_lbl, self.big_lbl):
            w.config(bg=bg)

    def _render_idle(self):
        self._state = "idle"
        self._set_main_bg(IDLE_BG)
        self.dot.config(fg=WHITE)
        self.status.config(text="NOT TRACKING", fg=WHITE)
        self.task_lbl.config(text="Everhour mruga ostrzegawczo.", fg=IDLE_MUTED)
        self.big_lbl.config(text="Włącz timer ⚠️", fg=WHITE,
                            font=self._F_BIG, justify="left")
        self.cta.pack_forget()

    def _render_active(self, task_name: str):
        self._state = "active"
        self._set_main_bg(BLACK)
        self.dot.config(fg=GREEN)
        self.status.config(text="TRACKING", fg=MUTED)
        self.task_lbl.config(text=task_name or "—", fg=MUTED)
        self.big_lbl.config(text=fmt_duration(self._duration + self._previous),
                            fg=WHITE, font=self._F_BIG, justify="left")
        # Re-show the CTA if it was hidden in the idle state
        if not self.cta.winfo_ismapped():
            self.cta.pack(side="right")

    # --- local 1s tick: counter + event-loop pump (keeps clicks responsive) ---
    def tick(self):
        if self._state == "active":
            self._duration += 1
            self.big_lbl.config(
                text=fmt_duration(self._duration + self._previous))
        self.root.after(TICK_MS, self.tick)

    # --- network sync every 30s ---
    def sync(self):
        if not self.token:
            self.status.config(text="NO TOKEN at ~/.everhour-token")
            self.root.after(SYNC_MS, self.sync)
            return

        def worker():
            timer = fetch_timer(self.token)
            self.root.after(0, lambda: self._apply(timer))

        threading.Thread(target=worker, daemon=True).start()
        self._refresh_nag()
        self.root.after(SYNC_MS, self.sync)

    def _apply(self, timer: dict | None):
        if timer is None:
            self.status.config(text="OFFLINE")
            return
        if timer.get("status") == "active":
            task = timer.get("task") or {}
            self._duration = int(timer.get("duration", 0))
            self._previous = int((task.get("time") or {}).get("total", 0))
            self._render_active(task.get("name", ""))
        else:
            self._render_idle()


if __name__ == "__main__":
    Widget()
