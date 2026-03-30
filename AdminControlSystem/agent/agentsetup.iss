[Setup]
AppName=SentraGuard Endpoint Agent
AppVersion=1.1.0
AppPublisher=SentraGuard (Utkarsh)
DefaultDirName={commonpf}\SentraGuard
DefaultGroupName=SentraGuard
OutputBaseFilename=SentraGuardSetup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
Uninstallable=yes
AlwaysRestart=no
DisableDirPage=yes
DisableProgramGroupPage=yes
SetupIconFile=assets\sentraguard_tray.ico
OutputDir=Output_Safe

; ── Directories ─────────────────────────────────────────────────────────────
[Dirs]
Name: "{commonappdata}\SentraGuard";                         Permissions: everyone-full
Name: "{commonappdata}\SentraGuard\logs";                    Permissions: everyone-full
Name: "{commonappdata}\SentraGuard\logs\archive";            Permissions: everyone-full

; ── Files ────────────────────────────────────────────────────────────────────
[Files]
; ─── Agent binaries ──────────────────────────────────────────────────────────
; Core control agent
Source: "dist_sg\agent\agent.exe";            DestDir: "{app}"; Flags: ignoreversion
; Activity collection service (SentraGuardActivitySvc)
Source: "dist_sg\activityservice\activityservice.exe"; DestDir: "{app}"; Flags: ignoreversion
; Sync service (SentraGuardSyncSvc)
Source: "dist_sg\syncservice\syncservice.exe"; DestDir: "{app}"; Flags: ignoreversion

; ─── NSSM service manager ────────────────────────────────────────────────────
Source: "nssm.exe"; DestDir: "{app}"; Flags: ignoreversion

; ─── Assets ──────────────────────────────────────────────────────────────────
Source: "assets\sentraguard_tray.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\sentraguard_tray.png"; DestDir: "{app}\assets"; Flags: ignoreversion

; ─── Update helpers ──────────────────────────────────────────────────────────
Source: "apply_latest.ps1";          DestDir: "{app}"; Flags: ignoreversion
Source: "create_task_applylatest.cmd"; DestDir: "{app}"; Flags: ignoreversion

; ── Install steps (Run) ──────────────────────────────────────────────────────
[Run]
; ── 0. Remove any legacy / previous-version service entries ──────────────────
Filename: "cmd.exe"; Parameters: "/c ""{app}\nssm.exe"" stop YourAgent 2>nul || exit /b 0"; Flags: runhidden
Filename: "cmd.exe"; Parameters: "/c ""{app}\nssm.exe"" remove YourAgent confirm 2>nul || exit /b 0"; Flags: runhidden
Filename: "cmd.exe"; Parameters: "/c reg delete HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run /v YourAgentTray /f 2>nul || exit /b 0"; Flags: runhidden

; Stop previous instances (safe — ignore errors if not installed)
Filename: "cmd.exe"; Parameters: "/c ""{app}\nssm.exe"" stop SentraGuard 2>nul || exit /b 0"; Flags: runhidden
Filename: "cmd.exe"; Parameters: "/c ""{app}\nssm.exe"" remove SentraGuard confirm 2>nul || exit /b 0"; Flags: runhidden
Filename: "cmd.exe"; Parameters: "/c ""{app}\nssm.exe"" stop SentraGuardActivitySvc 2>nul || exit /b 0"; Flags: runhidden
Filename: "cmd.exe"; Parameters: "/c ""{app}\nssm.exe"" remove SentraGuardActivitySvc confirm 2>nul || exit /b 0"; Flags: runhidden
Filename: "cmd.exe"; Parameters: "/c ""{app}\nssm.exe"" stop SentraGuardSyncSvc 2>nul || exit /b 0"; Flags: runhidden
Filename: "cmd.exe"; Parameters: "/c ""{app}\nssm.exe"" remove SentraGuardSyncSvc confirm 2>nul || exit /b 0"; Flags: runhidden

; ── 1. Create ProgramData directories ────────────────────────────────────────
Filename: "cmd.exe"; Parameters: "/c mkdir ""{commonappdata}\SentraGuard\logs\archive"" 2>nul || exit /b 0"; Flags: runhidden

; ── 2. Install SentraGuard (main control agent) via NSSM ─────────────────────
Filename: "{app}\nssm.exe"; Parameters: "install SentraGuard ""{app}\agent.exe"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard AppParameters ""--server={code:GetServerURL} --no-verify-ssl"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard Start SERVICE_AUTO_START"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard DisplayName ""SentraGuard Endpoint Agent"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard Description ""SentraGuard endpoint protection: device management, command execution, BitLocker, remote terminal and tamper protection."""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard AppRestartDelay 5000"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard AppExit Default Restart"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard AppStdout ""{commonappdata}\SentraGuard\logs\agent.log"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard AppStderr ""{commonappdata}\SentraGuard\logs\agent.log"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard AppRotateFiles 1"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard AppRotateBytes 10485760"; Flags: runhidden

; ── 3. Install SentraGuardActivitySvc (Activity Collection) via NSSM ─────────
Filename: "{app}\nssm.exe"; Parameters: "install SentraGuardActivitySvc ""{app}\activityservice.exe"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivitySvc Start SERVICE_AUTO_START"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivitySvc DisplayName ""SentraGuard Activity Collection"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivitySvc Description ""Captures user login, logout, idle, lock, screen and startup/shutdown events for the SentraGuard portal dashboard."""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivitySvc AppRestartDelay 5000"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivitySvc AppExit Default Restart"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivitySvc AppStdout ""{commonappdata}\SentraGuard\logs\activityservice.log"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivitySvc AppStderr ""{commonappdata}\SentraGuard\logs\activityservice.log"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivitySvc AppRotateFiles 1"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivitySvc AppRotateBytes 10485760"; Flags: runhidden

; ── 4. Install SentraGuardSyncSvc (Activity Sync) via NSSM ──────────────────
Filename: "{app}\nssm.exe"; Parameters: "install SentraGuardSyncSvc ""{app}\syncservice.exe"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardSyncSvc AppParameters ""--server={code:GetServerURL} --no-verify-ssl"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardSyncSvc Start SERVICE_AUTO_START"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardSyncSvc DisplayName ""SentraGuard Activity Sync"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardSyncSvc Description ""Uploads locally cached user activity events to the SentraGuard central portal. Retries automatically when offline."""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardSyncSvc AppRestartDelay 10000"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardSyncSvc AppExit Default Restart"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardSyncSvc AppStdout ""{commonappdata}\SentraGuard\logs\syncservice.log"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardSyncSvc AppStderr ""{commonappdata}\SentraGuard\logs\syncservice.log"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardSyncSvc AppRotateFiles 1"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardSyncSvc AppRotateBytes 10485760"; Flags: runhidden

; ── 5. Start all three services ───────────────────────────────────────────────
Filename: "{app}\nssm.exe"; Parameters: "start SentraGuardActivitySvc"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "start SentraGuardSyncSvc"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "start SentraGuard"; Flags: runhidden

; ── 6. Launch tray icon for current interactive user ─────────────────────────
Filename: "{app}\agent.exe"; Parameters: "--tray --server={code:GetServerURL} --no-verify-ssl"; Flags: runascurrentuser nowait runhidden

; ── 7. Register hourly update task ───────────────────────────────────────────
Filename: "{app}\create_task_applylatest.cmd"; Flags: runhidden

; ── Registry ─────────────────────────────────────────────────────────────────
[Registry]
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "SentraGuardTray"; ValueData: """{app}\agent.exe"" --tray --server={code:GetServerURL} --no-verify-ssl"; Flags: uninsdeletevalue

; ── Uninstall: stop and remove ALL three services ────────────────────────────
[UninstallRun]
; Kill tray process
Filename: "taskkill"; Parameters: "/F /IM agent.exe /T"; Flags: runhidden; RunOnceId: "KillTray"

; Stop + remove SentraGuardSyncSvc
Filename: "{app}\nssm.exe"; Parameters: "stop SentraGuardSyncSvc"; Flags: runhidden; RunOnceId: "StopSyncSvc"
Filename: "{app}\nssm.exe"; Parameters: "remove SentraGuardSyncSvc confirm"; Flags: runhidden; RunOnceId: "RemoveSyncSvc"

; Stop + remove SentraGuardActivitySvc
Filename: "{app}\nssm.exe"; Parameters: "stop SentraGuardActivitySvc"; Flags: runhidden; RunOnceId: "StopActivitySvc"
Filename: "{app}\nssm.exe"; Parameters: "remove SentraGuardActivitySvc confirm"; Flags: runhidden; RunOnceId: "RemoveActivitySvc"

; Stop + remove SentraGuard (main agent)
Filename: "{app}\nssm.exe"; Parameters: "stop SentraGuard"; Flags: runhidden; RunOnceId: "StopMainSvc"
Filename: "{app}\nssm.exe"; Parameters: "remove SentraGuard confirm"; Flags: runhidden; RunOnceId: "RemoveMainSvc"

; Remove scheduled tasks
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Unregister-ScheduledTask -TaskName 'SentraGuardTray' -Confirm:$false 2>$null"""; Flags: runhidden; RunOnceId: "RemoveTrayTask"
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Unregister-ScheduledTask -TaskName 'SentraGuardApplyLatest' -Confirm:$false 2>$null"""; Flags: runhidden; RunOnceId: "RemoveUpdateTask"

; Remove legacy YourAgent entries
Filename: "cmd.exe"; Parameters: "/c ""{app}\nssm.exe"" stop YourAgent 2>nul || exit /b 0"; Flags: runhidden; RunOnceId: "LegacyStop"
Filename: "cmd.exe"; Parameters: "/c ""{app}\nssm.exe"" remove YourAgent confirm 2>nul || exit /b 0"; Flags: runhidden; RunOnceId: "LegacyRemove"
Filename: "cmd.exe"; Parameters: "/c reg delete HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run /v YourAgentTray /f 2>nul || exit /b 0"; Flags: runhidden; RunOnceId: "LegacyReg"

; ── Inno Setup wizard code ────────────────────────────────────────────────────
[Code]
var
  ServerPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  ServerPage := CreateInputQueryPage(wpWelcome,
    'Server Configuration', 'Where should the agent report to?',
    'Enter the SentraGuard portal server URL. All three services will use this address.');
  ServerPage.Add('Server URL:', False);
  ServerPage.Values[0] := 'https://localhost:8000';
end;

function GetServerURL(Param: String): String;
begin
  Result := ServerPage.Values[0];
end;

function PromptForOTP(var OTP: String): Boolean;
var
  Form: TSetupForm;
  PromptLabel: TLabel;
  OTPEdit: TEdit;
  OKButton, CancelButton: TNewButton;
begin
  Result := False;
  Form := CreateCustomForm(320, 140, False, False);
  try
    Form.Caption := 'Uninstall Authorization';
    Form.Position := poScreenCenter;

    PromptLabel := TLabel.Create(Form);
    PromptLabel.Parent := Form;
    PromptLabel.Caption := 'Enter uninstall OTP from admin portal:';
    PromptLabel.Left := 16;
    PromptLabel.Top := 16;
    PromptLabel.Width := 280;

    OTPEdit := TEdit.Create(Form);
    OTPEdit.Parent := Form;
    OTPEdit.Left := 16;
    OTPEdit.Top := 40;
    OTPEdit.Width := 288;

    OKButton := TNewButton.Create(Form);
    OKButton.Parent := Form;
    OKButton.Caption := 'OK';
    OKButton.Default := True;
    OKButton.ModalResult := mrOk;
    OKButton.Left := 140;
    OKButton.Top := 85;
    OKButton.Width := 75;

    CancelButton := TNewButton.Create(Form);
    CancelButton.Parent := Form;
    CancelButton.Caption := 'Cancel';
    CancelButton.Cancel := True;
    CancelButton.ModalResult := mrCancel;
    CancelButton.Left := 225;
    CancelButton.Top := 85;
    CancelButton.Width := 75;

    if Form.ShowModal() = mrOk then
    begin
      OTP := OTPEdit.Text;
      Result := True;
    end;
  finally
    Form.Free;
  end;
end;

procedure InitializeUninstallProgressForm();
var
  ResultCode: Integer;
  OTPInput: String;
begin
  if not PromptForOTP(OTPInput) then
  begin
    MsgBox('Uninstall cancelled.', mbInformation, MB_OK);
    Abort();
  end;

  if Trim(OTPInput) = '' then
  begin
    MsgBox('OTP is required for uninstall.', mbError, MB_OK);
    Abort();
  end;

  if Exec(ExpandConstant('{app}\agent.exe'),
          '--verify-otp --otp "' + OTPInput + '" --no-verify-ssl',
          '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if ResultCode <> 0 then
    begin
      MsgBox('Invalid or expired OTP. Uninstall aborted.', mbError, MB_OK);
      Abort();
    end;
  end
  else
  begin
    MsgBox('Could not verify OTP. Agent executable is missing or corrupted.', mbError, MB_OK);
    Abort();
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
end;
