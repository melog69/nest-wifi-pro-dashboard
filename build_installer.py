"""
build_installer.py — Generates a native Windows Self-Extracting Executable (SFX).

Uses Microsoft Windows IExpress (built into all Windows versions) to compile
a standalone installer package: NestWifiProDashboard-Setup.exe.

When run on any Windows machine (such as a Plex media server):
  1. Extracts files into a temp directory.
  2. Runs installer.bat automatically.
  3. Deploys to %LOCALAPPDATA%\\NestWifiProDashboard.
  4. Configures Python virtualenv and dependencies.
  5. Registers the headless Windows background service.
  6. Creates Desktop shortcuts and launches the service.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_DIR, "dist")
STAGING_DIR = os.path.join(DIST_DIR, "staging")


def build() -> int:
    print("=" * 60)
    print("  Nest Wifi Pro Dashboard — Windows SFX Installer Builder")
    print("=" * 60)

    # 1. Ensure service scripts exist
    try:
        import service_manager
        service_manager.ensure_launcher_scripts()
        print("  ✓ Standalone service scripts generated")
    except Exception as exc:
        print(f"  ⚠ Could not refresh service scripts: {exc}")

    # 2. Prepare staging directory
    if os.path.exists(STAGING_DIR):
        shutil.rmtree(STAGING_DIR)
    os.makedirs(STAGING_DIR, exist_ok=True)
    os.makedirs(DIST_DIR, exist_ok=True)

    # 3. Copy files to staging
    payload_files = [
        "app.py",
        "config.py",
        "credentials.py",
        "service_manager.py",
        "wifi_client.py",
        "auth_helper.py",
        "auth_auto.py",
        "run.py",
        "requirements.txt",
        ".env.example",
        "LICENSE",
        "README.md",
        "start.bat",
        "setup_auth.bat",
        "setup_auth_auto.bat",
        "start_background.vbs",
        "start_background.bat",
        "stop_background.bat",
        "install_service.bat",
        "uninstall_service.bat",
        "installer.bat",
    ]

    staged_list: list[str] = []

    for fname in payload_files:
        src = os.path.join(PROJECT_DIR, fname)
        if os.path.exists(src):
            dst = os.path.join(STAGING_DIR, fname)
            shutil.copy2(src, dst)
            staged_list.append(fname)
        else:
            print(f"  ⚠ Skipping missing file: {fname}")

    # Copy static files with prefix for flat IExpress packaging
    static_index = os.path.join(PROJECT_DIR, "static", "index.html")
    if os.path.exists(static_index):
        shutil.copy2(static_index, os.path.join(STAGING_DIR, "static_index.html"))
        staged_list.append("static_index.html")

    static_settings = os.path.join(PROJECT_DIR, "static", "settings.html")
    if os.path.exists(static_settings):
        shutil.copy2(static_settings, os.path.join(STAGING_DIR, "static_settings.html"))
        staged_list.append("static_settings.html")

    print(f"  ✓ Staged {len(staged_list)} payload files into {STAGING_DIR}")

    # 4. Generate SED directive file for IExpress
    target_exe = os.path.join(DIST_DIR, "NestWifiProDashboard-Setup.exe")
    sed_file = os.path.join(DIST_DIR, "installer.sed")

    # Build file strings and entries
    strings_entries = []
    source_entries = []
    for idx, fname in enumerate(staged_list):
        tag = f"FILE{idx}"
        strings_entries.append(f'{tag}="{fname}"')
        source_entries.append(f"%{tag}%=")

    strings_block = "\n".join(strings_entries)
    source_block = "\n".join(source_entries)

    # Normalize paths for Windows
    norm_staging = os.path.abspath(STAGING_DIR).rstrip("\\") + "\\"
    norm_target = os.path.abspath(target_exe)

    sed_content = f"""[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=0
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=%InstallPrompt%
DisplayLicense=
FinishMessage=%FinishMessage%
TargetName=%TargetName%
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=%PostInstallCmd%
AdminQuietInstCmd=%AdminQuietInstCmd%
UserQuietInstCmd=%UserQuietInstCmd%
SourceFiles=SourceFiles
[Strings]
InstallPrompt=Would you like to install the Nest Wifi Pro Dashboard on this system?
FinishMessage=
TargetName={norm_target}
FriendlyName=Nest Wifi Pro Dashboard Setup
AppLaunched=cmd.exe /c installer.bat
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
{strings_block}
[SourceFiles]
SourceFiles0={norm_staging}
[SourceFiles0]
{source_block}
"""

    with open(sed_file, "w", encoding="ascii", errors="replace") as f:
        f.write(sed_content)

    print(f"  ✓ Created IExpress directive: {sed_file}")

    # 5. Invoke IExpress
    print("  ⏳ Compiling Self-Extracting Executable with IExpress...")
    if os.path.exists(target_exe):
        try:
            os.remove(target_exe)
        except Exception:
            pass

    try:
        proc = subprocess.run(
            ["iexpress.exe", "/N", sed_file],
            cwd=DIST_DIR,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0 and not os.path.exists(target_exe):
            print(f"  ✗ IExpress exited with code {proc.returncode}: {proc.stderr}")
            return 1
    except Exception as exc:
        print(f"  ✗ Failed to run iexpress.exe: {exc}")
        return 1

    if not os.path.exists(target_exe):
        print("  ✗ Target installer executable was not created.")
        return 1

    size_mb = os.path.getsize(target_exe) / (1024 * 1024)
    print("=" * 60)
    print(f"  ✓ SFX Installer successfully generated!")
    print(f"  📦 Location : {target_exe}")
    print(f"  📏 File Size: {size_mb:.2f} MB")
    print("=" * 60)

    # Also place a copy in project root for convenience
    root_copy = os.path.join(PROJECT_DIR, "NestWifiProDashboard-Setup.exe")
    try:
        shutil.copy2(target_exe, root_copy)
        print(f"  ✓ Standalone installer copied to project root:")
        print(f"    {root_copy}")
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(build())
