; Copyright (c) 2026, wingsummer
; SPDX-License-Identifier: BSD-3-Clause
; See LICENSE in the project root for license information.

; Illustrative project-owned template; shared settings supply application details.
[Setup]
@SETUP_DIRECTIVES@

[Files]
Source: "@PAYLOAD@\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

@INSTALLATION_SECTIONS@

[Code]
// Event attributes keep project callbacks compatible with generated helpers.
<event('CurStepChanged')>
procedure ProjectInstallStep(Step: TSetupStep);
begin
  if Step = ssPostInstall then Log('Project installation callback completed');
end;
