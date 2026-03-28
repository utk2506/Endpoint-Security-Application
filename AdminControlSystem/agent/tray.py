"""
tray.py — System tray icon and agent console UI window.
"""

import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from config import AGENT_VERSION, SERVICE_NAME
from logger import log
from state import load_state, save_state, dequeue_notification
from commands import execute_modern_notify


def _create_tray_image():
    """Generate a simple shield icon programmatically using Pillow."""
    from PIL import Image, ImageDraw  # type: ignore
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.polygon([(32, 4), (58, 16), (58, 36), (32, 60), (6, 36), (6, 16)], fill=(26, 37, 53))
    try:
        draw.text((22, 18), "A", fill=(255, 255, 255))
    except Exception:
        pass
    return img


def run_with_tray(server: str, device_id, auto_open: bool = False) -> None:
    """Show a system tray icon; runs agent console UI in the foreground (tkinter mainloop)."""
    try:
        import pystray  # type: ignore
    except ImportError:
        log('WARN', "pystray not installed — running without tray.")
        from agent import main_loop
        main_loop(server, device_id)
        return

    import tkinter as tk
    win = tk.Tk()
    win.withdraw()

    # Resolve log path (matches logger.py logic)
    exe_dir = Path(os.path.dirname(os.path.abspath(sys.executable)))
    log_path = Path(os.environ.get("TEMP", ".")) / "agent_debug.log"
    if "Program Files" in str(exe_dir):
        log_path = exe_dir / "agent_debug.log"

    def read_log_tail(lines: int = 200) -> str:
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                return ''.join(f.readlines()[-lines:])
        except Exception:
            return "No log entries yet."

    def open_console(icon=None, item=None):
        try:
            win.deiconify()
            win.lift()
            win.focus_force()
        except Exception:
            pass

    def on_open_log(icon, item):
        if hasattr(os, "startfile") and os.path.exists(log_path):
            os.startfile(str(log_path))

    def _setup_ui(win):
        try:
            from tkinter import ttk, scrolledtext
            try:
                from PIL import ImageTk  # type: ignore
                import PIL.Image  # type: ignore
            except ImportError:
                ImageTk = None  # type: ignore

            base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
            icon_path = base_dir / "assets" / "sentraguard_tray.png"

            C = {
                "bg": "#0B1F2A", "bg2": "#0F2D3B", "card": "#121820",
                "accent": "#1E90FF", "accent2": "#1474d6",
                "green": "#00E676", "yellow": "#FFC107", "red": "#FF3D00",
                "text": "#E8F3FF", "muted": "#9FB6C8", "border": "#1F3542", "log_bg": "#0F1722"
            }

            win.title("SentraGuard Agent Console")
            win.geometry("900x620")
            win.minsize(760, 520)
            win.configure(bg=C["bg"])

            try:
                if ImageTk:
                    _img = PIL.Image.open(icon_path).convert("RGBA") if icon_path.exists() else _create_tray_image()
                    _img = _img.resize((48, 48))
                    tk_icon = ImageTk.PhotoImage(_img)
                    win.iconphoto(False, tk_icon)
                    win._sg_icon = tk_icon  # type: ignore[attr-defined]
            except Exception as e:
                log('WARN', f"Failed to set window icon: {e}")

            style = ttk.Style(win)
            style.theme_use("clam")
            style.configure("TFrame", background=C["bg"])
            style.configure("Card.TFrame", background=C["card"])
            style.configure("TLabel", background=C["bg"], foreground=C["text"], font=("Segoe UI", 10))
            style.configure("Card.TLabel", background=C["card"], foreground=C["text"], font=("Segoe UI", 10))
            style.configure("TButton", background=C["accent"], foreground="white", relief="flat",
                            borderwidth=0, font=("Segoe UI", 9, "bold"), padding=(12, 6))
            style.map("TButton", background=[("active", C["accent2"])])

            # Header
            hdr = tk.Frame(win, bg=C["bg"], height=72)
            hdr.pack(fill="x", side="top", pady=(6, 0))
            hdr.pack_propagate(False)
            left = tk.Frame(hdr, bg=C["bg"])
            left.pack(side="left", padx=14, pady=6)
            try:
                if ImageTk:
                    header_icon_path = base_dir / "assets" / "sentraguard_logo.png"
                    if not header_icon_path.exists():
                        header_icon_path = icon_path
                    _himg = PIL.Image.open(header_icon_path).convert("RGBA")
                    h = 44
                    w = int(h * _himg.width / _himg.height)
                    _himg = _himg.resize((w, h))
                    tk_h_icon = ImageTk.PhotoImage(_himg)
                    lbl = tk.Label(left, image=tk_h_icon, bg=C["bg"])
                    lbl.image = tk_h_icon
                    lbl.grid(row=0, column=0, rowspan=2, padx=(0, 10))
            except Exception:
                tk.Label(left, text="🛡️", bg=C["bg"], fg=C["green"], font=("Segoe UI Emoji", 28)).grid(row=0, column=0, rowspan=2, padx=(0, 10))

            right = tk.Frame(hdr, bg=C["bg"])
            right.pack(side="right", padx=14, pady=10)
            update_status_var = tk.StringVar(value="Latest version")
            tk.Label(right, textvariable=update_status_var, bg=C["bg"], fg=C["muted"], font=("Segoe UI", 9)).pack(side="bottom", anchor="e")
            refresh_btn = ttk.Button(right, text="Update now", style="TButton")
            refresh_btn.pack(side="top")

            # Body
            body = ttk.Frame(win, style="TFrame", padding=16)
            body.pack(fill="both", expand=True)

            # Issues card
            issues = tk.Frame(body, bg=C["card"], padx=12, pady=12, highlightbackground=C["border"], highlightthickness=1)
            issues.pack(fill="x", pady=(0, 12))
            tk.Label(issues, text="Issues", bg=C["card"], fg=C["text"], font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))
            issue_row = tk.Frame(issues, bg=C["card"])
            issue_row.pack(fill="x")
            issue_icon = tk.Label(issue_row, text="⏳", bg=C["card"], fg=C["yellow"], font=("Segoe UI", 12))
            issue_icon.pack(side="left", padx=(4, 6))
            issue_text = tk.Label(issue_row, text="Awaiting first check-in.", bg=C["card"], fg=C["text"], font=("Segoe UI", 10))
            issue_text.pack(side="left", fill="x", expand=True)

            # Status cards
            cards_row = ttk.Frame(body, style="TFrame")
            cards_row.pack(fill="x", pady=(0, 12))
            status_var = tk.StringVar(value="Unknown")
            device_var = tk.StringVar(value=str(device_id))
            server_var = tk.StringVar(value=server)
            sync_var = tk.StringVar(value="—")
            version_var = tk.StringVar(value=AGENT_VERSION)

            def _card(parent, heading, var, colour=None):
                f = tk.Frame(parent, bg=C["card"], padx=12, pady=10, highlightbackground=C["border"], highlightthickness=1)
                tk.Label(f, text=heading, bg=C["card"], fg=C["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
                f_size = 9 if heading in ["Device ID", "Server"] else 11
                w_len = 260 if heading == "Device ID" else 220
                tk.Label(f, textvariable=var, bg=C["card"], fg=colour or C["text"],
                         font=("Segoe UI", f_size, "bold"), wraplength=w_len, justify="left").pack(anchor="w", pady=(4, 0))
                return f

            for col, (title, var, colour) in enumerate([
                ("Status", status_var, C["green"]),
                ("Device ID", device_var, None),
                ("Server", server_var, None),
                ("Last Sync", sync_var, None),
                ("Agent Version", version_var, None),
            ]):
                cards_row.columnconfigure(col, weight=1)
                _card(cards_row, title, var, colour).grid(row=0, column=col, padx=(0, 8 if col < 4 else 0), sticky="nsew")

            log_hdr = ttk.Frame(body, style="TFrame")
            log_hdr.pack(fill="x", pady=(6, 4))
            tk.Label(log_hdr, text="Recent Log", bg=C["bg"], fg=C["text"], font=("Segoe UI", 10, "bold")).pack(side="left")
            log_open_btn = ttk.Button(log_hdr, text="Open File", style="TButton")
            log_open_btn.pack(side="right", padx=(0, 6))
            log_refresh_btn = ttk.Button(log_hdr, text="Refresh", style="TButton")
            log_refresh_btn.pack(side="right", padx=(0, 6))

            log_frame = tk.Frame(body, bg=C["log_bg"], highlightbackground=C["border"], highlightthickness=1)
            log_frame.pack(fill="both", expand=True)
            log_box = scrolledtext.ScrolledText(log_frame, bg=C["log_bg"], fg=C["text"],
                                                insertbackground=C["text"], font=("Consolas", 9),
                                                relief="flat", borderwidth=0, wrap="word")
            log_box.pack(fill="both", expand=True, padx=4, pady=4)
            log_box.configure(state="disabled")

            footer = tk.Frame(win, bg=C["bg"], height=28)
            footer.pack(fill="x", side="bottom")
            tk.Label(footer, text=f"{SERVICE_NAME} tray console • v{AGENT_VERSION}",
                     bg=C["bg"], fg=C["muted"], font=("Segoe UI", 8)).pack(side="left", padx=12, pady=4)

            def status_from_state(s):
                last = s.get("last_seen") or s.get("last_sync")
                if not last:
                    return "Unknown", C["yellow"]
                try:
                    ts = datetime.fromisoformat(last.replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - ts).total_seconds()
                    if age < 60:
                        return "Online", C["green"]
                    if age < 300:
                        return "Idle", C["yellow"]
                    return "Offline", C["red"]
                except Exception:
                    return "Unknown", C["yellow"]

            def refresh_all():
                s = load_state()
                label, colour = status_from_state(s)
                status_var.set(label)
                device_var.set(s.get("device_id", "—"))
                last_seen_val = s.get("last_seen") or s.get("last_sync")
                if last_seen_val:
                    try:
                        ts = datetime.fromisoformat(last_seen_val.replace("Z", "+00:00"))
                        sync_var.set(ts.strftime("%Y-%m-%d %H:%M"))
                    except Exception:
                        sync_var.set("—")
                else:
                    sync_var.set("—")

                current_ver = s.get("agent_version", AGENT_VERSION)
                latest_ver = s.get("latest_version", current_ver)
                has_update = bool(s.get("update_available"))
                version_var.set(current_ver)
                update_status_var.set(f"Update available: {latest_ver}" if has_update else f"Latest version: {latest_ver}")

                if colour == C["red"]:
                    issue_icon.config(text="⛔", fg=C["red"])
                    issue_text.config(text="Unprotected — Agent is offline.", fg=C["red"])
                elif colour == C["yellow"]:
                    issue_icon.config(text="⚠", fg=C["yellow"])
                    issue_text.config(text="Action needed — Device idle.", fg=C["yellow"])
                else:
                    issue_icon.config(text="✅", fg=C["green"])
                    issue_text.config(text="Protected — System is secure.", fg=C["green"])

                log_box.configure(state="normal")
                log_box.delete("1.0", "end")
                log_box.insert("end", read_log_tail(150))
                log_box.configure(state="disabled")

            def auto_refresh():
                if not win.winfo_exists():
                    return
                refresh_all()
                win.after(5000, auto_refresh)

            def request_update_now():
                try:
                    s = load_state()
                    s["force_update_check"] = True
                    save_state(s)
                    update_status_var.set("Checking for updates…")
                except Exception:
                    update_status_var.set("Update request failed")
                refresh_all()

            refresh_btn.configure(command=request_update_now)
            log_refresh_btn.configure(command=refresh_all)
            log_open_btn.configure(command=lambda: os.startfile(str(log_path)) if os.path.exists(log_path) else None)
            win.protocol("WM_DELETE_WINDOW", win.withdraw)
            refresh_all()
            win.after(5000, auto_refresh)
        except Exception as e:
            import traceback
            log('ERROR', f'Console UI Crash: {e}\n{traceback.format_exc()}')

    def flush_queued_notifications():
        import time
        while True:
            try:
                msg = dequeue_notification()
                if msg:
                    execute_modern_notify(msg)
            except Exception:
                pass
            time.sleep(5)

    try:
        base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        icon_path = base_dir / "assets" / "sentraguard_tray.png"
        try:
            import PIL.Image  # type: ignore
            icon_image = PIL.Image.open(icon_path).convert("RGBA") if icon_path.exists() else _create_tray_image()
        except Exception:
            icon_image = _create_tray_image()

        menu = pystray.Menu(
            pystray.MenuItem("Open Console", open_console, default=True),
            pystray.MenuItem("Open Log", on_open_log),
        )
        tray = pystray.Icon("SentraGuard Agent", icon_image, "SentraGuard Agent", menu)
        tray.default_action = open_console
    except Exception as e:
        import traceback
        log('ERROR', f"🚨 Tray Setup Crash: {e}\n{traceback.format_exc()}")
        raise

    _setup_ui(win)
    if auto_open:
        win.after(100, open_console)

    log('INFO', "🛡️  SentraGuard tray is active. Right-click the tray for status and logs.")

    threading.Thread(target=flush_queued_notifications, daemon=True).start()
    threading.Thread(target=lambda: tray.run(), daemon=True).start()
    win.mainloop()
