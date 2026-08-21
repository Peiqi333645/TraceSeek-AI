; Inno Setup 脚本 — TraceSeek-AI Windows 安装程序
; 用法: ISCC.exe /DMyAppVersion=1.0.0 packaging\traceseek.iss
; 产物: packaging\Output\TraceSeek-AI-Setup.exe
; 前置: PyInstaller 已产出 dist\TraceSeek-AI\(并已 copy_browsers 拷入 ms-playwright)

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "寻迹AI助手"
#define MyAppExe "TraceSeek-AI.exe"
#define MyAppPublisher "TraceSeek AI"

[Setup]
AppId={{E6A78A2B-6B94-4A71-9F18-2D50A17913D1}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=TraceSeek-AI-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; ChineseSimplified.isl 是非官方翻译, Inno Setup 标准安装/choco 包都不带,
; 所以随仓库一起带一份(packaging/ChineseSimplified.isl), 用 {#SourcePath} 按脚本目录定位。
[Languages]
Name: "chinesesimplified"; MessagesFile: "{#SourcePath}ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Files]
Source: "..\dist\TraceSeek-AI\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
