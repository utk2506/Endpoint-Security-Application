"""
commands.py — All execute_* command handlers dispatched from the main polling loop.
"""

import ctypes
import json
import os
import subprocess
import tempfile
import threading
from typing import List

from config import CREATE_NO_WINDOW, CREATE_DEFAULT_ERROR_MODE, WINDLL
from logger import log
from network import api_call, powershell_available
from state import enqueue_notification


# ── Generic command runner ────────────────────────────────────────────────────

def _run_cmd(cmd: list, display_cmd: str = None):
    """Run a system command and return (success, output)."""
    show = display_cmd or ' '.join(cmd)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
            stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
        )
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0
        log('INFO' if success else 'WARN', f"{'✓' if success else '✗'} {show} → {output}")
        return success, output
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


# ── User management ───────────────────────────────────────────────────────────

def execute_create_user(username: str, password: str, dry_run: bool = False):
    ps_cmd = f'$Password = ConvertTo-SecureString "{password}" -AsPlainText -Force; New-LocalUser -Name "{username}" -Password $Password -Description "Created via Admin Control System"'
    cmd = ['powershell', '-NoProfile', '-Command', ps_cmd]
    if dry_run:
        log('DRY-RUN', f'Would run: $Password = ConvertTo-SecureString "***" -AsPlainText -Force; New-LocalUser -Name "{username}" ...')
        return True, "Dry-run mode (command not executed)"
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0
        log('INFO' if success else 'WARN', f"{'✓' if success else '✗'} Create user {username} → {output}")
        return success, output
    except Exception as e:
        return False, str(e)


def execute_grant(username: str, dry_run: bool = False):
    ps_cmd = f'Add-LocalGroupMember -Group "Administrators" -Member "{username}"'
    cmd = ['powershell', '-NoProfile', '-Command', ps_cmd]
    if dry_run:
        log('DRY-RUN', f"Would run: {ps_cmd}")
        return True, "Dry-run mode (command not executed)"
    return _run_cmd(cmd, ps_cmd)


def execute_revoke(username: str, dry_run: bool = False):
    ps_cmd = f'Remove-LocalGroupMember -Group "Administrators" -Member "{username}" -Confirm:$false'
    cmd = ['powershell', '-NoProfile', '-Command', ps_cmd]
    if dry_run:
        log('DRY-RUN', f"Would run: {ps_cmd}")
        return True, "Dry-run mode (command not executed)"
    return _run_cmd(cmd, ps_cmd)


def execute_check(dry_run: bool = False):
    cmd = ['net', 'localgroup', 'Administrators']
    if dry_run:
        log('DRY-RUN', f"Would run: {' '.join(cmd)}")
        return True, "Dry-run mode", ['Administrator', 'DryRunUser']
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0
        members: List[str] = []
        if success:
            in_members = False
            for line in result.stdout.strip().splitlines():
                if line.startswith('---'):
                    in_members = True
                    continue
                if in_members:
                    if not line or line.startswith('The command completed'):
                        break
                    members.append(line)
        log('INFO', f"Admin members: {members}")
        return success, output, members
    except subprocess.TimeoutExpired:
        return False, "Command timed out", []
    except Exception as e:
        return False, str(e), []


# ── Shell execution ───────────────────────────────────────────────────────────

def execute_shell(payload: str, dry_run: bool = False):
    if dry_run:
        log('DRY-RUN', f"Would run shell payload:\n{payload}")
        return True, f"Dry-run mode. Payload length: {len(payload)}"
    cmd_list: List[str] = ['powershell', '-NoProfile', '-NonInteractive', '-Command', payload]
    try:
        result = subprocess.run(cmd_list, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0
        log('INFO' if success else 'WARN', f"Shell exec -> returncode {result.returncode}")
        return success, output
    except subprocess.TimeoutExpired:
        return False, "Shell command timed out (max 60s)"
    except Exception as e:
        return False, str(e)


# ── Software uninstall ────────────────────────────────────────────────────────

def execute_uninstall(payload: str, dry_run: bool = False):
    try:
        data = json.loads(payload) if payload else {}
    except Exception:
        data = {"uninstall_string": payload}

    uninstall_cmd = data.get('uninstall_string') or data.get('command')
    name = data.get('name') or 'target software'

    if not uninstall_cmd:
        return False, "No uninstall command provided by portal/agent"

    cmd_to_run = uninstall_cmd.strip()

    def has_silent_flag(cmd: str) -> bool:
        return any(f in cmd.lower() for f in ['/qn', '/quiet', '/q', '/s', '/silent', '/verysilent', '/passive'])

    def split_path_args(cmd: str):
        cmd = cmd.strip()
        if cmd.startswith('"'):
            end = cmd.find('"', 1)
            exe = cmd[1:end] if end != -1 else cmd.strip('"')
            rest = cmd[end + 1:].strip() if end != -1 else ''
        else:
            parts = cmd.split(' ', 1)
            exe = parts[0]
            rest = parts[1] if len(parts) > 1 else ''
        return exe, rest

    exe, args = split_path_args(cmd_to_run)
    if 'msiexec' in exe.lower():
        if (' /i' in args.lower()) and (' /x' not in args.lower()):
            args = args.replace('/I', '/X').replace('/i', '/x')
        if not has_silent_flag(args):
            args += ' /qn /norestart'
        exe = 'msiexec.exe'
    else:
        if not has_silent_flag(args):
            args += ' /S /VERYSILENT /silent /quiet /norestart'
        if '/s' not in args.lower():
            args += ' /S'

    def ps_quote(s: str) -> str:
        return "'" + s.replace("'", "''") + "'"

    ps_cmd = (
        f"Start-Process -FilePath {ps_quote(exe)} "
        f"-ArgumentList {ps_quote(args.strip())} "
        f"-WindowStyle Hidden -Wait; exit $LASTEXITCODE"
    )

    if dry_run:
        log('DRY-RUN', f"Would uninstall {name} using: {exe} {args}")
        return True, f"Dry-run: would uninstall {name} via '{exe} {args}'"

    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_cmd],
            capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
        )
        output = (result.stdout + result.stderr).strip() or "Completed with no output."
        success = result.returncode == 0
        log('INFO' if success else 'WARN', f"Uninstall {name} → rc={result.returncode}")
        return success, output
    except subprocess.TimeoutExpired:
        return False, f"Uninstall timed out for {name}"
    except Exception as e:
        return False, f"Uninstall failed: {e}"


# ── Notifications ─────────────────────────────────────────────────────────────

def execute_notify(payload: str, dry_run: bool = False):
    try:
        data = json.loads(payload)
        msg_text = data.get('message', 'Notification from IT')
    except Exception as e:
        return False, f"Failed to parse notification payload: {e}"
    if dry_run:
        log('DRY-RUN', f"Would send modern notification: '{msg_text}'")
        return True, f"Dry-run mode. Message: {msg_text}"
    return execute_modern_notify(msg_text)


def execute_modern_notify(message: str):
    """Launch a styled WPF notification window via PowerShell, with session handling."""
    if not powershell_available():
        log('WARN', "PowerShell unavailable; falling back to msg.exe notification.")
        try:
            subprocess.run(['msg', '*', message], capture_output=True, stdin=subprocess.DEVNULL,
                           creationflags=CREATE_NO_WINDOW | CREATE_DEFAULT_ERROR_MODE)
            return True, "PowerShell unavailable; used msg.exe fallback."
        except Exception as e:
            return False, f"Notification failed (no PowerShell): {e}"

    session_id = 0
    try:
        current_session = ctypes.c_uint32()
        if WINDLL and WINDLL.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(current_session)):
            session_id = current_session.value
    except Exception:
        pass

    if session_id == 0:
        enqueue_notification(message)
        return True, "Agent is running as a service; notification queued for user session."

    safe_msg = message.replace('\\', '\\\\').replace('"', '\\"')
    ps_content = f"""
$pfw = ([Reflection.Assembly]::LoadWithPartialName('PresentationFramework')).Location
$pfc = ([Reflection.Assembly]::LoadWithPartialName('PresentationCore')).Location
$wb  = ([Reflection.Assembly]::LoadWithPartialName('WindowsBase')).Location
$sx  = ([Reflection.Assembly]::LoadWithPartialName('System.Xaml')).Location

Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase

Add-Type -ReferencedAssemblies $pfw, $pfc, $wb, $sx, "System.Core", "mscorlib" @"
using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Effects;

public class ChimeraNotifyWin {{
    public static void Show(string msg) {{
        var win = new Window {{
            Title = "Chimera Control Message",
            Width = 460, Height = 260,
            WindowStyle = WindowStyle.None,
            AllowsTransparency = true,
            Background = Brushes.Transparent,
            WindowStartupLocation = WindowStartupLocation.CenterScreen,
            Topmost = true, ShowInTaskbar = true, ResizeMode = ResizeMode.NoResize
        }};
        var outerBorder = new Border {{
            Background = Brushes.White,
            BorderBrush = new SolidColorBrush(Color.FromRgb(0x1a, 0x25, 0x35)),
            BorderThickness = new Thickness(1.5),
            CornerRadius = new CornerRadius(12),
            Effect = new DropShadowEffect {{ BlurRadius = 15, Direction = 270, Opacity = 0.3, ShadowDepth = 3 }}
        }};
        var grid = new Grid();
        grid.RowDefinitions.Add(new RowDefinition {{ Height = new GridLength(50) }});
        grid.RowDefinitions.Add(new RowDefinition {{ Height = new GridLength(1, GridUnitType.Star) }});
        grid.RowDefinitions.Add(new RowDefinition {{ Height = new GridLength(70) }});
        var headerBg = new Border {{
            Background = new SolidColorBrush(Color.FromRgb(0x1a, 0x25, 0x35)),
            CornerRadius = new CornerRadius(10, 10, 0, 0)
        }};
        var headerText = new TextBlock {{
            Text = "CHIMERA SECURITY NOTIFICATION",
            Foreground = new SolidColorBrush(Color.FromRgb(0xE0, 0xE0, 0xE0)),
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            FontWeight = FontWeights.SemiBold, FontSize = 13
        }};
        headerBg.Child = headerText;
        Grid.SetRow(headerBg, 0); grid.Children.Add(headerBg);
        var msgBlock = new TextBlock {{
            Text = msg, TextWrapping = TextWrapping.Wrap, FontSize = 16,
            Foreground = new SolidColorBrush(Color.FromRgb(0x2D, 0x37, 0x48)),
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            TextAlignment = TextAlignment.Center,
            Margin = new Thickness(30, 25, 30, 10)
        }};
        Grid.SetRow(msgBlock, 1); grid.Children.Add(msgBlock);
        var btn = new Button {{
            Content = "Dismiss", Width = 120, Height = 36,
            Background = new SolidColorBrush(Color.FromRgb(0x3b, 0x82, 0xf6)),
            Foreground = Brushes.White, FontWeight = FontWeights.Bold, FontSize = 13,
            BorderThickness = new Thickness(0),
            Cursor = System.Windows.Input.Cursors.Hand,
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center
        }};
        btn.Click += (s, e) => win.Close();
        Grid.SetRow(btn, 2); grid.Children.Add(btn);
        outerBorder.Child = grid; win.Content = outerBorder; win.ShowDialog();
    }}
}}
"@ -ErrorAction Stop

[ChimeraNotifyWin]::Show("{safe_msg}")
"""
    with tempfile.NamedTemporaryFile(suffix='.ps1', delete=False, mode='w', encoding='utf-8') as tf:
        tf.write(ps_content)
        temp_path = tf.name

    try:
        cmd = ['powershell', '-Sta', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', temp_path]

        def _run():
            res = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
            if res.returncode != 0:
                log('ERROR', f"Notification PowerShell failed (code {res.returncode})")
                log('DEBUG', f"PS Error: {res.stderr[:500]}")
            try:
                os.remove(temp_path)
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True).start()
        log('INFO', f"✓ Modern notification launched (Session {session_id}): {message[:50]}...")
        return True, f"Modern notification window launched in Session {session_id}."
    except Exception as e:
        log('WARN', f"Failed to launch modern notification: {e}")
        return False, str(e)
