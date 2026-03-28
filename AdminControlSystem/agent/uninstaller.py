"""
uninstaller.py — OTP-protected agent uninstall flow (GUI dialog + PowerShell cleanup).
"""

import os
import shutil
import subprocess
import tempfile
import time

from config import AGENT_VERSION, SERVICE_NAME, CREATE_NO_WINDOW, CREATE_DEFAULT_ERROR_MODE, WINDLL
from logger import log
from network import api_call, powershell_available
from state import load_state, update_state
from system_info import get_hostname, get_ip
from watchdog import stop_service


def protected_uninstall_flow(
    server_url: str,
    otp: "str | None",
    service_name: str,
    install_root,
    verify_only: bool = False,
) -> bool:
    """Verify OTP with backend and (optionally) uninstall service + files."""
    state = load_state()
    device_id = state.get("device_id")

    if not device_id:
        resp = api_call(server_url, "POST", "/register", {
            "hostname": get_hostname(),
            "ip_address": get_ip(),
            "agent_version": AGENT_VERSION,
            "install_path": str(install_root),
        })
        if resp and resp.get("device_id"):
            device_id = resp["device_id"]
            update_state(device_id=device_id)

    if not device_id:
        log("ERROR", "Cannot determine device ID; uninstall aborted.")
        return False

    code = None

    if otp:
        code = otp.strip()
        if not code:
            log("ERROR", "OTP is required for uninstall.")
            return False
        resp = api_call(server_url, "POST", "/verify-uninstall", {
            "device_id": device_id, "otp": code, "hostname": get_hostname(),
        })
        if not resp or resp.get("status") != "ok":
            detail = resp.get("detail") if resp else "No response from server"
            log("ERROR", f"Uninstall blocked: invalid or expired OTP. {detail}")
            return False
    else:
        # GUI OTP prompt via tkinter
        import tkinter as tk
        import tkinter.messagebox as msgbox
        from pathlib import Path
        try:
            from PIL import Image, ImageTk  # type: ignore
        except ImportError:
            Image = None  # type: ignore
            ImageTk = None  # type: ignore

        root = tk.Tk()
        root.withdraw()

        try:
            if Image:
                base_dir = Path(getattr(__import__('sys'), "_MEIPASS", Path(__file__).parent))
                icon_path = base_dir / "assets" / "sentraguard_tray.png"
                if icon_path.exists():
                    _img = Image.open(icon_path).convert("RGBA").resize((48, 48))
                    tk_icon = ImageTk.PhotoImage(_img)
                    root.iconphoto(True, tk_icon)
                    root._sg_icon = tk_icon  # type: ignore[attr-defined]
        except Exception:
            pass

        custom_result: list = []

        def on_ok(event=None):
            val = entry.get().strip()
            if not val:
                return
            dlg.config(cursor="wait")
            ok_btn.config(state="disabled")
            dlg.update()
            r = api_call(server_url, "POST", "/verify-uninstall", {
                "device_id": device_id, "otp": val, "hostname": get_hostname(),
            })
            dlg.config(cursor="")
            ok_btn.config(state="normal")
            if not r or r.get("status") != "ok":
                detail = r.get("detail") if r else "Server unreachable or timeout"
                msgbox.showerror("Error", f"Invalid OTP: {detail}", parent=dlg)
                entry.delete(0, 'end')
                entry.focus()
            else:
                custom_result.append(val)
                dlg.destroy()

        def on_cancel():
            dlg.destroy()

        dlg = tk.Toplevel(root)
        dlg.title("Uninstall Authorization")
        dlg.configure(bg="#1A212D")
        dlg.attributes("-topmost", True)
        dlg.focus_force()
        w, h = 360, 180
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"{w}x{h}+{int((sw-w)/2)}+{int((sh-h)/2)}")
        dlg.resizable(False, False)
        try:
            dlg.iconphoto(False, root._sg_icon)  # type: ignore[attr-defined]
        except Exception:
            pass

        tk.Label(dlg, text="🛡️ Uninstall Authorization", bg="#1A212D", fg="#FF4444",
                 font=("Segoe UI", 12, "bold")).pack(pady=(16, 12))
        tk.Label(dlg, text="Enter uninstall OTP from admin portal:", bg="#1A212D", fg="#E4E6EB",
                 font=("Segoe UI", 10)).pack(pady=(0, 6))

        entry = tk.Entry(dlg, bg="#2A313C", fg="#FFFFFF", font=("Segoe UI", 11),
                         insertbackground="white", justify="center", bd=1, relief="solid")
        entry.pack(fill="x", padx=40, pady=4)
        entry.focus()
        entry.bind("<Return>", on_ok)

        btn_frame = tk.Frame(dlg, bg="#1A212D")
        btn_frame.pack(side="bottom", fill="x", pady=16)
        ok_btn = tk.Button(btn_frame, text="OK", width=12, bg="#007ACC", fg="white",
                           activebackground="#005A9E", activeforeground="white",
                           bd=0, font=("Segoe UI", 10, "bold"), command=on_ok)
        ok_btn.pack(side="right", padx=(0, 40))
        tk.Button(btn_frame, text="Cancel", width=12, bg="#2A313C", fg="#E4E6EB",
                  activebackground="#3A414C", activeforeground="white",
                  bd=0, font=("Segoe UI", 10), command=on_cancel).pack(side="right", padx=10)

        dlg.transient(root)
        dlg.grab_set()
        root.wait_window(dlg)
        code = custom_result[0] if custom_result else None

    if not code:
        log("ERROR", "OTP is required for uninstall.")
        return False

    if verify_only:
        log("INFO", "OTP validated successfully. (verify_only=True)")
        return True

    log("INFO", "OTP validated. Stopping service and removing files…")
    stop_service(service_name)

    try:
        safe_root = str(install_root).lower()
        if "youragent" in safe_root or "sentraguard" in safe_root.lower():
            if not powershell_available():
                # Pure-Python fallback cleanup
                for proc_name in ["agent.exe", "agent", "nssm.exe", "nssm"]:
                    try:
                        subprocess.run(["taskkill", "/F", "/IM", proc_name],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=CREATE_NO_WINDOW | CREATE_DEFAULT_ERROR_MODE)
                    except Exception:
                        pass
                time.sleep(3)
                for cmd in [["sc", "stop", service_name], ["sc", "delete", service_name]]:
                    try:
                        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=CREATE_NO_WINDOW | CREATE_DEFAULT_ERROR_MODE)
                        time.sleep(2)
                    except Exception:
                        pass
                for _ in range(5):
                    try:
                        if install_root.exists():
                            shutil.rmtree(install_root, ignore_errors=True)
                        if not install_root.exists():
                            break
                    except Exception as e:
                        log("WARN", f"Failed to remove install dir: {e}")
                    time.sleep(3)
                try:
                    import winreg  # type: ignore
                    for hive, path in [
                        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\YourAgent"),
                        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\YourAgent"),
                    ]:
                        try:
                            winreg.DeleteKey(winreg.ConnectRegistry(None, hive), path)
                        except Exception:
                            pass
                    try:
                        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                                             0, winreg.KEY_ALL_ACCESS)
                        winreg.DeleteValue(key, "YourAgentTray")
                        key.Close()
                    except Exception:
                        pass
                except Exception as e:
                    log("WARN", f"Registry cleanup fallback failed: {e}")
            else:
                ps_script = f"""
$ErrorActionPreference = 'SilentlyContinue'
Stop-Service -Name "{service_name}" -Force
sc.exe stop "{service_name}"; Start-Sleep -Seconds 2; sc.exe delete "{service_name}"
@("agent", "nssm", "winpty-agent") | ForEach-Object {{ Get-Process -Name $_ -ErrorAction SilentlyContinue | Stop-Process -Force }}
Start-Sleep -Seconds 3
for ($i=0; $i -lt 5; $i++) {{
    if (Test-Path "{install_root}") {{
        Remove-Item "{install_root}" -Recurse -Force
        if (!(Test-Path "{install_root}")) {{ break }}
        Start-Sleep -Seconds 3
    }} else {{ break }}
}}
Remove-Item -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\YourAgent" -Recurse -Force
Remove-Item -Path "HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\YourAgent" -Recurse -Force
Remove-ItemProperty -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run" -Name "YourAgentTray" -ErrorAction SilentlyContinue
"""
                with tempfile.NamedTemporaryFile(suffix='.ps1', delete=False, mode='w', encoding='utf-8') as tf:
                    tf.write(ps_script)
                    ps_temp_path = tf.name
                log("INFO", f"Running uninstall cleanup script: {ps_temp_path}")
                try:
                    result = subprocess.run(
                        ['powershell', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', ps_temp_path],
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        creationflags=CREATE_NO_WINDOW | CREATE_DEFAULT_ERROR_MODE, timeout=60,
                    )
                    log("INFO", f"Uninstall script exited with code {result.returncode}")
                except subprocess.TimeoutExpired:
                    log("WARN", "Uninstall cleanup script timed out (60s)")
                except Exception as e:
                    log("WARN", f"Uninstall cleanup script error: {e}")
                finally:
                    try:
                        os.remove(ps_temp_path)
                    except Exception:
                        pass
        else:
            log("WARN", f"Install path '{install_root}' does not look safe to delete; skipped.")
    except Exception as e:
        log("WARN", f"Cleanup warning: {e}")

    log("INFO", "Agent uninstalled successfully.")
    return True
