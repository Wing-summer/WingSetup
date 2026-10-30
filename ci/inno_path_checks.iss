; Copyright (c) 2026, wingsummer
; SPDX-License-Identifier: BSD-3-Clause
; See LICENSE in the project root for license information.

[Code]
procedure WingFixturePathRoundTrip(Baseline: String);
var
  Added, Restored: String;
  Found: Boolean;
begin
  Added := WingAppendPath(Baseline, 'C:\WingSetup Fixture');
  Restored := WingFilterPath(Added, 'C:\WingSetup Fixture', True, Found);
  if (not Found) or (Restored <> Baseline) then
    RaiseException('PATH round-trip failed for [' + Baseline + '] -> [' + Restored + ']');
end;

<event('InitializeSetup')>
function WingFixturePathChecks: Boolean;
begin
  // Execute the production Pascal functions without changing any registry values.
  WingFixturePathRoundTrip('');
  WingFixturePathRoundTrip('C:\Keep');
  WingFixturePathRoundTrip('C:\Keep;');
  WingFixturePathRoundTrip(';');
  WingFixturePathRoundTrip(';;');
  WingFixturePathRoundTrip(';C:\Keep;;');
  WingFixturePathRoundTrip('%USERPROFILE%\Tools;;C:\Keep;');
  Log('WingSetup PATH round-trip checks passed');
  Result := True;
end;
