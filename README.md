# Track Your Time

Native macOS floating widget for [Everhour](https://everhour.com) — always-on-top, click anywhere to open Everhour, with an optional desktop nag that pokes you when you forget to start the timer.

Two scripts, zero dependencies beyond Python stdlib + `curl` (preinstalled on macOS). Built because Everhour's official menubar app didn't exist on Mac when I needed it.

## What you get

- **Floating timer widget** — current task + live H:MM:SS (running session + previously logged today), red alarm-state when nothing's tracking.
- **Click anywhere → opens Everhour** in your default browser.
- **Optional notification nag** every 10 minutes when no timer is running. Snooze 1h / EOD / fully stop — directly from the widget footer.
- **SG branding** — Poppins font, `#00C853` accent. Edit the constants at the top of `everhour_widget.py` if you want your own.

## Requirements

- macOS (Sequoia / Sonoma tested; should work on anything 12+).
- Python 3.10+ with Tkinter. The easiest way is the installer from [python.org](https://www.python.org/downloads/macos/) — their build ships Tk. Verify with:
  ```bash
  python3 -c "import tkinter; print(tkinter.TkVersion)"
  ```
- An [Everhour API token](https://app.everhour.com/#/account/profile) — Profile Settings → API Access.
- *(Optional)* The [Poppins](https://fonts.google.com/specimen/Poppins) font installed in Font Book for the intended look (falls back to Helvetica Neue otherwise).

---

## Install

### 1. Clone and put the scripts on your `PATH`-ish

```bash
git clone https://github.com/skalskiw/track-your-time.git
cd track-your-time
mkdir -p ~/bin
cp everhour_widget.py everhour_nag.py ~/bin/
chmod +x ~/bin/everhour_widget.py ~/bin/everhour_nag.py
```

### 2. Drop in your Everhour API token

```bash
echo 'PASTE_YOUR_TOKEN_HERE' > ~/.everhour-token
chmod 600 ~/.everhour-token
```

### 3. Launch the widget

```bash
~/bin/everhour_widget.py &
```

A window appears (~460×230). Drag it where you want — position is remembered between runs in `~/.everhour-widget-pos`.

### 4. (Optional) Enable notifications

Test the nag once:
```bash
~/bin/everhour_nag.py
```
You should get a native macOS notification if no timer is active. If nothing shows: System Settings → Notifications → find `Script Editor` (or `terminal-notifier` if you install it) → enable Allow Notifications.

For clickable notifications that open Everhour on tap:
```bash
brew install terminal-notifier
```

Schedule the nag every 10 minutes via launchd:
```bash
cat > ~/Library/LaunchAgents/com.wojtek.everhour-nag.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.wojtek.everhour-nag</string>
    <key>ProgramArguments</key>
    <array>
        <string>$(which python3)</string>
        <string>$HOME/bin/everhour_nag.py</string>
    </array>
    <key>StartInterval</key><integer>600</integer>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key><string>$HOME/Library/Logs/everhour-nag.stdout.log</string>
    <key>StandardErrorPath</key><string>$HOME/Library/Logs/everhour-nag.stderr.log</string>
</dict>
</plist>
EOF

launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.wojtek.everhour-nag.plist
launchctl list | grep everhour    # sanity check
```

> The label `com.wojtek.everhour-nag` is hardcoded in the widget so its footer can control the job. Cosmetic only — feel free to rename it in both `everhour_widget.py` (`NAG_LABEL`) and the plist.

### 5. (Optional) Autostart the widget at login

System Settings → General → **Login Items & Extensions** → **+** under "Open at Login" → `Cmd+Shift+G` → `~/bin` → pick `everhour_widget.py`.

---

## Using it

| Element | Action |
|---|---|
| Click anywhere on the widget body | Opens Everhour in your default browser |
| Footer **1H** | Snooze nag for 1 hour |
| Footer **EOD** | Snooze nag until end of day (Europe/Warsaw) |
| Footer **STOP** / **START** | Fully turn the nag launchd job off / on |
| Red dot in title bar | Closes the widget (relaunch with `~/bin/everhour_widget.py &`) |

CLI for the nag, if you prefer terminal over clicking:
```bash
~/bin/everhour_nag.py snooze 1h     # also: 30m, 2h, eod
~/bin/everhour_nag.py resume
~/bin/everhour_nag.py status
```

---

## Files this creates on your machine

| Path | Purpose |
|---|---|
| `~/bin/everhour_widget.py` | The widget |
| `~/bin/everhour_nag.py` | The notification script |
| `~/.everhour-token` | Your API token (chmod 600) |
| `~/.everhour-widget-pos` | Last window position |
| `~/.everhour-nag-snooze` | Snooze deadline if any |
| `~/Library/LaunchAgents/com.wojtek.everhour-nag.plist` | launchd job |
| `~/Library/Logs/everhour-{widget,nag}.log` | Logs |

---

## Uninstall

```bash
launchctl bootout gui/$UID ~/Library/LaunchAgents/com.wojtek.everhour-nag.plist
pkill -f everhour_widget.py
rm ~/bin/everhour_{widget,nag}.py
rm ~/.everhour-{token,widget-pos,nag-snooze}
rm ~/Library/LaunchAgents/com.wojtek.everhour-nag.plist
rm ~/Library/Logs/everhour-{widget,nag}*.log
```
Plus remove it from Login Items in System Settings.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'tkinter'`** — your Python install lacks Tk. Install Python from [python.org](https://www.python.org/downloads/macos/); their bundle includes it.

**SSL: CERTIFICATE_VERIFY_FAILED** — you're behind a corporate MITM (Zscaler / Cloudflare WARP). The scripts use system `curl` (which uses the macOS Keychain), so this normally just works. If it doesn't, debug with:
```bash
curl -v -H "X-Api-Key: $(cat ~/.everhour-token)" https://api.everhour.com/timers/current
```

**Widget shows up in a weird spot** — `rm ~/.everhour-widget-pos` to reset.

**Notifications don't appear** — System Settings → Notifications → find `Script Editor` (or `terminal-notifier`) → allow.

---

## How it works (short version)

- `everhour_widget.py` is a Tk window. Local 1s tick keeps the event loop warm (so clicks register fast) and ticks the visible counter. Network sync hits `GET /timers/current` every 5s in a background thread. All UI mutations stay on the main thread via `root.after(0, ...)`.
- `everhour_nag.py` is a one-shot script. launchd fires it on `StartInterval`. It checks `~/.everhour-nag-snooze` before doing anything, then hits the same Everhour endpoint; if status isn't active, fires a macOS notification (via `terminal-notifier` if installed, falling back to `osascript display notification`).
- Both shell out to `curl` rather than using `urllib`, specifically to respect the macOS Keychain on corporate networks.

---

## License

MIT — see [LICENSE](LICENSE).
