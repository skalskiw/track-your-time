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
SETTINGS_FILE = Path.home() / ".everhour-settings.json"
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
OFF_BG = "#1E40AF"         # blue-800 — off-hours chill background
OFF_MUTED = "#BFDBFE"      # blue-200 — muted text on the blue bg
ACCENT_H = 4        # height of the top accent stripe (under title bar)

DEFAULT_SETTINGS = {
    "schedule": "weekdays",   # "always" | "weekdays"
    "start_hour": 8,
    "end_hour": 17,
}

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

MASCOT_ACTIVE = "😎"
MASCOT_IDLE_POOL = ["😔", "😒", "😟"]
MASCOT_OFF = "🏖️"
MASCOT_SIZE = 56


def log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    with LOG_FILE.open("a") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")


def load_settings() -> dict:
    try:
        if SETTINGS_FILE.exists():
            with SETTINGS_FILE.open() as f:
                return {**DEFAULT_SETTINGS, **json.load(f)}
    except Exception as e:
        log(f"load_settings: {e}")
    return dict(DEFAULT_SETTINGS)


def save_settings(s: dict) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(s, indent=2))
    except Exception as e:
        log(f"save_settings: {e}")


def is_off_hours(settings: dict | None = None) -> bool:
    """True if widget should be in chill/off mode (outside configured hours)."""
    from datetime import datetime
    s = settings if settings is not None else load_settings()
    if s.get("schedule") == "always":
        return False
    now = datetime.now()
    if now.weekday() >= 5:              # Sat / Sun
        return True
    start = int(s.get("start_hour", 8))
    end = int(s.get("end_hour", 17))
    return not (start <= now.hour < end)


def off_hours_return_text(settings: dict | None = None) -> str:
    """Friendly 'Wracamy ...' label pointing to the next business-hours start."""
    from datetime import datetime
    s = settings if settings is not None else load_settings()
    start = int(s.get("start_hour", 8))
    now = datetime.now()
    wd = now.weekday()
    if wd < 5 and now.hour < start:
        return "Wracamy niedługo"
    if wd in (4, 5, 6):                 # Fri after hours / Sat / Sun
        return "Wracamy w poniedziałek"
    return "Wracamy jutro"


def read_token() -> str | None:
    return TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else None


def stop_timer(token: str) -> None:
    """Fire DELETE /timers/current — ignore result, optimistic UI handles it."""
    try:
        subprocess.run(
            ["curl", "-fsS", "--max-time", "10",
             "-X", "DELETE", "-H", f"X-Api-Key: {token}", API_URL],
            capture_output=True, timeout=15,
        )
    except Exception as e:
        log(f"stop_timer error: {e}")


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


def _sum_today_from_history(timer: dict) -> int:
    """Sum seconds logged TODAY on this task (excluding current running session).

    Everhour returns `currentTaskTime.history` with entries having
    `time` (running total after this entry) and `previousTime` (before),
    so the per-entry delta is (time - previousTime). `userDate` is the
    user's current local date in YYYY-MM-DD form — we match createdAt
    prefix against it.
    """
    today = timer.get("userDate", "")
    if not today:
        return 0
    history = ((timer.get("currentTaskTime") or {}).get("history")) or []
    total = 0
    for entry in history:
        if not isinstance(entry, dict):
            continue
        created = entry.get("createdAt", "")
        if not created.startswith(today):
            continue
        delta = int(entry.get("time", 0)) - int(entry.get("previousTime", 0))
        if delta > 0:
            total += delta
    return total


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
        self._fam = fam
        F_BIG = (fam, 44, "bold")
        F_IDLE = (fam, 32, "bold")
        F_OFF = (fam, 22, "bold")
        F_TASK = (fam, 13)
        F_STATUS = (fam, 10, "bold")
        F_HINT = (fam, 11)
        F_DOT = (fam, 14)
        self._F_BIG = F_BIG
        self._F_IDLE = F_IDLE
        self._F_OFF = F_OFF

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

        # Gear icon (settings) — far left
        self.gear = tk.Label(footer, text="⚙", fg=MUTED, bg=BLACK,
                             font=(fam, 14), cursor="pointinghand")
        self.gear.pack(side="left", padx=(0, 10))
        self.gear.bind("<ButtonRelease-1>", lambda _e: self._open_settings())

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

        # Mascot on the far right; STOP icon between timer and mascot; text column on the left
        self.mascot = tk.Label(center, text="", bg=BLACK,
                               font=("Helvetica Neue", MASCOT_SIZE))
        self.mascot.pack(side="right", padx=(10, 0))

        # STOP icon — red circle with a white square. Stationary, only shown when active.
        # Bound directly (not via click_targets) so it doesn't open Everhour.
        STOP_SIZE = 44
        self.stop_btn = tk.Canvas(center, width=STOP_SIZE, height=STOP_SIZE,
                                  bg=BLACK, highlightthickness=0, bd=0,
                                  cursor="pointinghand")
        self.stop_btn.create_oval(2, 2, STOP_SIZE - 2, STOP_SIZE - 2,
                                  fill=RED, outline=RED)
        sq = STOP_SIZE * 0.32
        cx = STOP_SIZE / 2
        self.stop_btn.create_rectangle(cx - sq / 2, cx - sq / 2,
                                       cx + sq / 2, cx + sq / 2,
                                       fill=WHITE, outline=WHITE)
        self.stop_btn.bind("<ButtonRelease-1>", lambda _e: self._on_stop())

        text_col = tk.Frame(center, bg=BLACK)
        text_col.pack(side="left", fill="both", expand=True)
        self._text_col = text_col
        self.task_lbl = tk.Label(text_col, text="", fg=MUTED, bg=BLACK,
                                 font=F_TASK, anchor="w")
        self.task_lbl.pack(fill="x")
        self.big_lbl = tk.Label(text_col, text="", fg=WHITE, bg=BLACK,
                                font=F_BIG, anchor="w")
        self.big_lbl.pack(fill="x")
        self.total_lbl = tk.Label(text_col, text="", fg=MUTED, bg=BLACK,
                                  font=(fam, 11), anchor="w")
        self.total_lbl.pack(fill="x")

        # Click-anywhere-but-close opens Everhour. Drag from top bar moves window.
        self._press_xy = None
        self._press_root = None
        click_targets = [outer, top, self.dot, self.status, self.cta, center,
                         text_col, self.task_lbl,
                         self.big_lbl, self.total_lbl, self.mascot]
        for w in click_targets:
            w.bind("<ButtonPress-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_motion)
            w.bind("<ButtonRelease-1>", self._on_release)

        self._state = None
        self._duration = 0       # current running session
        self._today_logged = 0   # seconds already logged today on this task
        self._lifetime = 0       # life-of-task total (already logged)
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
                  self._text_col, self.dot, self.status, self.task_lbl,
                  self.big_lbl, self.total_lbl, self.mascot):
            w.config(bg=bg)


    def _render_idle(self):
        first_time = self._state != "idle"
        self._state = "idle"
        self._set_main_bg(IDLE_BG)
        self.dot.config(fg=WHITE)
        self.status.config(text="NOT TRACKING", fg=WHITE)
        self.task_lbl.config(text="Chyba o czymś zapomniałeś…", fg=IDLE_MUTED)
        self.big_lbl.config(text="Włącz timer!", fg=WHITE,
                            font=self._F_BIG, justify="left")
        self.total_lbl.config(text="")
        if first_time:
            self.mascot.config(text=random.choice(MASCOT_IDLE_POOL))
        # CTA stays in place — black pill with white text on the red bg
        self.cta.config(bg=BLACK, fg=WHITE)
        # No active timer to stop
        self.stop_btn.pack_forget()

    def _render_active(self, task_name: str):
        self._state = "active"
        self._set_main_bg(BLACK)
        self.dot.config(fg=GREEN)
        self.status.config(text="TRACKING", fg=MUTED)
        self.task_lbl.config(text=task_name or "—", fg=MUTED)
        self._refresh_time_labels()
        self.mascot.config(text=MASCOT_ACTIVE)
        # Restore green CTA palette
        self.cta.config(bg=GREEN, fg=BLACK)
        # Show STOP icon between text_col and mascot (only while tracking)
        if not self.stop_btn.winfo_ismapped():
            self.stop_btn.pack(side="right", padx=(16, 4), before=self.mascot)
        self.stop_btn.config(bg=BLACK)

    def _render_off(self):
        """Outside business hours — chill blue, no tracking nag."""
        self._state = "off"
        self._set_main_bg(OFF_BG)
        self.dot.config(fg=WHITE)
        self.status.config(text="OFF HOURS", fg=WHITE)
        self.task_lbl.config(text="Po godzinach. Spokojnie.", fg=OFF_MUTED)
        self.big_lbl.config(text=off_hours_return_text(),
                            fg=WHITE, font=self._F_OFF, justify="left")
        self.total_lbl.config(text="")
        self.mascot.config(text=MASCOT_OFF)
        # CTA stays in place but in muted palette (nothing urgent to do)
        self.cta.config(bg=BLACK, fg=WHITE)
        # No active timer to stop
        self.stop_btn.pack_forget()

    def _on_stop(self):
        log("stop click")
        # Optimistic UI: switch to idle instantly, then hit API in the background
        self._render_idle()
        if self.token:
            threading.Thread(
                target=lambda: stop_timer(self.token),
                daemon=True,
            ).start()


    def _refresh_time_labels(self):
        today = self._duration + self._today_logged
        total = self._duration + self._lifetime
        self.big_lbl.config(text=fmt_duration(today),
                            fg=WHITE, font=self._F_BIG, justify="left")
        # Hide total if it equals today (i.e. first time on this task)
        if total > today:
            h, rem = divmod(total, 3600)
            m, _ = divmod(rem, 60)
            self.total_lbl.config(text=f"total {h}:{m:02d}", fg=MUTED)
        else:
            self.total_lbl.config(text="")

    # --- local 1s tick: counter + event-loop pump (keeps clicks responsive) ---
    def tick(self):
        if self._state == "active":
            self._duration += 1
            self._refresh_time_labels()
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

    # --- settings dialog ---
    def _open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("Everhour Widget — Settings")
        win.configure(bg=BLACK)
        win.resizable(False, False)
        try:
            win.transient(self.root)
        except Exception:
            pass

        s = load_settings()
        fam = self._fam
        PAD_X = 24

        tk.Label(win, text="When should the widget bug you?",
                 bg=BLACK, fg=WHITE, font=(fam, 12, "bold"),
                 anchor="w").pack(fill="x", padx=PAD_X, pady=(20, 10))

        schedule_var = tk.StringVar(value=s.get("schedule", "weekdays"))
        radio_kwargs = dict(bg=BLACK, fg=WHITE,
                            selectcolor=BLACK,
                            activebackground=BLACK, activeforeground=WHITE,
                            highlightthickness=0, font=(fam, 11),
                            anchor="w")
        tk.Radiobutton(win, text="Always — every day, all the time",
                       variable=schedule_var, value="always",
                       **radio_kwargs).pack(fill="x", padx=PAD_X)
        tk.Radiobutton(win, text="Workdays only, business hours",
                       variable=schedule_var, value="weekdays",
                       **radio_kwargs).pack(fill="x", padx=PAD_X)

        tk.Label(win, text="Business hours (Mon–Fri):",
                 bg=BLACK, fg=MUTED, font=(fam, 10),
                 anchor="w").pack(fill="x", padx=PAD_X, pady=(16, 4))

        hours = tk.Frame(win, bg=BLACK)
        hours.pack(fill="x", padx=PAD_X)

        start_var = tk.IntVar(value=int(s.get("start_hour", 8)))
        end_var = tk.IntVar(value=int(s.get("end_hour", 17)))

        tk.Label(hours, text="from", bg=BLACK, fg=WHITE,
                 font=(fam, 11)).pack(side="left")
        tk.Spinbox(hours, from_=0, to=23, width=3, textvariable=start_var,
                   font=(fam, 11)).pack(side="left", padx=6)
        tk.Label(hours, text=":00    to", bg=BLACK, fg=WHITE,
                 font=(fam, 11)).pack(side="left")
        tk.Spinbox(hours, from_=0, to=23, width=3, textvariable=end_var,
                   font=(fam, 11)).pack(side="left", padx=6)
        tk.Label(hours, text=":00", bg=BLACK, fg=WHITE,
                 font=(fam, 11)).pack(side="left")

        btn_row = tk.Frame(win, bg=BLACK)
        btn_row.pack(fill="x", padx=PAD_X, pady=(20, 20))

        def do_save():
            try:
                sh = max(0, min(23, int(start_var.get())))
                eh = max(0, min(24, int(end_var.get())))
                if eh <= sh:
                    eh = sh + 1
            except Exception:
                sh = DEFAULT_SETTINGS["start_hour"]
                eh = DEFAULT_SETTINGS["end_hour"]
            save_settings({
                "schedule": schedule_var.get(),
                "start_hour": sh,
                "end_hour": eh,
            })
            log(f"settings saved: schedule={schedule_var.get()} {sh}:00-{eh}:00")
            win.destroy()
            # Force immediate re-render based on new settings + fresh fetch
            if self.token:
                def refresh():
                    t = fetch_timer(self.token)
                    self.root.after(0, lambda: self._apply(t))
                threading.Thread(target=refresh, daemon=True).start()

        cancel = tk.Label(btn_row, text="Cancel", fg=MUTED, bg=BLACK,
                          font=(fam, 11, "bold"), cursor="pointinghand",
                          padx=8)
        cancel.pack(side="right", padx=(8, 0))
        cancel.bind("<ButtonRelease-1>", lambda _e: win.destroy())

        save_btn = tk.Label(btn_row, text="Save", fg=BLACK, bg=GREEN,
                            font=(fam, 11, "bold"), cursor="pointinghand",
                            padx=14, pady=4)
        save_btn.pack(side="right")
        save_btn.bind("<ButtonRelease-1>", lambda _e: do_save())

    def _apply(self, timer: dict | None):
        if timer is None:
            self.status.config(text="OFFLINE")
            return
        # Off-hours overrides idle nagging. An active timer still wins (you're
        # working overtime — show it), but never harass when nothing's running.
        if timer.get("status") == "active":
            task = timer.get("task") or {}
            self._duration = int(timer.get("duration", 0))
            self._lifetime = int((task.get("time") or {}).get("total", 0))
            self._today_logged = _sum_today_from_history(timer)
            self._render_active(task.get("name", ""))
        elif is_off_hours():
            self._render_off()
        else:
            self._render_idle()


if __name__ == "__main__":
    Widget()
