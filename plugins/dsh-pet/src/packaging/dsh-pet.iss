; -*- mode: ini -*-
; Generic dsh-pet-standalone onedir installer (Inno Setup 6)
;
; Compile (defaults build the webm-chat variant):
;   E:\tools\InnoSetup6\ISCC.exe packaging\dsh-pet.iss
;
; Other variants (override defines on the command line):
;   E:\tools\InnoSetup6\ISCC.exe /DMyAppShortName=dsh-pet-standalone-webm `
;       /DMyAppExeName=dsh-pet-standalone-webm.exe `
;       /DMyAppDir=..\dist-onedir\dsh-pet-standalone-webm `
;       /DMyAppId=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx `
;       /DMyAppDisplay="dsh-pet-standalone (WebM)" packaging\dsh-pet.iss
;
; Output: dist-onedir\<shortname>-setup.exe

#ifndef MyAppShortName
#define MyAppShortName "dsh-pet-standalone-webm-chat"
#endif
#ifndef MyAppExeName
#define MyAppExeName "dsh-pet-standalone-webm-chat.exe"
#endif
#ifndef MyAppDir
#define MyAppDir "..\dist-onedir\dsh-pet-standalone-webm-chat"
#endif
#ifndef MyAppId
; NOTE: value must include the double-brace escaping required by AppId ({{GUID})
#define MyAppId "{{3424d6cc-af3c-4383-8797-ab520b923aa6}"
#endif
#ifndef MyAppDisplay
#define MyAppDisplay "dsh-pet-standalone (WebM Chat)"
#endif
#ifndef MyAppVersion
; 默认版本与 pet/__init__.py 的 __version__ 一致；CI 构建时通过
; /DMyAppVersion=<版本> 从单一来源注入（见 build-windows.yml）。
#define MyAppVersion "4.3.0"
#endif

#ifdef BundleLajiAgent
; ── 捆绑 Laji Agent 安装包（scripts/build-pet-bundle.ps1 注入）──────────────
; 桌宠的「打工」用 installed_desktop_command() 找
; %LOCALAPPDATA%\Programs\Laji Agent\LajiAgent.exe；对方机器上没装就只剩
; 一句「没找到 Laji Agent」气泡。捆绑版把 Agent 安装包一起带走，装完即可打工。
; 两个 /D 由脚本给出；缺任何一个直接编译失败，避免做出一个静默失效的包。
#ifndef LajiAgentSetup
  #error /DLajiAgentSetup=<absolute path of the Laji Agent installer>
#endif
#ifndef LajiAgentSetupName
  #error /DLajiAgentSetupName=<file name of the Laji Agent installer>
#endif
; 捆绑包里的 Agent 版本（脚本从文件名解析）。只判「装没装」会让「本来就装了旧版」
; 的机器永远停在旧版——那正是「别人装了就没自动更新」的成因。
#ifndef LajiAgentVersion
  #error /DLajiAgentVersion=<version of the bundled Laji Agent installer>
#endif
#endif

[Setup]
AppId={#MyAppId}
AppName={#MyAppDisplay}
AppVersion={#MyAppVersion}
AppPublisher=merzlin
; 安装包图标（待机封面帧生成，scripts/make_icon.py）
SetupIconFile=..\assets\icon.ico
; Per-user install, no admin needed; user may pick any drive in the wizard
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#MyAppShortName}
DisableProgramGroupPage=yes
OutputDir=..\dist-onedir
OutputBaseFilename={#MyAppShortName}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 在线更新会以静默方式覆盖现有 onedir；由 Inno 负责关闭占用文件的旧进程。
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no
UninstallDisplayName={#MyAppDisplay}

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#MyAppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

#ifdef BundleLajiAgent
; Agent 安装包只是安装期载荷：落 tmp、装完删掉，不进 {app}。
; 只在「没装或装得比捆绑包旧」时才复制（Check），省掉一次几百 MB 的临时拷贝。
Source: "{#LajiAgentSetup}"; DestDir: "{tmp}\laji-agent"; Flags: deleteafterinstall; Check: LajiAgentNeedsInstall
#endif

[Icons]
Name: "{autoprograms}\{#MyAppShortName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppShortName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
#ifdef BundleLajiAgent
; 先静默装 Laji Agent，再起桌宠：同一 [Run] 段按声明顺序执行，
; waituntilterminated 保证串行。
; 不传 /D：Agent 的 build/installer.nsh 在 customInit 里把 $INSTDIR 写死成
; %LOCALAPPDATA%\Programs\LajiAgent，命令行 /D 会被它覆盖（传了只是假象）。
; 静默安装没有目录选择页，落点恒定，桌宠 _install_roots() 认得这个目录。
; Check 比版本：已装旧版时这里也会跑，electron-builder 的安装器自己负责先卸旧再装。
Filename: "{tmp}\laji-agent\{#LajiAgentSetupName}"; Parameters: "/S"; StatusMsg: "Installing Laji Agent..."; Flags: runhidden waituntilterminated; Check: LajiAgentNeedsInstall
#endif
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppShortName}}"; Flags: nowait postinstall

; 注：这里刻意没有 [UninstallDelete]。
; 旧版有一条 `Type: filesandordirs; Name: "{app}\_MEI*"`，是按名字通配删除——
; `_MEI数字` 是 PyInstaller 的解包目录命名，安装目录里出现的同名目录并不保证是
; 本产品的（任何以本目录为工作目录启动的 onefile 程序都会在这里解包）。没有归属
; 证据就不删：本产品自己的 onefile 运行目录由 pet/runtime_cleanup.py 按归属标记
; 清理（见下方 [Code] 的卸载清理调用）。

[Code]
{ 卸载清理必须在删除 exe 之前跑：exe 一旦被删，清理实现就没了。
  usUninstall 是卸载流程里最早的步骤，此处的 Exec 先于文件删除。
  清理只删本产品 own 的东西（自启项 / Claude hooks / DSH 桥接插件），
  失败必须留痕：退出码写进卸载日志，交互式卸载还会弹一次提示。
  注：本 .iss 是 UTF-8 无 BOM（Inno 按 ANSI 读取），因此**字符串字面量只用 ASCII**，
  中文说明留在注释里；面向用户的详细结果由 Python 侧写进 uninstall-cleanup.log。}
#ifdef BundleLajiAgent
{ 已装的 Laji Agent 是否该被这份捆绑包覆盖。
  只判「装没装」会让「对方本来就装了旧版」的机器永远停在旧版，
  这正是「别人装了就没自动更新」的成因；这里比版本，装得比捆绑包旧才重装。
  第一行是 Agent 安装器 customInit 的真实落点（无空格）：build/installer.nsh。}
function FindLajiAgentExe(out ExePath: String): Boolean;
var
  Candidate: String;
begin
  Candidate := ExpandConstant('{localappdata}\Programs\LajiAgent\LajiAgent.exe');
  if FileExists(Candidate) then begin ExePath := Candidate; Result := True; exit; end;
  Candidate := ExpandConstant('{localappdata}\Programs\Laji Agent\LajiAgent.exe');
  if FileExists(Candidate) then begin ExePath := Candidate; Result := True; exit; end;
  Candidate := ExpandConstant('{localappdata}\Programs\laji-agent\LajiAgent.exe');
  if FileExists(Candidate) then begin ExePath := Candidate; Result := True; exit; end;
  Candidate := ExpandConstant('{localappdata}\Programs\Laji\LajiAgent.exe');
  if FileExists(Candidate) then begin ExePath := Candidate; Result := True; exit; end;
  Candidate := ExpandConstant('{userappdata}\Programs\Laji Agent\LajiAgent.exe');
  if FileExists(Candidate) then begin ExePath := Candidate; Result := True; exit; end;
  ExePath := '';
  Result := False;
end;

{ 'a.b.c' 的第 Index 段；缺段按 0，'1.7' 与 '1.7.0' 等价。}
function VersionSegment(const Ver: String; Index: Integer): Integer;
var
  I, Part, StartPos: Integer;
begin
  Result := 0;
  Part := 1;
  StartPos := 1;
  for I := 1 to Length(Ver) + 1 do
    if (I > Length(Ver)) or (Ver[I] = '.') then
    begin
      if Part = Index then
      begin
        Result := StrToIntDef(Copy(Ver, StartPos, I - StartPos), 0);
        exit;
      end;
      Part := Part + 1;
      StartPos := I + 1;
    end;
end;

function CompareVersions(const A, B: String): Integer;
var
  I, Left, Right: Integer;
begin
  for I := 1 to 4 do
  begin
    Left := VersionSegment(A, I);
    Right := VersionSegment(B, I);
    if Left <> Right then
    begin
      Result := Left - Right;
      exit;
    end;
  end;
  Result := 0;
end;

function LajiAgentNeedsInstall: Boolean;
var
  ExePath, InstalledVer: String;
begin
  Result := True;
  if not FindLajiAgentExe(ExePath) then
  begin
    Log('Laji Agent: not installed, will install {#LajiAgentVersion}');
    exit;
  end;
  if not GetVersionNumbersString(ExePath, InstalledVer) then
  begin
    Log('Laji Agent: cannot read version from ' + ExePath
      + ', will reinstall {#LajiAgentVersion}');
    exit;
  end;
  Result := CompareVersions(InstalledVer, '{#LajiAgentVersion}') < 0;
  if Result then
    Log('Laji Agent: installed ' + InstalledVer + ' is older than bundled '
      + '{#LajiAgentVersion}, will upgrade')
  else
    Log('Laji Agent: installed ' + InstalledVer + ' is up to date (bundled '
      + '{#LajiAgentVersion}), skipping');
end;

{ 空间前置检查：Agent 安装包解压后约 700 MB，且装在 %LOCALAPPDATA%（系统盘）。
  空间不够时 electron-builder 的安装器只回一个退出码 2，界面上看不出原因，
  所以在开始拷文件之前就把话说清楚。1.5 GB 留的是解压 + 回滚的余量。}
function InitializeSetup: Boolean;
var
  FreeBytes, TotalBytes: Int64;
begin
  Result := True;
  if not GetSpaceOnDisk64(ExpandConstant('{localappdata}'), FreeBytes, TotalBytes) then
    exit;
  if FreeBytes >= 1610612736 then
    exit;
  SuppressibleMsgBox('Not enough free space for the bundled Laji Agent installer:'
    + ' it needs about 1.5 GB, but only '
    + IntToStr(FreeBytes div (1024 * 1024)) + ' MB is free on the system drive.'
    + ' Free some space and run this installer again.',
    mbCriticalError, MB_OK, IDOK);
  Result := False;
end;
#endif

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  CleanupExe: String;
  WorkDir: String;
  ResultCode: Integer;
begin
  if CurUninstallStep <> usUninstall then
    exit;
  CleanupExe := ExpandConstant('{app}\{#MyAppExeName}');
  if not FileExists(CleanupExe) then
  begin
    Log('dsh-pet uninstall cleanup skipped: executable not found: ' + CleanupExe);
    exit;
  end;
  { 工作目录先取系统临时目录：onefile 形态会用 --runtime-tmpdir 在当前目录解包，
    指到安装目录会在卸载过程中再造一个解包目录；TEMP 不可用时退回安装目录本身
    （它一定存在，因为 exe 就在那里）。}
  WorkDir := ExpandConstant('{%TEMP}');
  if (WorkDir = '') or (not DirExists(WorkDir)) then
    WorkDir := ExpandConstant('{app}');
  if Exec(CleanupExe, '--uninstall-cleanup', WorkDir,
          SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if ResultCode = 0 then
      Log('dsh-pet uninstall cleanup finished (exit 0)')
    else
    begin
      Log('dsh-pet uninstall cleanup failed for some steps (exit '
        + IntToStr(ResultCode) + ')');
      SuppressibleMsgBox('dsh-pet uninstall cleanup did not fully succeed (exit code '
        + IntToStr(ResultCode) + '). Autostart, Claude hooks or the DSH bridge plugin'
        + ' may still be present; see uninstall-cleanup.log in the configuration'
        + ' directory for details.', mbError, MB_OK, IDOK);
    end;
  end
  else
  begin
    Log('dsh-pet uninstall cleanup could not start: ' + SysErrorMessage(ResultCode));
    SuppressibleMsgBox('Could not run the dsh-pet uninstall cleanup program: '
      + SysErrorMessage(ResultCode), mbError, MB_OK, IDOK);
  end;
end;
