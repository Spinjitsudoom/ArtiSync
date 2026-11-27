"""
updater.py
Update checks and self-updates from GitHub Releases. GUI-free.

check() asks GitHub for the latest published release. How an update is put
in place depends on how this copy was installed (install_kind()):

  windows-installer  run the new ArtiSync-Setup.exe silently; it closes and
                     relaunches the app
  windows-portable   unzip the new build, swap it into the app folder once the
                     app has exited (PowerShell), relaunch
  macos              unzip the new ArtiSync.app, swap it in once the app has
                     exited (sh), relaunch
  appimage           download next to the AppImage, rename over it, relaunch
  flatpak            save the .flatpak bundle to Downloads for the user to open
                     (the sandbox can't reinstall its own app)
  bundle / source    point to the release page

When the app's own location isn't writable, the update is downloaded to the
Downloads folder instead. Every download is checked against the size and
SHA-256 digest GitHub lists for the asset.
"""

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

import version

REPO = "Spinjitsudoom/ArtiSync"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
TEMP_PREFIX = "artisync-update-"

# The release asset each kind of install updates itself from.
ASSETS = {
    "windows-installer": "ArtiSync-Setup.exe",
    "windows-portable": "ArtiSync-Portable.zip",
    "macos": "ArtiSync-macOS-app.zip",
    "appimage": "ArtiSync.AppImage",
    "flatpak": "ArtiSync.flatpak",
}
# What to save to Downloads when the app can't replace itself.
MANUAL_ASSETS = dict(ASSETS, macos="ArtiSync-macOS.dmg")


class UpdateError(Exception):
    pass


class Cancelled(UpdateError):
    pass


# ── Versions ──────────────────────────────────────────────────────────────────

def parse_version(text):
    """'v3.1.0' -> (3, 1, 0); () when there's no version number."""
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", text or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def is_newer(remote, local=None):
    r = parse_version(remote)
    l = parse_version(local if local is not None else version.VERSION)
    n = max(len(r), len(l))
    return bool(r) and r + (0,) * (n - len(r)) > l + (0,) * (n - len(l))


# ── Releases ──────────────────────────────────────────────────────────────────

@dataclass
class Asset:
    name: str
    url: str
    size: int
    sha256: str | None     # hex digest, when GitHub lists one


@dataclass
class Release:
    version: str           # "3.1.0"
    notes: str             # Markdown
    page_url: str
    assets: dict           # name -> Asset


def _open(url, timeout, accept=None):
    headers = {"User-Agent": version.USER_AGENT}
    if accept:
        headers["Accept"] = accept
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                  timeout=timeout)


def latest_release(timeout=10):
    try:
        with _open(API_LATEST, timeout, "application/vnd.github+json") as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("No releases have been published yet.") from None
        if e.code in (403, 429):
            raise UpdateError("GitHub is limiting requests right now. "
                              "Try again later.") from None
        raise UpdateError(f"GitHub answered with HTTP {e.code}.") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", None) or e
        raise UpdateError(f"Couldn't reach GitHub ({reason}).") from None
    assets = {}
    for a in data.get("assets") or []:
        digest = a.get("digest") or ""
        assets[a["name"]] = Asset(
            name=a["name"], url=a.get("browser_download_url", ""),
            size=int(a.get("size") or 0),
            sha256=digest[7:].lower() if digest.startswith("sha256:") else None)
    tag = data.get("tag_name") or ""
    return Release(version=tag.lstrip("v"), notes=data.get("body") or "",
                   page_url=data.get("html_url") or RELEASES_PAGE, assets=assets)


def check(timeout=10):
    """The latest release if it's newer than this copy, else None."""
    cleanup_old()
    rel = latest_release(timeout)
    return rel if is_newer(rel.version) else None


# ── How this copy is installed ────────────────────────────────────────────────

def _app_bundle():
    for p in Path(sys.executable).resolve().parents:
        if p.suffix == ".app":
            return p
    return None


def install_kind():
    if os.environ.get("FLATPAK_ID") or os.path.exists("/.flatpak-info"):
        return "flatpak"
    if not getattr(sys, "frozen", False):
        return "source"
    if sys.platform == "win32":
        exe_dir = Path(sys.executable).resolve().parent
        return ("windows-installer" if (exe_dir / "unins000.exe").exists()
                else "windows-portable")
    if sys.platform == "darwin":
        return "macos" if _app_bundle() else "bundle"
    if os.environ.get("APPIMAGE"):
        return "appimage"
    return "bundle"


def _target(kind):
    """The file or folder an update replaces."""
    if kind == "windows-portable":
        return Path(sys.executable).resolve().parent
    if kind == "macos":
        return _app_bundle()
    if kind == "appimage" and os.environ.get("APPIMAGE"):
        return Path(os.environ["APPIMAGE"])
    return None


def _can_create_in(folder):
    # A real write test: on Windows os.access ignores folder permissions.
    try:
        with tempfile.TemporaryFile(dir=folder):
            return True
    except OSError:
        return False


def _writable(kind):
    if kind == "windows-installer":
        return True                       # the installer asks for rights itself
    t = _target(kind)
    if t is None:
        return False
    if kind == "windows-portable":
        return _can_create_in(t) and _can_create_in(t / "_internal")
    return _can_create_in(t.parent) and os.access(t, os.W_OK)


@dataclass
class Plan:
    kind: str
    action: str            # "install" (replace and restart), "download" or "page"
    asset: Asset | None


def plan(release, kind=None):
    kind = kind or install_kind()
    if kind in ASSETS and kind != "flatpak" and _writable(kind):
        asset = release.assets.get(ASSETS[kind])
        if asset:
            return Plan(kind, "install", asset)
    asset = release.assets.get(MANUAL_ASSETS.get(kind, ""))
    if asset:
        return Plan(kind, "download", asset)
    return Plan(kind, "page", None)


# ── Downloading ───────────────────────────────────────────────────────────────

def _free_name(folder, name):
    """name in folder, or 'stem (2).ext' etc. if that's taken."""
    p = Path(folder) / name
    stem, suffix = p.stem, p.suffix
    n = 2
    while p.exists():
        p = Path(folder) / f"{stem} ({n}){suffix}"
        n += 1
    return p


def download(asset, dest, report=None, cancel=None):
    """Download asset to the path dest and verify it. report(done, total) is
    called as it goes; set the cancel Event to stop (raises Cancelled)."""
    if not asset.url.startswith(DOWNLOAD_PREFIX):
        raise UpdateError("Unexpected download address.")
    dest = Path(dest)
    part = dest.with_name("." + dest.name + ".part")
    h = hashlib.sha256()
    done = 0
    try:
        with _open(asset.url, 30) as r, open(part, "wb") as f:
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled("Download cancelled.")
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if report:
                    report(done, asset.size)
        if asset.size and done != asset.size:
            raise UpdateError("The download was incomplete. Try again.")
        if asset.sha256 and h.hexdigest() != asset.sha256:
            raise UpdateError("The download didn't match the release's checksum, "
                              "so it wasn't used.")
        os.replace(part, dest)
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, OSError) as e:
        part.unlink(missing_ok=True)
        reason = getattr(e, "reason", None) or e
        raise UpdateError(f"Download failed ({reason}).") from None
    return dest


def fetch(p, downloads_dir, report=None, cancel=None):
    """Download what plan p needs. For "install" the file goes somewhere it
    can be applied from; for "download" into downloads_dir."""
    if p.action == "download":
        Path(downloads_dir).mkdir(parents=True, exist_ok=True)
        return download(p.asset, _free_name(downloads_dir, p.asset.name), report, cancel)
    if p.kind == "appimage":
        # Same folder as the AppImage, so it can be renamed over it.
        t = _target(p.kind)
        return download(p.asset, t.with_name("." + t.name + ".new"), report, cancel)
    tmp = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    return download(p.asset, tmp / p.asset.name, report, cancel)


def cleanup_old():
    """Remove temporary folders left by earlier updates."""
    for d in Path(tempfile.gettempdir()).glob(TEMP_PREFIX + "*"):
        shutil.rmtree(d, ignore_errors=True)


# ── Applying ──────────────────────────────────────────────────────────────────

def _clean_env():
    """Environment for the relaunched app, minus anything pointing into this
    bundle (PyInstaller's library path, the AppImage's mount)."""
    env = dict(os.environ)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for k, v in list(env.items()):
            if meipass in v and k not in ("PATH",):
                env.pop(k)
        if "LD_LIBRARY_PATH_ORIG" in env:
            env["LD_LIBRARY_PATH"] = env.pop("LD_LIBRARY_PATH_ORIG")
    for k in ("APPIMAGE", "APPDIR", "ARGV0", "OWD"):
        env.pop(k, None)
    return env


def _spawn_detached(args):
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL, close_fds=True, env=_clean_env())
    if sys.platform == "win32":
        kw["creationflags"] = (subprocess.CREATE_NO_WINDOW
                               | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kw["start_new_session"] = True
    subprocess.Popen(args, **kw)


def _ps(s):
    return "'" + str(s).replace("'", "''") + "'"


def _apply_windows_installer(file):
    args = ["/SILENT", "/SP-", "/SUPPRESSMSGBOXES", "/NORESTART",
            "/CLOSEAPPLICATIONS", "/NOCANCEL"]
    local = os.environ.get("LOCALAPPDATA")
    exe = str(Path(sys.executable).resolve())
    if local and exe.lower().startswith(str(Path(local).resolve()).lower()):
        args.append("/CURRENTUSER")      # it was installed for this user only
    else:
        args.append("/ALLUSERS")
    # ShellExecute rather than CreateProcess, so Windows can show the UAC prompt.
    os.startfile(str(file), "open", " ".join(args))


def _apply_windows_portable(file):
    work = file.parent
    new_root = work / "new"
    with zipfile.ZipFile(file) as z:
        z.extractall(new_root)
    found = next((p.parent for p in new_root.rglob("ArtiSync.exe")
                  if (p.parent / "_internal").is_dir()), None)
    if found is None:
        raise UpdateError("The downloaded zip doesn't contain ArtiSync.")
    app = _target("windows-portable")
    script = work / "update.ps1"
    # Only ArtiSync.exe and _internal are swapped, so anything else in the
    # folder is left alone. The old copy is restored if the copy fails.
    script.write_text(f"""
$ErrorActionPreference = 'Stop'
$app = {_ps(app)}; $new = {_ps(found)}; $work = {_ps(work)}
$exe = Join-Path $app 'ArtiSync.exe'; $int = Join-Path $app '_internal'
try {{ Wait-Process -Id {os.getpid()} }} catch {{}}
Start-Sleep -Milliseconds 500
try {{
  Remove-Item -LiteralPath "$int.old", "$exe.old" -Recurse -Force -ErrorAction SilentlyContinue
  Rename-Item -LiteralPath $int -NewName '_internal.old'
  Rename-Item -LiteralPath $exe -NewName 'ArtiSync.exe.old'
  try {{
    Get-ChildItem -LiteralPath $new | Copy-Item -Destination $app -Recurse -Force
    Remove-Item -LiteralPath "$int.old", "$exe.old" -Recurse -Force -ErrorAction SilentlyContinue
  }} catch {{
    Remove-Item -LiteralPath $int, $exe -Recurse -Force -ErrorAction SilentlyContinue
    Rename-Item -LiteralPath "$int.old" -NewName '_internal'
    Rename-Item -LiteralPath "$exe.old" -NewName 'ArtiSync.exe'
  }}
}} finally {{
  Start-Process -FilePath $exe
  Set-Location $env:TEMP
  Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}}
""", encoding="utf-8-sig")
    _spawn_detached(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                     "-WindowStyle", "Hidden", "-File", str(script)])


def _apply_macos(file):
    work = file.parent
    new_root = work / "new"
    # ditto keeps the bundle's symlinks, permissions and signature.
    subprocess.run(["ditto", "-x", "-k", str(file), str(new_root)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    new_app = new_root / "ArtiSync.app"
    if not new_app.is_dir():
        raise UpdateError("The downloaded zip doesn't contain ArtiSync.app.")
    app = _target("macos")
    q = shlex.quote
    script = work / "update.sh"
    script.write_text(f"""#!/bin/sh
while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.3; done
app={q(str(app))}; new={q(str(new_app))}
rm -rf "$app.old"
if mv "$app" "$app.old"; then
  if mv "$new" "$app"; then rm -rf "$app.old"; else mv "$app.old" "$app"; fi
fi
open "$app"
rm -rf {q(str(work))}
""")
    _spawn_detached(["/bin/sh", str(script)])


def _apply_appimage(file):
    target = _target("appimage")
    os.chmod(file, 0o755)
    # The running copy keeps its old (already open) file; the next launch
    # gets the new one.
    os.replace(file, target)
    _spawn_detached(["/bin/sh", "-c",
                     'while kill -0 "$1" 2>/dev/null; do sleep 0.3; done; exec "$2"',
                     "sh", str(os.getpid()), str(target)])


def apply(p, file):
    """Put the downloaded update in place. Returns True when the app should
    now quit so the update can finish and relaunch it."""
    file = Path(file)
    if p.action != "install":
        return False
    try:
        {"windows-installer": _apply_windows_installer,
         "windows-portable": _apply_windows_portable,
         "macos": _apply_macos,
         "appimage": _apply_appimage}[p.kind](file)
    except UpdateError:
        raise
    except (OSError, subprocess.SubprocessError, zipfile.BadZipFile) as e:
        raise UpdateError(f"Couldn't install the update ({e}).") from None
    return True
