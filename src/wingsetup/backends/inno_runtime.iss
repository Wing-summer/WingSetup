; Copyright (c) 2026, wingsummer
; SPDX-License-Identifier: BSD-3-Clause
; See LICENSE in the project root for license information.

[Code]
const
  WingOwnerKey = @@OWNER@@;
var
  WingOwned: TStringList;

function WingRegGetValue(RootKey: Integer; SubKey, ValueName: String;
  Flags: Cardinal; var ValueType: Cardinal; Data: LongWord; var Size: Cardinal): Longint;
  external 'RegGetValueW@advapi32.dll stdcall';

function WingRoot: Integer;
begin
  if IsAdminInstallMode then Result := HKLM else Result := HKCU;
end;

function WingEnvironmentKey: String;
begin
  if IsAdminInstallMode then
    Result := 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
  else Result := 'Environment';
end;

procedure WingWrite(Key, Name, Value: String);
begin
  if not RegWriteStringValue(WingRoot, Key, Name, Value) then
    RaiseException('Cannot register installation value: ' + Key);
  WingOwned.Add(Key + #9 + Name);
end;

procedure WingPruneEmpty(Key: String);
var
  I: Integer;
begin
  while Length(Key) > Length('Software') do begin
    if not RegDeleteKeyIfEmpty(WingRoot, Key) then Exit;
    I := Length(Key);
    while (I > 0) and (Key[I] <> '\') do I := I - 1;
    if I = 0 then Exit;
    Key := Copy(Key, 1, I - 1);
  end;
end;

procedure WingClearOwned;
var
  Saved, Key, Name, RecordText: String;
  Entries: TStringList;
  I, P: Integer;
begin
  if not RegQueryStringValue(WingRoot, WingOwnerKey, 'Owned', Saved) then Exit;
  Entries := TStringList.Create;
  try
    Entries.Text := Saved;
    for I := Entries.Count - 1 downto 0 do begin
      RecordText := Entries[I];
      P := Pos(#9, RecordText);
      if P > 0 then begin
        Key := Copy(RecordText, 1, P - 1);
        Name := Copy(RecordText, P + 1, Length(RecordText));
        RegDeleteValue(WingRoot, Key, Name);
        WingPruneEmpty(Key);
      end;
    end;
  finally
    Entries.Free;
  end;
  RegDeleteValue(WingRoot, WingOwnerKey, 'Owned');
end;

function WingPathToken(Value: String): String;
begin
  Result := Trim(Value);
  if (Length(Result) >= 2) and (Result[1] = '"') and
     (Result[Length(Result)] = '"') then
    Result := Copy(Result, 2, Length(Result) - 2);
  Result := RemoveBackslashUnlessRoot(Result);
end;

function WingFilterPath(Value, Entry: String; Remove: Boolean; var Found: Boolean): String;
var
  Token: String;
  P: Integer;
  Match, First: Boolean;
begin
  Result := '';
  Found := False;
  First := True;
  repeat
    P := Pos(';', Value);
    if P = 0 then begin Token := Value; Value := ''; end
    else begin Token := Copy(Value, 1, P - 1); Delete(Value, 1, P); end;
    Match := CompareText(WingPathToken(Token), WingPathToken(Entry)) = 0;
    if Match then Found := True;
    if not (Remove and Match) then begin
      if not First then Result := Result + ';';
      Result := Result + Token;
      First := False;
    end;
  until P = 0;
end;

function WingAppendPath(Value, Entry: String): String;
begin
  // A trailing semicolon represents an existing empty token; preserve it.
  if Value = '' then Result := Entry
  else Result := Value + ';' + Entry;
end;

procedure WingModifyPath(Entry: String; Add: Boolean; var Owned: Boolean);
var
  Value, Filtered: String;
  Kind, Size: Cardinal;
  Found, Existed: Boolean;
begin
  Kind := 2;
  Size := 0;
  Existed := RegValueExists(WingRoot, WingEnvironmentKey, 'Path');
  if Existed then begin
    if WingRegGetValue(WingRoot, WingEnvironmentKey, 'Path', $10000006, Kind, 0, Size) <> 0 then
      RaiseException('Cannot inspect existing PATH registry type');
    if not RegQueryStringValue(WingRoot, WingEnvironmentKey, 'Path', Value) then
      RaiseException('Cannot read existing PATH');
  end else Value := '';
  Filtered := WingFilterPath(Value, Entry, not Add, Found);
  if Add then begin
    if Found then Exit;
    Filtered := WingAppendPath(Value, Entry);
    Owned := True;
    if not Existed then RegWriteStringValue(WingRoot, WingOwnerKey, 'PathCreated', '1');
  end else if not Found then Exit;
  if (not Add) and (Filtered = '') and RegValueExists(WingRoot, WingOwnerKey, 'PathCreated') then
    RegDeleteValue(WingRoot, WingEnvironmentKey, 'Path')
  else if Kind = 1 then begin
    if not RegWriteStringValue(WingRoot, WingEnvironmentKey, 'Path', Filtered) then RaiseException('Cannot write PATH');
  end else begin
    if not RegWriteExpandStringValue(WingRoot, WingEnvironmentKey, 'Path', Filtered) then RaiseException('Cannot write PATH');
  end;
end;

procedure WingSyncPath(Enable: Boolean);
var
  Previous, Desired: String;
  Owned, Unused: Boolean;
begin
  Desired := ExpandConstant('{app}');
  Owned := RegQueryStringValue(WingRoot, WingOwnerKey, 'PathEntry', Previous);
  if Owned and ((not Enable) or (CompareText(Previous, Desired) <> 0)) then begin
    Unused := False;
    WingModifyPath(Previous, False, Unused);
    RegDeleteValue(WingRoot, WingOwnerKey, 'PathEntry');
    RegDeleteValue(WingRoot, WingOwnerKey, 'PathCreated');
    Owned := False;
  end;
  if Enable then begin
    WingModifyPath(Desired, True, Owned);
    if Owned then RegWriteStringValue(WingRoot, WingOwnerKey, 'PathEntry', Desired);
  end;
end;

<event('CurStepChanged')>
procedure WingInstallStep(Step: TSetupStep);
begin
  if Step = ssInstall then WingClearOwned;
  if Step = ssPostInstall then begin
    WingOwned := TStringList.Create;
    try
@@WRITES@@
      RegWriteStringValue(WingRoot, WingOwnerKey, 'Owned', WingOwned.Text);
      WingSyncPath(@@PATH_REQUEST@@);
    finally
      WingOwned.Free;
    end;
  end;
end;

<event('CurUninstallStepChanged')>
procedure WingUninstallStep(Step: TUninstallStep);
begin
  if Step = usUninstall then begin
    WingClearOwned;
    WingSyncPath(False);
    RegDeleteKeyIfEmpty(WingRoot, WingOwnerKey);
  end;
end;
