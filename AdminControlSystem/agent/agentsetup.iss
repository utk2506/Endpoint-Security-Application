[Setup]
AppName=YourAgent Endpoint
AppVersion=1.1.8
AppPublisher=Chimera IT
DefaultDirName={pf}\YourAgent
DefaultGroupName=YourAgent
OutputBaseFilename=agentsetup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
; Enable native uninstaller
Uninstallable=yes
DisableDirPage=yes
DisableProgramGroupPage=yes

[Files]
Source: "dist\agent.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "nssm.exe"; DestDir: "{app}"; Flags: ignoreversion

[Run]
; 1. Install Windows Service using NSSM
Filename: "{app}\nssm.exe"; Parameters: "install YourAgent ""{app}\agent.exe"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set YourAgent AppParameters ""--server={code:GetServerURL} --no-verify-ssl"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set YourAgent Start SERVICE_AUTO_START"; Flags: runhidden
; 2. Start the Service
Filename: "{app}\nssm.exe"; Parameters: "start YourAgent"; Flags: runhidden
; 3. Run the tray icon immediately for the current user (won't block setup)
Filename: "{app}\agent.exe"; Parameters: "--tray --server={code:GetServerURL} --no-verify-ssl"; Flags: runascurrentuser nowait

[Registry]
; Add tray app to Startup for ALL users
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "YourAgentTray"; ValueData: """{app}\agent.exe"" --tray --server={code:GetServerURL} --no-verify-ssl"; Flags: uninsdeletevalue

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

function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
begin
  // Trigger the standalone OTP validation via Python Tkinter
  if Exec(ExpandConstant('{app}\agent.exe'), '--verify-otp --no-verify-ssl', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if ResultCode = 0 then
    begin
      Result := True;
      Exit;
    end
    else
    begin
      MsgBox('Invalid or expired OTP. Uninstall aborted.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end
  else
  begin
    MsgBox('Could not verify OTP. Agent executable is missing or corrupted.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
end;
