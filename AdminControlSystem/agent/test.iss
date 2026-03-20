[Setup]
AppName=Test
AppVersion=1
DefaultDirName={pf}\Test

[Code]
function InitializeUninstall(): Boolean;
var
  Code: String;
begin
  Code := InputBox('Auth', 'Code:', '');
  if Length(Code) > 0 then
    Result := True
  else
    Result := False;
end;
