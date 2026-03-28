[Setup]
AppName=SentraGuard Endpoint Agent
AppVersion=1.0.1
AppPublisher=SentraGuard (Utkarsh)
DefaultDirName={commonpf}\SentraGuard
DefaultGroupName=SentraGuard
OutputBaseFilename=SentraGuardSetup_New
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
Uninstallable=yes
AlwaysRestart=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
SetupIconFile=assets\sentraguard_tray.ico
OutputDir=Output_Safe

[Files]
Source: "dist_sg\agent\agent.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "nssm.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "assets\sentraguard_tray.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\sentraguard_tray.png"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "apply_latest.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "create_task_applylatest.cmd"; DestDir: "{app}"; Flags: ignoreversion
[Run]
; 0. Clean up any legacy YourAgent service/startup entry (ignore failures)
Filename: "cmd.exe"; Parameters: "/c ""{app}\nssm.exe"" stop YourAgent 2>nul || exit /b 0"; Flags: runhidden
Filename: "cmd.exe"; Parameters: "/c ""{app}\nssm.exe"" remove YourAgent confirm 2>nul || exit /b 0"; Flags: runhidden
Filename: "cmd.exe"; Parameters: "/c reg delete HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run /v YourAgentTray /f 2>nul || exit /b 0"; Flags: runhidden
; 1. Install Windows Service using NSSM
Filename: "{app}\nssm.exe"; Parameters: "install SentraGuard ""{app}\agent.exe"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard AppParameters ""--server={code:GetServerURL} --no-verify-ssl"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set SentraGuard Start SERVICE_AUTO_START"; Flags: runhidden
; 2. Start the Service
Filename: "{app}\nssm.exe"; Parameters: "start SentraGuard"; Flags: runhidden
; 3. Run the tray icon immediately for the current user (won't block setup) - hidden to avoid console flash
Filename: "{app}\agent.exe"; Parameters: "--tray --server={code:GetServerURL} --no-verify-ssl"; Flags: runascurrentuser nowait runhidden
; 4. Register the hourly scheduled task that applies staged agent updates
Filename: "{app}\create_task_applylatest.cmd"; Flags: runhidden

[Registry]
; Add tray app to Startup for ALL users
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "SentraGuardTray"; ValueData: """{app}\agent.exe"" --tray --server={code:GetServerURL} --no-verify-ssl"; Flags: uninsdeletevalue

[UninstallRun]
; 1. Stop and remove both current and legacy services gracefully
Filename: "cmd.exe"; Parameters: "/c ""{app}\nssm.exe"" stop YourAgent 2>nul || exit /b 0"; Flags: runhidden; RunOnceId: "LegacyStopYourAgent"
Filename: "cmd.exe"; Parameters: "/c ""{app}\nssm.exe"" remove YourAgent confirm 2>nul || exit /b 0"; Flags: runhidden; RunOnceId: "LegacyRemoveYourAgent"
Filename: "{app}\nssm.exe"; Parameters: "stop SentraGuard"; Flags: runhidden; RunOnceId: "StopSentraGuard"
Filename: "taskkill"; Parameters: "/F /IM agent.exe"; Flags: runhidden; RunOnceId: "KillAgentProcess"
Filename: "{app}\nssm.exe"; Parameters: "remove SentraGuard confirm"; Flags: runhidden; RunOnceId: "RemoveSentraGuard"
Filename: "cmd.exe"; Parameters: "/c reg delete HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run /v YourAgentTray /f 2>nul || exit /b 0"; Flags: runhidden; RunOnceId: "CleanupLegacyTrayKey"

[UninstallRun]
; 1. Stop and remove the Windows Service gracefully
Filename: "{app}\nssm.exe"; Parameters: "stop YourAgent"; Flags: runhidden
Filename: "taskkill"; Parameters: "/F /IM agent.exe"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "remove YourAgent confirm"; Flags: runhidden

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

  // Trigger the standalone OTP validation using agent.exe and pass OTP via args
  if Exec(ExpandConstant('{app}\agent.exe'), '--verify-otp --otp "' + OTPInput + '" --no-verify-ssl', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
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
  Result := True; // InitializeUninstall is now just a check, prompt happens at Progress form stage
end;
