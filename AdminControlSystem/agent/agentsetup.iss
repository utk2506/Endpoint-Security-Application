[Setup]
AppName=SentraGuard Endpoint Agent
AppVersion=1.0.3
AppPublisher=SentraGuard (Utkarsh)
DefaultDirName={commonpf}\SentraGuard
DefaultGroupName=SentraGuard
OutputBaseFilename=SentraGuardSetup_New
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
Uninstallable=yes
AlwaysRestart=no
DisableDirPage=yes
DisableProgramGroupPage=yes
SetupIconFile=assets\sentraguard_tray.ico
OutputDir=Output_Safe

; ── Files ──────────────────────────────────────────────────────────────────────
[Files]
; Main agent executable
Source: "dist_sg\agent\agent.exe";             DestDir: "{app}"; Flags: ignoreversion
; Activity monitoring service executable
Source: "dist_sg\activity_service\activity_service.exe"; DestDir: "{app}"; Flags: ignoreversion
; NSSM service manager
Source: "nssm.exe";                            DestDir: "{app}"; Flags: ignoreversion
; Assets (tray icons)
Source: "assets\sentraguard_tray.ico";         DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\sentraguard_tray.png";         DestDir: "{app}\assets"; Flags: ignoreversion
; Update helpers
Source: "apply_latest.ps1";                    DestDir: "{app}"; Flags: ignoreversion
Source: "create_task_applylatest.cmd";         DestDir: "{app}"; Flags: ignoreversion

; ── Install steps (Run) ───────────────────────────────────────────────────────
[Run]
; ── 0. Remove any legacy YourAgent service/startup entries ────────────────────
Filename: "cmd.exe"; Parameters: "/c ""{app}\nssm.exe"" stop YourAgent 2>nul || exit /b 0"; Flags: runhidden
Filename: "cmd.exe"; Parameters: "/c ""{app}\nssm.exe"" remove YourAgent confirm 2>nul || exit /b 0"; Flags: runhidden
Filename: "cmd.exe"; Parameters: "/c reg delete HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run /v YourAgentTray /f 2>nul || exit /b 0"; Flags: runhidden

; ── 1. Install SentraGuard (main control agent) service via NSSM ──────────────
Filename: "{app}\nssm.exe"; Parameters: "install SentraGuard ""{app}\agent.exe"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard AppParameters ""--server={code:GetServerURL} --no-verify-ssl"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard Start SERVICE_AUTO_START"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard DisplayName ""SentraGuard Endpoint Agent"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard Description ""SentraGuard endpoint protection agent: device management, command execution, and tamper protection."""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard AppRestartDelay 5000"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard AppStopMethodSkip 0"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard AppExit Default Restart"; Flags: runhidden
; NSSM stdout/stderr log routing
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard AppStdout ""{commonappdata}\SentraGuard\logs\agent.log"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard AppStderr ""{commonappdata}\SentraGuard\logs\agent.log"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard AppRotateFiles 1"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard AppRotateBytes 5242880"; Flags: runhidden

; ── 2. Install SentraGuardActivityService (dedicated activity monitoring) ──────
Filename: "{app}\nssm.exe"; Parameters: "install SentraGuardActivityService ""{app}\activity_service.exe"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivityService AppParameters ""--server={code:GetServerURL} --no-verify-ssl"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivityService Start SERVICE_AUTO_START"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivityService DisplayName ""SentraGuard Activity Monitoring"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivityService Description ""SentraGuard Activity Monitoring: Tracks user application usage, idle time, and input activity for enterprise productivity analytics. Runs alongside the main SentraGuard agent service."""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivityService AppRestartDelay 10000"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivityService AppExit Default Restart"; Flags: runhidden
; Activity service stdout/stderr log routing
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivityService AppStdout ""{commonappdata}\SentraGuard\logs\activity_service.log"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivityService AppStderr ""{commonappdata}\SentraGuard\logs\activity_service.log"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivityService AppRotateFiles 1"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuardActivityService AppRotateBytes 5242880"; Flags: runhidden

; ── 3. Start both services ─────────────────────────────────────────────────────
Filename: "{app}\nssm.exe"; Parameters: "start SentraGuard"; Flags: runhidden
; Activity service waits 8s so main agent writes agent_state.json first
Filename: "cmd.exe"; Parameters: "/c timeout /t 8 /nobreak && ""{app}\nssm.exe"" start SentraGuardActivityService"; Flags: runhidden nowait

; ── 4. Launch tray icon for the current interactive user ──────────────────────
Filename: "{app}\agent.exe"; Parameters: "--tray --server={code:GetServerURL} --no-verify-ssl"; Flags: runascurrentuser nowait runhidden

; ── 5. Register hourly update task ────────────────────────────────────────────
Filename: "{app}\create_task_applylatest.cmd"; Flags: runhidden

; ── Registry ──────────────────────────────────────────────────────────────────
[Registry]
; Tray autostart for all users
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "SentraGuardTray"; ValueData: """{app}\agent.exe"" --tray --server={code:GetServerURL} --no-verify-ssl"; Flags: uninsdeletevalue

; ── Uninstall: stop and remove EVERYTHING ────────────────────────────────────
[UninstallRun]
; Kill the tray process first (user-session)
Filename: "taskkill"; Parameters: "/F /IM agent.exe /T"; Flags: runhidden; RunOnceId: "KillTray"

; Stop + remove SentraGuardActivityService
Filename: "{app}\nssm.exe"; Parameters: "stop SentraGuardActivityService"; Flags: runhidden; RunOnceId: "StopActivitySvc"
Filename: "{app}\nssm.exe"; Parameters: "remove SentraGuardActivityService confirm"; Flags: runhidden; RunOnceId: "RemoveActivitySvc"

; Stop + remove SentraGuard (main)
Filename: "{app}\nssm.exe"; Parameters: "stop SentraGuard"; Flags: runhidden; RunOnceId: "StopMainSvc"
Filename: "{app}\nssm.exe"; Parameters: "remove SentraGuard confirm"; Flags: runhidden; RunOnceId: "RemoveMainSvc"

; Remove tray scheduled task
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Unregister-ScheduledTask -TaskName 'SentraGuardTray' -Confirm:$false 2>$null"""; Flags: runhidden; RunOnceId: "RemoveTrayTask"
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Unregister-ScheduledTask -TaskName 'SentraGuardApplyLatest' -Confirm:$false 2>$null"""; Flags: runhidden; RunOnceId: "RemoveUpdateTask"

; Remove legacy YourAgent entries (safety net)
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
    'Please specify the master server URL. Devices will check in with this API address.');
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
