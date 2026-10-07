"""Small helpers shared by every layer: processes, HTTP and files."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import APP_NAME, __version__, ui

USER_AGENT = f"{APP_NAME}/{__version__} (+https://github.com/knirby/gnome-dots)"


class CommandError(RuntimeError):
    pass


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def run(cmd: list[str], *, mutate: bool = False, check: bool = False,
        capture: bool = True, input: str | None = None, env: dict | None = None,
        timeout: float | None = None, cwd=None) -> subprocess.CompletedProcess:
    """Run a command. Commands that change the system pass mutate=True and are
    skipped in dry-run mode; queries always run."""
    shown = " ".join(cmd)
    if mutate:
        ui.action(shown)
        if ui.dry_run:
            return subprocess.CompletedProcess(cmd, 0, "", "")
    else:
        ui.log(f"$ {shown}")
    full_env = None
    if env:
        full_env = dict(os.environ, **env)
    try:
        proc = subprocess.run(cmd, capture_output=capture, text=True, input=input,
                              env=full_env, timeout=timeout, cwd=cwd)
    except FileNotFoundError as e:
        if check:
            raise CommandError(f"{cmd[0]}: not found") from e
        return subprocess.CompletedProcess(cmd, 127, "", str(e))
    except subprocess.TimeoutExpired as e:
        if check:
            raise CommandError(f"{shown}: timed out") from e
        return subprocess.CompletedProcess(cmd, 124, "", "timed out")
    if capture and proc.stderr:
        ui.log(proc.stderr.rstrip())
    if check and proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise CommandError(f"{shown} failed ({proc.returncode})" + (f": {msg[-1]}" if msg else ""))
    return proc


def output(cmd: list[str], timeout: float = 30) -> str | None:
    """stdout of a query command, or None if it failed."""
    proc = run(cmd, timeout=timeout)
    return proc.stdout if proc.returncode == 0 else None


def http_get(url: str, *, timeout: float = 30, retries: int = 3, headers: dict | None = None) -> bytes:
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code != 429:
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise ConnectionError(f"{url}: {last}")


def http_json(url: str, **kw):
    return json.loads(http_get(url, **kw).decode("utf-8"))


def download(url: str, dest: Path, *, timeout: float = 120) -> Path:
    """Download to dest atomically (via a temporary file beside it)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = http_get(url, timeout=timeout)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return dest


def reachable(url: str, timeout: float = 10) -> bool:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True  # the host answered
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def write_text(path: Path, text: str, mode: int | None = None) -> None:
    """Write a file atomically, honouring dry-run."""
    write_bytes(path, text.encode("utf-8"), mode)


def write_bytes(path: Path, data: bytes, mode: int | None = None) -> None:
    """Write a file atomically, honouring dry-run."""
    ui.action(f"write {path}")
    if ui.dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def remove_tree(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    ui.action(f"remove {path}")
    if ui.dry_run:
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def tree_hash(root: Path) -> str:
    """A stable digest of every file under root, to tell if configs changed."""
    h = hashlib.sha256()
    if root.is_dir():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                h.update(str(p.relative_to(root)).encode())
                h.update(p.read_bytes())
    return h.hexdigest()


def read(path, default: str | None = None) -> str | None:
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeDecodeError):
        return default


def free_bytes(path: Path) -> int:
    while not path.exists():
        path = path.parent
    return shutil.disk_usage(path).free
