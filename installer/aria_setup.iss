; =============================================================================
; ARIA — Windows Installer Script
; Inno Setup 6.3+   https://jrsoftware.org/isinfo.php
;
; Build from repo root:
;   iscc installer\aria_setup.iss
;   (or open this file in the Inno Setup IDE and press F9)
;
; Output: installer\dist\ARIA_Setup.exe
;
; Prerequisites for the END USER (checked at runtime — NOT bundled):
;   • Python 3.10+  https://www.python.org/downloads/
;   • Ollama        https://ollama.com/download
; =============================================================================

#define AppName      "ARIA"
#define AppVersion   "1.0"
#define AppPublisher "Ziyad Noucair"
#define AppURL       "https://github.com/zn200/ARIA_PUBLIC"
#define OllamaModel  "qwen2.5:7b"

; ---------------------------------------------------------------------------
[Setup]
; A unique AppId prevents conflicts with other Inno Setup packages.
; Do NOT reuse this GUID in any other installer.
AppId={{F3A72C1D-8B4E-4F29-9D6A-E5C18047B321}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}

; Install to per-user AppData — no admin required
DefaultDirName={localappdata}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; Output
OutputDir=dist
OutputBaseFilename=ARIA_Setup
SetupMutex=ARIASetupMutex

; Appearance
WizardStyle=modern
; The PNG is used as the large wizard image (right-hand panel).
; Must be exactly 164 x 314 px for best results; Inno Setup will scale it.
WizardImageFile=..\static\aria_icon.png
WizardImageStretch=yes
; To add an .ico to the installer .exe itself, convert aria_icon.png first:
;   magick static\aria_icon.png -define icon:auto-resize installer\aria_icon.ico
; Then uncomment:
; SetupIconFile=aria_icon.ico

; Privileges — per-user install, no UAC prompt
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Windows 10+ only (same requirement as PyAudio / faster-whisper)
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Compression
Compression=lzma2/max
SolidCompression=yes

; Uninstall
UninstallDisplayName={#AppName}
; UninstallDisplayIcon={app}\static\aria_icon.ico

; ---------------------------------------------------------------------------
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

; ---------------------------------------------------------------------------
[Files]
; ── Python source files ────────────────────────────────────────────────────
Source: "..\app.py";              DestDir: "{app}"; Flags: ignoreversion
Source: "..\aria.py";             DestDir: "{app}"; Flags: ignoreversion
Source: "..\launch.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "..\diagnostic.py";       DestDir: "{app}"; Flags: ignoreversion
Source: "..\hw_detect.py";        DestDir: "{app}"; Flags: ignoreversion
Source: "..\proactive_engine.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\setup.py";            DestDir: "{app}"; Flags: ignoreversion
Source: "..\spotify_reader.py";   DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt";    DestDir: "{app}"; Flags: ignoreversion
Source: "..\.env.example";        DestDir: "{app}"; Flags: ignoreversion

; ── Package sub-directories ────────────────────────────────────────────────
Source: "..\modules\*";   DestDir: "{app}\modules";   Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\scripts\*";   DestDir: "{app}\scripts";   Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\static\*";    DestDir: "{app}\static";    Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\templates\*"; DestDir: "{app}\templates"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docs\*";      DestDir: "{app}\docs";      Flags: ignoreversion recursesubdirs createallsubdirs

; ── Default data files (never overwrite if user has personalised them) ─────
Source: "..\data\*"; DestDir: "{app}\data"; Flags: ignoreversion recursesubdirs createallsubdirs onlyifdoesntexist

; ── Bundled uninstaller helper ────────────────────────────────────────────
Source: "uninstall.bat"; DestDir: "{app}"; Flags: ignoreversion

; ---------------------------------------------------------------------------
[Icons]
; Desktop shortcut — points to venv Python so no activation is needed
Name: "{userdesktop}\{#AppName}"; \
    Filename: "{app}\.venv\Scripts\python.exe"; \
    Parameters: """{app}\app.py"""; \
    WorkingDir: "{app}"; \
    Comment: "Launch ARIA voice assistant"

; Start Menu shortcut
Name: "{group}\{#AppName}"; \
    Filename: "{app}\.venv\Scripts\python.exe"; \
    Parameters: """{app}\app.py"""; \
    WorkingDir: "{app}"; \
    Comment: "Launch ARIA voice assistant"

; Start Menu — Uninstall
Name: "{group}\Uninstall {#AppName}"; \
    Filename: "{uninstallexe}"

; ---------------------------------------------------------------------------
[Run]
; Each step runs after all files are copied.
; Steps 1-5 are mandatory setup; step 6 is an optional finish-page checkbox.

; ─── 1. Create Python virtual environment ────────────────────────────────
Filename: "{sys}\cmd.exe"; \
    Parameters: "/c {code:GetPythonCmd} -m venv ""{app}\.venv"""; \
    WorkingDir: "{app}"; \
    StatusMsg: "Creating Python virtual environment..."; \
    Flags: runhidden waituntilterminated

; ─── 2. Upgrade pip (avoids "outdated pip" warnings during install) ───────
Filename: "{app}\.venv\Scripts\python.exe"; \
    Parameters: "-m pip install --upgrade pip --quiet"; \
    WorkingDir: "{app}"; \
    StatusMsg: "Upgrading pip..."; \
    Flags: runhidden waituntilterminated

; ─── 3. Install Python dependencies ──────────────────────────────────────
; Runs hidden — the StatusMsg keeps the user informed.
; This is the longest step; expect 2–10 minutes depending on connection speed.
Filename: "{app}\.venv\Scripts\pip.exe"; \
    Parameters: "install -r ""{app}\requirements.txt"" --quiet"; \
    WorkingDir: "{app}"; \
    StatusMsg: "Installing Python packages (this may take several minutes)..."; \
    Flags: runhidden waituntilterminated

; ─── 4. Pull Ollama model ─────────────────────────────────────────────────
; Shown in a visible console so the user can see download progress.
; Model size: qwen2.5:7b ≈ 4.7 GB — may take several minutes.
Filename: "{sys}\cmd.exe"; \
    Parameters: "/c ollama pull {#OllamaModel} & echo. & echo Done — press any key to continue & pause >nul"; \
    WorkingDir: "{app}"; \
    StatusMsg: "Pulling {#OllamaModel} via Ollama (may take several minutes)..."; \
    Flags: waituntilterminated

; ─── 5. Run ARIA configuration wizard ────────────────────────────────────
; Interactive — opens a console window for the user to answer prompts.
Filename: "{app}\.venv\Scripts\python.exe"; \
    Parameters: "setup.py"; \
    WorkingDir: "{app}"; \
    StatusMsg: "Running ARIA configuration wizard..."; \
    Flags: waituntilterminated

; ─── 6. Launch ARIA now (optional finish-page checkbox) ──────────────────
Filename: "{app}\.venv\Scripts\python.exe"; \
    Parameters: """{app}\app.py"""; \
    WorkingDir: "{app}"; \
    Description: "Launch ARIA now"; \
    Flags: postinstall nowait skipifsilent

; ---------------------------------------------------------------------------
[UninstallDelete]
; Remove generated directories the file-level uninstaller wouldn't know about
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\.env"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\modules\__pycache__"
Type: filesandordirs; Name: "{app}\.cache"
Type: filesandordirs; Name: "{app}\data\piper"

; ---------------------------------------------------------------------------
[Code]

var
  GPythonCmd: String;   // "py -3" or "python" — determined by FindPython()

// =============================================================================
// Helper: run a hidden cmd.exe command and capture the first line of stdout.
// Returns True if the command exited 0 and produced output.
// =============================================================================
function RunAndCaptureLine(Cmd: String; var OutLine: String): Boolean;
var
  TmpFile : String;
  ExitCode: Integer;
  Lines   : TArrayOfString;
begin
  Result  := False;
  OutLine := '';
  TmpFile := ExpandConstant('{tmp}\aria_probe.txt');

  if not Exec(ExpandConstant('{sys}\cmd.exe'),
              '/c ' + Cmd + ' > "' + TmpFile + '" 2>&1',
              '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
    Exit;

  if ExitCode <> 0 then Exit;
  if not LoadStringsFromFile(TmpFile, Lines) then Exit;
  if GetArrayLength(Lines) = 0 then Exit;

  OutLine := Trim(Lines[0]);
  Result  := (OutLine <> '');
end;

// =============================================================================
// Python detection
// Tries the Windows 'py' launcher first (safest on Windows), then 'python'.
// Sets GPythonCmd to the usable command.
// =============================================================================
function FindPython(): Boolean;
var
  Output: String;
  Minor : Integer;
begin
  Result := False;

  // ── Try Windows py launcher (py.exe) ─────────────────────────────────────
  if RunAndCaptureLine(
      'py -3 -c "import sys; print(sys.version_info.minor)"', Output) then
  begin
    Minor := StrToIntDef(Output, -1);
    if Minor >= 10 then
    begin
      GPythonCmd := 'py -3';
      Result := True;
      Exit;
    end;
    if Minor >= 0 then
    begin
      // py launcher found but version < 3.10
      MsgBox(
        'Python 3.' + Output + ' was found, but ARIA requires Python 3.10 or newer.' + #13#10 +
        'Please install Python 3.11 or 3.12 (64-bit) from https://www.python.org/downloads/' + #13#10 +
        'then re-run this installer.',
        mbError, MB_OK);
      Exit;
    end;
  end;

  // ── Try 'python' on PATH ─────────────────────────────────────────────────
  if RunAndCaptureLine(
      'python -c "import sys; print(sys.version_info.minor)"', Output) then
  begin
    Minor := StrToIntDef(Output, -1);
    if Minor >= 10 then
    begin
      GPythonCmd := 'python';
      Result := True;
      Exit;
    end;
  end;
end;

// =============================================================================
// Ollama detection
// =============================================================================
function FindOllama(): Boolean;
var
  ExitCode: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\cmd.exe'),
                 '/c ollama --version >nul 2>&1',
                 '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
  Result := Result and (ExitCode = 0);
end;

// =============================================================================
// Getter used by [Run] via {code:GetPythonCmd}
// =============================================================================
function GetPythonCmd(Param: String): String;
begin
  Result := GPythonCmd;
end;

// =============================================================================
// InitializeSetup — runs once before the wizard is displayed.
// Aborts early if Python 3.10+ or Ollama are missing, and opens the
// appropriate download page so the user knows exactly what to install.
// =============================================================================
function InitializeSetup(): Boolean;
var
  Ans: Integer;
begin
  Result := True;

  // ── 1. Python 3.10+ ────────────────────────────────────────────────────
  if not FindPython() then
  begin
    Ans := MsgBox(
      'Python 3.10 or newer is required but was not found.' + #13#10 +
      #13#10 +
      'Click OK to open the Python download page.' + #13#10 +
      #13#10 +
      'Installation tips:' + #13#10 +
      '  • Download Python 3.11 or 3.12 (64-bit).' + #13#10 +
      '  • On the first installer screen, check "Add Python to PATH".' + #13#10 +
      '  • After Python installs, re-run this ARIA installer.',
      mbInformation, MB_OKCANCEL);

    if Ans = IDOK then
      ShellExec('open', 'https://www.python.org/downloads/',
                '', '', SW_SHOWNORMAL, ewNoWait, Ans);

    Result := False;
    Exit;
  end;

  // ── 2. Ollama ───────────────────────────────────────────────────────────
  if not FindOllama() then
  begin
    Ans := MsgBox(
      'Ollama is required but was not found.' + #13#10 +
      #13#10 +
      'Ollama is the local AI engine that powers ARIA''s brain.' + #13#10 +
      #13#10 +
      'Click OK to open the Ollama download page.' + #13#10 +
      'Install Ollama, then re-run this ARIA installer.',
      mbInformation, MB_OKCANCEL);

    if Ans = IDOK then
      ShellExec('open', 'https://ollama.com/download',
                '', '', SW_SHOWNORMAL, ewNoWait, Ans);

    Result := False;
    Exit;
  end;
end;
