#!/usr/bin/env python3
"""Sprawdza czy w Everhour jest aktywny timer. Jeśli nie — pokazuje notyfikację."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TOKEN_FILE = Path.home() / ".everhour-token"
SNOOZE_FILE = Path.home() / ".everhour-nag-snooze"
EVERHOUR_URL = "https://app.everhour.com/#/time"
API_URL = "https://api.everhour.com/timers/current"
LOG_FILE = Path.home() / "Library/Logs/everhour-nag.log"
TZ_WARSAW = "Europe/Warsaw"


def log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    with LOG_FILE.open("a") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")


def read_token() -> str:
    if not TOKEN_FILE.exists():
        log(f"Brak {TOKEN_FILE}")
        sys.exit(0)
    return TOKEN_FILE.read_text().strip()


def get_current_timer(token: str) -> dict | None:
    # curl używa macOS Keychain → działa nawet z corporate MITM (Zscaler itp.)
    try:
        result = subprocess.run(
            ["curl", "-fsS", "--max-time", "10",
             "-H", f"X-Api-Key: {token}", API_URL],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            log(f"curl rc={result.returncode}: {result.stderr.strip()[:200]}")
            return None
        return json.loads(result.stdout)
    except Exception as e:
        log(f"Błąd: {e}")
        return None


def notify(title: str, message: str) -> None:
    # Preferuj terminal-notifier (klikalna notyfikacja → otwiera Everhour)
    tn = shutil.which("terminal-notifier")
    if tn:
        subprocess.run([
            tn,
            "-title", title,
            "-message", message,
            "-open", EVERHOUR_URL,
            "-sound", "Pop",
            "-group", "everhour-nag",
        ], check=False)
        return

    # Fallback: natywna notyfikacja przez osascript (nieklikalna)
    script = f'display notification "{message}" with title "{title}" sound name "Pop"'
    subprocess.run(["osascript", "-e", script], check=False)


def now_warsaw():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(TZ_WARSAW))


def snooze_active() -> bool:
    if not SNOOZE_FILE.exists():
        return False
    try:
        until_iso = SNOOZE_FILE.read_text().strip()
        from datetime import datetime
        until = datetime.fromisoformat(until_iso)
        if now_warsaw() < until:
            return True
        SNOOZE_FILE.unlink(missing_ok=True)
    except Exception as e:
        log(f"Snooze parse error: {e}")
    return False


def cmd_snooze(arg: str) -> None:
    from datetime import timedelta
    now = now_warsaw()
    arg = arg.lower().strip()
    if arg in ("eod", "today", "day"):
        until = now.replace(hour=23, minute=59, second=59, microsecond=0)
        label = f"do końca dnia ({until.strftime('%H:%M')} CEST)"
    elif arg.endswith("h"):
        until = now + timedelta(hours=float(arg[:-1]))
        label = f"do {until.strftime('%H:%M')} CEST"
    elif arg.endswith("m"):
        until = now + timedelta(minutes=float(arg[:-1]))
        label = f"do {until.strftime('%H:%M')} CEST"
    else:
        print("Użycie: everhour_nag.py snooze <1h|30m|eod>")
        sys.exit(1)
    SNOOZE_FILE.write_text(until.isoformat())
    print(f"💤 Cisza {label}.  Wznów: everhour_nag.py resume")


def cmd_resume() -> None:
    SNOOZE_FILE.unlink(missing_ok=True)
    print("🔔 Wznowione.")


def cmd_status() -> None:
    if snooze_active():
        until = SNOOZE_FILE.read_text().strip()
        print(f"💤 Snooze do {until}")
    else:
        print("🔔 Aktywne — sprawdza co 10 min.")


def main() -> None:
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "snooze" and len(sys.argv) > 2:
            return cmd_snooze(sys.argv[2])
        if cmd == "resume":
            return cmd_resume()
        if cmd == "status":
            return cmd_status()
        print("Komendy: snooze <1h|30m|eod> | resume | status")
        sys.exit(1)

    if snooze_active():
        log("Snooze aktywny — pomijam")
        return

    token = read_token()
    timer = get_current_timer(token)

    if timer is None:
        # Błąd sieci/API — nie spamujemy notyfikacjami
        return

    status = timer.get("status", "stopped")
    if status == "active":
        log("OK — timer aktywny")
        return

    log("Brak timera — notyfikacja")
    notify(
        title="⏱️ Nie trackujesz czasu",
        message="Co robisz? Kliknij żeby otworzyć Everhour.",
    )


if __name__ == "__main__":
    main()
