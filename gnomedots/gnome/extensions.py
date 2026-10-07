"""Installing and enabling GNOME Shell extensions.

Extensions come from extensions.gnome.org, built for the running shell
version, or straight from a GitHub repository. Either way they are unpacked
into the user's extension folder with their settings schemas compiled, then
switched on by listing them in org.gnome.shell enabled-extensions. GNOME on
Wayland only loads new extensions at login, which is why nothing here talks to
the running shell.
"""

import io
import json
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from .. import ui, util
from ..paths import CACHE_DIR, EXTENSIONS_DIR, data_dirs
from . import dconf, gvariant

EGO = "https://extensions.gnome.org"


def user_dir(uuid: str) -> Path:
    return EXTENSIONS_DIR / uuid


def find(uuid: str) -> Path | None:
    """The folder GNOME would load uuid from (user copy wins over system)."""
    for base in data_dirs():
        p = base / "gnome-shell" / "extensions" / uuid
        if (p / "metadata.json").is_file():
            return p
    return None


def metadata(uuid: str) -> dict | None:
    p = find(uuid)
    if not p:
        return None
    try:
        return json.loads((p / "metadata.json").read_text())
    except (OSError, ValueError):
        return None


def installed_version(uuid: str):
    meta = metadata(uuid)
    return meta.get("version") if meta else None


def ego_info(uuid: str, shell_major: int) -> dict | None:
    try:
        info = util.http_json(f"{EGO}/extension-info/?uuid={uuid}&shell_version={shell_major}")
    except Exception as e:  # 404 means no build for this shell
        ui.detail(f"{uuid}: {e}")
        return None
    return info if info.get("download_url") else None


def _safe_members(names, dest: Path):
    for name in names:
        target = (dest / name).resolve()
        if dest.resolve() not in target.parents and target != dest.resolve():
            raise ValueError(f"unsafe path in archive: {name}")


def _compile_schemas(folder: Path) -> None:
    schemas = folder / "schemas"
    if schemas.is_dir() and any(schemas.glob("*.gschema.xml")) and not (schemas / "gschemas.compiled").exists():
        if util.which("glib-compile-schemas"):
            util.run(["glib-compile-schemas", str(schemas)], check=True)
        else:
            ui.warn(f"glib-compile-schemas is missing; {folder.name} may not open its settings")


def _swap_in(staged: Path, uuid: str) -> None:
    final = user_dir(uuid)
    old = final.with_name(f".{uuid}.old")
    if old.exists():
        shutil.rmtree(old)
    if final.exists():
        final.rename(old)
    staged.rename(final)
    if old.exists():
        shutil.rmtree(old)


def _stage(uuid: str) -> Path:
    EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)
    staged = EXTENSIONS_DIR / f".{uuid}.new"
    if staged.exists():
        shutil.rmtree(staged)
    staged.mkdir()
    return staged


def install_zip(data: bytes, uuid: str) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        meta = json.loads(zf.read("metadata.json"))
        if meta.get("uuid") != uuid:
            raise ValueError(f"archive is for {meta.get('uuid')}, expected {uuid}")
        staged = _stage(uuid)
        try:
            _safe_members(zf.namelist(), staged)
            zf.extractall(staged)
            _compile_schemas(staged)
        except Exception:
            shutil.rmtree(staged, ignore_errors=True)
            raise
    _swap_in(staged, uuid)


def install_from_ego(uuid: str, shell_major: int, info: dict | None = None):
    info = info or ego_info(uuid, shell_major)
    if not info:
        raise LookupError(f"extensions.gnome.org has no build of {uuid} for GNOME {shell_major}")
    ui.action(f"install {uuid} v{info.get('version')} from extensions.gnome.org")
    if ui.dry_run:
        return info.get("version")
    data = util.http_get(EGO + info["download_url"], timeout=120)
    install_zip(data, uuid)
    return info.get("version")


SKIP_FROM_SOURCE = {"Makefile", ".git", ".github", ".gitignore", "README.md",
                    "CODE_OF_CONDUCT.md", "CONTRIBUTING.md", "po", "build"}


def github_head(repo: str, branch: str) -> str | None:
    try:
        return util.http_json(f"https://api.github.com/repos/{repo}/commits/{branch}",
                              headers={"Accept": "application/vnd.github+json"})["sha"]
    except Exception as e:
        ui.detail(f"{repo}: {e}")
        return None


def github_metadata(repo: str, ref: str) -> dict | None:
    try:
        return util.http_json(f"https://raw.githubusercontent.com/{repo}/{ref}/metadata.json")
    except Exception as e:
        ui.detail(f"{repo}@{ref[:8]}: {e}")
        return None


def supports(meta: dict | None, shell_major: int) -> bool:
    """Whether an extension's metadata.json lists this GNOME Shell major."""
    versions = (meta or {}).get("shell-version", [])
    return str(shell_major) in {str(v).split(".")[0] for v in versions}


def _extract_all(tf: tarfile.TarFile, dest: Path, members=None) -> None:
    try:
        tf.extractall(dest, members=members, filter="data")
    except TypeError:  # Python without extraction filters
        tf.extractall(dest, members=members)


def _build_from_source(uuid: str, data: bytes, build: list[str], artifact: str) -> None:
    """Run the repository's own build and install the zip it makes."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=CACHE_DIR, prefix="build-") as tmp:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            _extract_all(tf, Path(tmp))
        checkout = next(p for p in Path(tmp).iterdir() if p.is_dir())
        proc = util.run(build, env={"LC_ALL": "C"}, timeout=600, cwd=checkout)
        if proc.returncode != 0:
            lines = (proc.stderr or proc.stdout or "").strip().splitlines()
            raise RuntimeError(f"`{' '.join(build)}` failed" + (f": {lines[-1]}" if lines else ""))
        install_zip((checkout / artifact).read_bytes(), uuid)


def install_from_github(uuid: str, repo: str, ref: str, build: list[str] | None = None,
                        artifact: str | None = None) -> None:
    """Install an extension from a GitHub commit, building it if it needs that."""
    ui.action(f"install {uuid} from github.com/{repo} ({ref[:12]})" + (" and build it" if build else ""))
    if ui.dry_run:
        return
    data = util.http_get(f"https://codeload.github.com/{repo}/tar.gz/{ref}", timeout=120)
    if build:
        _build_from_source(uuid, data, build, artifact)
        return
    staged = _stage(uuid)
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            keep = []
            for m in tf.getmembers():
                parts = PurePosixPath(m.name).parts
                if len(parts) < 2 or parts[1] in SKIP_FROM_SOURCE or parts[-1].endswith(".zip"):
                    continue
                if not (m.isfile() or m.isdir()):
                    continue
                m.name = str(PurePosixPath(*parts[1:]))
                keep.append(m)
            _safe_members([m.name for m in keep], staged)
            _extract_all(tf, staged, keep)
        meta = json.loads((staged / "metadata.json").read_text())
        if meta.get("uuid") != uuid:
            raise ValueError(f"{repo} holds {meta.get('uuid')}, expected {uuid}")
        _compile_schemas(staged)
    except Exception:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    _swap_in(staged, uuid)


def pin_version(uuid: str, version: int) -> None:
    """Rewrite the user copy's metadata version, as local builds do (9999)."""
    meta_file = user_dir(uuid) / "metadata.json"
    ui.action(f"pin {uuid} metadata version to {version}")
    if ui.dry_run:
        return
    meta = json.loads(meta_file.read_text())
    meta["version"] = version
    meta.pop("_generated", None)
    meta_file.write_text(json.dumps(meta, indent=4) + "\n")


def remove_user_copy(uuid: str) -> None:
    util.remove_tree(user_dir(uuid))


# -- enabling --------------------------------------------------------------

def _shell_list(key: str) -> list[str]:
    out = util.output(["gsettings", "get", "org.gnome.shell", key])
    if out is None:
        out = dconf.read(f"/org/gnome/shell/{key}")
    return gvariant.load_strv(out)


def enabled() -> list[str]:
    return _shell_list("enabled-extensions")


def disabled() -> list[str]:
    return _shell_list("disabled-extensions")


def set_enabled(enable: list[str], disable: list[str]) -> None:
    """Enable and disable extensions by uuid, keeping everything else as is."""
    on = [u for u in enabled() if u not in disable]
    on += [u for u in enable if u not in on]
    off = [u for u in disabled() if u not in enable]
    off += [u for u in disable if u not in off]
    dconf.write("/org/gnome/shell/enabled-extensions", on)
    dconf.write("/org/gnome/shell/disabled-extensions", off)
    dconf.write("/org/gnome/shell/disable-user-extensions", False)

