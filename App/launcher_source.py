"""Source for "Baby Luz.exe" (the desktop root's one clickable launcher) --
compiled with PyInstaller into a onefile, windowless exe. Rebuild after
changing this file with:

    python -m PyInstaller --onefile --noconsole --name "Baby Luz" ^
        --distpath ".." --workpath "%TEMP%\babyluz_build" --specpath "%TEMP%\babyluz_build" ^
        launcher_source.py

Deliberately tiny and dependency-free (no customtkinter/onnxruntime/etc.
imports here) -- it only launches automacao_producao/gui_app.py as a
subprocess using the system's own Python, the same one "Instalar (computador
novo).bat" installs the real dependencies into. Bundling those heavy
dependencies into the exe itself would make the build slow and fragile for
no benefit, since the target machine already has them.
"""
import ctypes
import os
import shutil
import subprocess
import sys


def _real_python_command(candidate: str) -> bool:
    """Windows ships a fake python.exe/python3.exe (App Execution Alias) that
    just nags about the Microsoft Store and exits -- same check the .bat
    launchers use: only trust a candidate that actually prints a version."""
    try:
        result = subprocess.run(
            [candidate, "--version"], capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, OSError):
        return False
    output = (result.stdout or "") + (result.stderr or "")
    return output.strip().startswith("Python ")


def _find_windowed_launcher() -> str | None:
    """Prefers the windowless interpreter (pythonw/pyw) so no console flashes
    up behind the GUI."""
    for console_cmd, windowed_cmd in (("python", "pythonw"), ("py", "pyw")):
        if not _real_python_command(console_cmd):
            continue
        return windowed_cmd if shutil.which(windowed_cmd) else console_cmd
    return None


def main() -> None:
    base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.abspath(__file__))
    app_script = os.path.join(base_dir, "App", "automacao_producao", "gui_app.py")

    launcher_cmd = _find_windowed_launcher()
    if not launcher_cmd:
        ctypes.windll.user32.MessageBoxW(
            0,
            "Python não encontrado nesse computador.\n\n"
            "Rode \"App\\Instalar (computador novo).bat\" primeiro.",
            "Baby Luz", 0x10)
        return

    # CREATE_BREAKAWAY_FROM_JOB: the PyInstaller onefile bootloader ties itself
    # (and, by default, any child it spawns) to a Windows Job Object it tears
    # down as soon as this launcher exits -- without breaking away, the real
    # app would get silently killed the instant this tiny launcher process
    # returns, a split second after starting it.
    popen_kwargs = dict(cwd=os.path.dirname(app_script))
    try:
        subprocess.Popen(
            [launcher_cmd, app_script],
            creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB, **popen_kwargs)
    except OSError:
        subprocess.Popen([launcher_cmd, app_script], **popen_kwargs)


if __name__ == "__main__":
    main()
