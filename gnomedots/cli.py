"""knirby-gnomedots: install, update, inspect and remove the setup."""

import argparse
import getpass
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

from . import APP_NAME, BRANCH, MIN_SHELL, REPO, SUPPORTED_SHELL, __version__, hardware, ui, util, wallpapers
from .context import Context, Options
from .gnome import dconf
from .gnome import extensions as ext
from .modules import ALL, BY_NAME, menulogo
from .modules.command import copy_tree
from .paths import APP_DIR, BACKUP_DIR, CACHE_DIR, CONFIG_DIR, DATA_HOME, LAUNCHER, LOG_FILE, STATE_FILE
from .state import State
from .system import privilege, session
from .system.distro import FAMILY_NAMES

MIN_FREE = 500 * 1024 * 1024


# -- shared steps ----------------------------------------------------------

def make_context(args) -> Context:
    ui.assume_yes = getattr(args, "yes", False)
    ui.dry_run = getattr(args, "dry_run", False)
    ui.verbose = getattr(args, "verbose", False)
    opts = Options(assume_yes=ui.assume_yes, dry_run=ui.dry_run, force=getattr(args, "force", False),
                   skip=set(getattr(args, "skip", None) or []), only=set(getattr(args, "only", None) or []),
                   with_=set(getattr(args, "with_", None) or []))
    for name in opts.skip | opts.only | opts.with_:
        if name not in BY_NAME:
            raise SystemExit(f"error: no module called {name!r}; see `{APP_NAME} modules`")
    return Context(opts)


def preflight(ctx: Context, modules) -> bool:
    """Every check that should stop the run before anything changes."""
    ui.header("Checking this system")
    good = True
    if os.geteuid() == 0:
        ui.error("Run this as your normal user, not root; it asks for sudo when it needs it.")
        return False
    if not sys.platform.startswith("linux"):
        ui.error("This only works on Linux.")
        return False

    v = ctx.shell_version
    if not v:
        ui.error("GNOME Shell isn't installed. Install your distribution's GNOME desktop first.")
        return False
    if v[0] in SUPPORTED_SHELL:
        ui.ok(f"GNOME Shell {v[0]}.{v[1]}")
    elif v[0] > max(SUPPORTED_SHELL):
        ui.warn(f"GNOME Shell {v[0]}.{v[1]} is newer than this setup is tested with ({max(SUPPORTED_SHELL)}).")
        if not ctx.options.force and not ui.confirm("Continue anyway?", False):
            return False
    elif v[0] >= MIN_SHELL:
        ui.warn(f"GNOME Shell {v[0]}.{v[1]}: this setup is built for {max(SUPPORTED_SHELL)}; "
                "extensions without a build for your version are skipped.")
    else:
        ui.error(f"GNOME Shell {v[0]}.{v[1]} is too old; this setup needs GNOME {MIN_SHELL} or newer.")
        if not ctx.options.force:
            ui.info("Use --force to try anyway (extensions may be missing).")
            return False

    d = ctx.distro
    if d.supported:
        ui.ok(f"{d.describe()} - {FAMILY_NAMES[d.family]}")
    elif d.guessed:
        ui.warn(f"{d.describe()} isn't on the supported list, but it has {FAMILY_NAMES[d.guessed]}.")
        if ui.confirm(f"Use {FAMILY_NAMES[d.guessed]} for packages anyway?", False):
            ctx.allow_untested_pm = True
        else:
            ui.info("Packages will be skipped; everything else still applies.")
    else:
        ui.warn(f"{d.describe()} isn't supported (supported: {', '.join(FAMILY_NAMES.values())}).")
        ui.info("Packages will be skipped; fonts, themes and tools must already be there.")
        if not ui.confirm("Continue without installing packages?", False):
            return False
    if d.ostree:
        ui.warn("This is an image-based system; packages are skipped (layer them with rpm-ostree if needed).")

    wants = {m.name for m in modules}
    if "packages" in wants and ctx.backend is None and (d.supported or ctx.allow_untested_pm) and not d.ostree:
        ui.warn("No sudo, doas or run0 found, so packages can't be installed.")

    if any(m.needs_dconf for m in modules):
        if not session.has_session_bus():
            ui.error("No session bus: run this from a terminal inside your GNOME session.")
            good = False
        elif not session.in_gnome():
            ui.warn("This doesn't look like a GNOME session; settings still apply to GNOME.")
        if not dconf.available() and "packages" not in wants:
            ui.error("The dconf command is missing; install it or include the packages module.")
            good = False

    if any(m.needs_network for m in modules):
        for url in ("https://extensions.gnome.org", "https://github.com"):
            if not util.reachable(url):
                ui.error(f"Can't reach {url}; check the network connection.")
                good = False
        if good:
            ui.ok("Network reachable")

    free = util.free_bytes(DATA_HOME)
    if free < MIN_FREE:
        ui.error(f"Only {free // 2**20} MB free in {DATA_HOME}; at least {MIN_FREE // 2**20} MB needed.")
        good = False
    return good


def selected(ctx: Context):
    """The modules for this run; asks about opt-in addons nobody mentioned."""
    o = ctx.options
    if not o.only and not ui.assume_yes and sys.stdin.isatty():
        for m in ALL:
            if not m.default and m.name not in o.with_ | o.skip:
                if ui.confirm(f"Also set up the {m.title}? ({m.summary.removeprefix('optional: ')})", False):
                    o.with_.add(m.name)
    modules = [m for m in ALL if ctx.wants(m.name, m.default)]
    ctx.selected = {m.name for m in modules}
    return modules


def show_plan(ctx: Context, modules) -> None:
    for m in modules:
        ui.header(m.title)
        try:
            ui.bullet_list(m.plan(ctx))
        except Exception as e:
            ui.warn(f"couldn't work out the plan: {e}")


def run_modules(ctx: Context, modules, label: str | None) -> bool:
    """Apply modules in order, backing up the settings first under label
    (no backup when label is None)."""
    if not ui.dry_run and any(m.needs_root(ctx) for m in modules):
        ui.info("Some steps need root:")
        if not privilege.warm_up(privilege.prefix() or []):
            ui.error("Couldn't get root; nothing was changed.")
            ui.info("On Debian with a root password, your user can't use sudo yet; fix it once with")
            ui.info(f'  su -c "apt-get install -y sudo && usermod -aG sudo {getpass.getuser()}"')
            ui.info("then log out and back in, and rerun.")
            return False
    backed_up = ui.dry_run or label is None
    for m in modules:
        # Back up right before the first settings change: after packages,
        # which may be what installs dconf.
        if m.needs_dconf and not backed_up:
            folder = dconf.backup(label)
            if not folder:
                ui.error("Couldn't back up the current settings, so none were changed; rerunning is safe.")
                ctx.state.save()
                return False
            ui.ok(f"Settings backed up to {folder}")
            if not ctx.state["initial_backup"]:
                ctx.state["initial_backup"] = str(folder)
            backed_up = True
        ui.header(m.title)
        try:
            m.apply(ctx)
            ctx.state.add_unique("modules", m.name)
        except Exception as e:
            ui.error(f"{m.title}: {e}")
            ctx.failures.append(m.name)
            if m.name == "packages":
                ui.error("Stopping: later steps need these packages.")
                break
        ctx.state.save()
    return True


def finish(ctx: Context) -> None:
    ui.header("Done" if not ctx.failures else "Done, with problems")
    if ctx.failures:
        ui.warn("These steps had problems: " + ", ".join(ctx.failures))
        ui.info(f"Details are in {LOG_FILE}; rerunning is safe.")
    else:
        ui.ok("Everything applied")
    ui.info(f"`{APP_NAME} status` shows what's installed; `{APP_NAME} update` keeps it current.")


# -- commands --------------------------------------------------------------

def cmd_install(args) -> int:
    ctx = make_context(args)
    ui.open_log(LOG_FILE)
    ui.header(f"{APP_NAME} {__version__}")
    modules = selected(ctx)
    if not preflight(ctx, modules):
        return 1
    show_plan(ctx, modules)
    print()
    backup = ui.confirm_backup("Apply all of this?")
    if backup is None:
        ui.info("Nothing changed.")
        return 1
    if not backup and not ctx.state["initial_backup"] and any(m.needs_dconf for m in modules):
        ui.warn("Without a backup from before the first install, uninstall can't put your settings back.")
    if not run_modules(ctx, modules, "before-install" if backup else None):
        return 1
    if not ctx.state.installed:
        ctx.state.stamp("installed_at")
    ctx.state["config_hash"] = util.tree_hash(CONFIG_DIR)
    ctx.state.save()
    finish(ctx)
    if not ui.dry_run:
        session.offer_restart()
    return 0 if not ctx.failures else 2


def cmd_apply(args) -> int:
    args.only = args.modules
    args.skip = []
    args.with_ = []
    return cmd_install(args)


def cmd_update(args) -> int:
    ctx = make_context(args)
    ui.open_log(LOG_FILE)
    if not ctx.state.installed:
        ui.error(f"{APP_NAME} isn't installed here; run install.py from a clone first.")
        return 1
    ui.header(f"Updating {APP_NAME}")
    head = ext.github_head(REPO, BRANCH)
    if not head:
        ui.error(f"Can't reach github.com/{REPO}.")
        return 1
    current = ctx.state.get("commit")
    if head == current and not args.force:
        ui.ok(f"{APP_NAME} is up to date ({head[:8]})")
    elif args.check:
        ui.info(f"Update available: {(current or 'unknown')[:8]} -> {head[:8]}")
        return 0
    elif ui.confirm(f"Update {APP_NAME} to {head[:8]}?", True):
        ui.action(f"download github.com/{REPO} at {head[:8]}")
        if not ui.dry_run:
            data = util.http_get(f"https://codeload.github.com/{REPO}/tar.gz/{head}", timeout=120)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=CACHE_DIR) as tmp:
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
                    try:
                        tf.extractall(tmp, filter="data")
                    except TypeError:
                        tf.extractall(tmp)
                root = next(Path(tmp).iterdir())
                if not (root / "gnomedots" / "__init__.py").is_file():
                    ui.error("The download doesn't look like this tool; not updating.")
                    return 1
                copy_tree(root, APP_DIR)
            ctx.state["commit"] = head
            ctx.state.stamp("updated_at")
            ctx.state.save()
            ui.ok(f"{APP_NAME} updated to {head[:8]}")
            # Carry on with the new code.
            argv = [sys.executable, str(APP_DIR / "install.py"), "_post-update"]
            argv += [f for f, on in (("--yes", ui.assume_yes), ("--verbose", ui.verbose),
                                     ("--reapply", args.reapply)) if on]
            os.execv(sys.executable, argv)
    if args.check:
        return 0
    return post_update(ctx, args.reapply)


def cmd_post_update(args) -> int:
    ctx = make_context(args)
    ui.open_log(LOG_FILE)
    return post_update(ctx, args.reapply)


def cmd_wallpapers(args) -> int:
    ctx = make_context(args)
    s = wallpapers.Settings(ctx.themes_config["wallpaper"])
    if args.action == "sync":
        if args.quiet:
            ui.verbose = False
        if args.watch:
            wallpapers.watch(s)
        try:
            r = wallpapers.sync(s)
        except Exception as e:
            ui.error(f"Couldn't reach Bing: {e}")
            return 1
        if not args.quiet:
            ui.ok(f"{len(r['new'])} new picture(s)" + (f"; showing {r['today'].name}" if r["switched"] else ""))
            if r["removed"]:
                ui.ok(f"Trimmed {len(r['removed'])} old picture(s) to stay under {s.limit // 2**20} MB")
        return 0
    if args.action == "clean":
        files = wallpapers.images(s.folder)
        current = wallpapers.current_wallpaper()
        doomed = [p for p in files if args.all or p != current]
        if not doomed:
            ui.ok("Nothing to clean")
            return 0
        mb = sum(p.stat().st_size for p in doomed) / 2**20
        keep = "" if args.all or current not in files else " (the current wallpaper stays)"
        if not ui.confirm(f"Delete {len(doomed)} picture(s), {mb:.0f} MB, from {s.folder}{keep}?", False):
            return 1
        removed = wallpapers.clean(s, keep_current=not args.all)
        ui.ok(f"Deleted {len(removed)} picture(s); new ones keep arriving every day")
        return 0
    files = wallpapers.images(s.folder)
    total = wallpapers.size(s.folder)
    print(f"folder:   {s.folder}")
    print(f"pictures: {len(files)}, {total / 2**20:.1f} MB of {s.limit // 2**20} MB kept")
    print(f"newest:   {files[-1].name if files else 'none'}")
    print(f"showing:  {(wallpapers.current_wallpaper() or Path('none')).name}")
    print(f"market:   {s.market}, {s.resolution}")
    return 0


def post_update(ctx: Context, reapply: bool) -> int:
    changed = False
    ext_mod = BY_NAME["extensions"]
    ui.header("Extensions")
    ui.bullet_list(ext_mod.plan(ctx))
    if any(r["action"] in ("install", "update") for r in ctx.vars["_extensions"]):
        if ui.confirm("Install these extension updates?", True):
            ext_mod.apply(ctx)
            changed = True
    else:
        ui.ok("All extensions are up to date")

    # Hardware can change between runs (new GPU, new disk); re-detect quietly.
    if ext.find("monitor@astraext.github.io"):
        BY_NAME["sysmon"].apply(ctx)
    BY_NAME["command"].apply(ctx)
    # Recopy launchers from packages that changed, and rebuild the rounded
    # blur library, with build tools for the new libmutter, after a GNOME
    # upgrade.
    steps = ["app-icons"] if "app-icons" in ctx.state["modules"] else []
    if "rounded-blur" in ctx.state["modules"] and BY_NAME["rounded-blur"].needs_root(ctx):
        ctx.selected = {"rounded-blur"}
        steps += ["packages", "rounded-blur"] if ctx.backend else ["rounded-blur"]
    for name in steps:
        try:
            BY_NAME[name].apply(ctx)
        except Exception as e:
            ui.error(f"{BY_NAME[name].title}: {e}")
            ctx.failures.append(name)
    if "wallpaper" in ctx.state["modules"] and dconf.available():
        wallpapers.install_schedule()

    new_hash = util.tree_hash(CONFIG_DIR)
    if new_hash != ctx.state.get("config_hash"):
        ui.header("Configuration")
        ui.info("This version changes the desktop configuration.")
        backup = True if reapply else ui.confirm_backup("Re-apply it now?", False)
        if backup is not None:
            mods = [m for m in ALL if m.name not in ("packages", "extensions", "command")
                    and (m.default or m.name in ctx.state["modules"])]
            ctx.selected = {m.name for m in mods}
            if not run_modules(ctx, mods, "before-update" if backup else None):
                return 1
            ctx.state["config_hash"] = new_hash
            changed = True
        else:
            ui.info(f"Later: `{APP_NAME} apply settings` (or any module) re-applies it.")
    ctx.state.save()
    finish(ctx)
    if changed:
        session.offer_restart()
    return 0 if not ctx.failures else 2


def cmd_uninstall(args) -> int:
    ctx = make_context(args)
    ui.open_log(LOG_FILE)
    st = ctx.state
    ui.header(f"Uninstalling {APP_NAME}")
    ours = [u for u, r in st["extensions"].items() if not r.get("preexisting")]
    initial = st.get("initial_backup")
    restore = bool(initial) and Path(initial, "dconf.ini").is_file() and not args.keep_settings
    plan = [
        f"remove {len(ours)} extensions it installed (ones you had before stay)",
        f"remove downloaded themes: {', '.join(st['themes']) or 'none'}",
        "remove the gtk.css block, the Super+T shortcut, the Tux logo, the hourly wallpaper job "
        "and its launcher copies",
        "remove the file templates it added that you haven't changed",
        f"remove {LAUNCHER}, {APP_DIR} and the PATH lines it added",
    ]
    if restore:
        plan.insert(0, f"put back the settings it changed, from {Path(initial).name}")
    else:
        plan.insert(0, "keep the current settings" + ("" if initial else " (no pre-install backup found)"))
    if st.get("zsh"):
        plan.append("put back your previous .zshrc and remove the Oh My Zsh it installed")
    if st.get("rounded_blur"):
        plan.append("remove the GNOME Rounded Blur library it built")
    if st["packages_added"]:
        plan.append("offer to remove the packages it installed")
    ui.bullet_list(plan)
    backup = ui.confirm_backup("Uninstall?", False)
    if backup is None:
        ui.info("Nothing changed.")
        return 1
    if backup and dconf.available() and session.has_session_bus():
        folder = dconf.backup("before-uninstall")
        if folder:
            ui.ok(f"Current settings backed up to {folder}")
    steps = [
        ("extensions", lambda: BY_NAME["extensions"].remove(ctx)),
        ("wallpaper", lambda: BY_NAME["wallpaper"].remove(ctx)),
        ("zsh", lambda: BY_NAME["zsh"].remove(ctx)),
        ("settings", lambda: restore and dconf.restore(Path(initial), st["dconf_sections"], st["dconf_trees"])),
        ("keybindings", lambda: BY_NAME["keybindings"].remove(ctx)),
        ("themes", lambda: BY_NAME["themes"].remove(ctx)),
        ("menu-logo", lambda: BY_NAME["menu-logo"].remove(ctx)),
        ("gtk", lambda: BY_NAME["gtk"].remove(ctx)),
        ("app-icons", lambda: BY_NAME["app-icons"].remove(ctx)),
        ("templates", lambda: BY_NAME["templates"].remove(ctx)),
        ("rounded-blur", lambda: BY_NAME["rounded-blur"].remove(ctx)),
        ("packages", lambda: BY_NAME["packages"].remove(ctx)),
        ("command", lambda: BY_NAME["command"].remove(ctx)),
    ]
    for name, fn in steps:
        try:
            fn()
        except Exception as e:
            ui.error(f"{name}: {e}")
            ctx.failures.append(name)
    if not ui.dry_run:
        STATE_FILE.unlink(missing_ok=True)
        shutil.rmtree(CACHE_DIR, ignore_errors=True)
    ui.ok(f"{APP_NAME} is uninstalled")
    ui.info(f"Settings backups are kept in {BACKUP_DIR}.")
    if ctx.failures:
        ui.warn("Some steps had problems: " + ", ".join(ctx.failures))
    session.offer_restart("GNOME unloads removed extensions at the next login")
    return 0 if not ctx.failures else 2


def cmd_status(args) -> int:
    if args.log:
        try:
            print(LOG_FILE.read_text(), end="")
            return 0
        except OSError:
            ui.error("No log yet.")
            return 1
    ctx = make_context(args)
    st = ctx.state
    v = ctx.shell_version
    commit = (st.get("commit") or "")[:8]
    print(f"{APP_NAME} {__version__}" + (f" ({commit})" if commit else ""))
    print(f"  installed:   {st.get('installed_at') or 'no'}" + (f", updated {st['updated_at']}" if st.get("updated_at") else ""))
    print(f"  system:      {ctx.distro.describe()}")
    print(f"  packages:    {FAMILY_NAMES.get(ctx.distro.family or '', 'none')}")
    print(f"  GNOME Shell: {f'{v[0]}.{v[1]}' if v else 'not found'} ({session.session_type()})")
    print(f"  command:     {LAUNCHER if LAUNCHER.exists() else 'not installed'}")
    print(f"  backups:     {len(dconf.list_backups())} in {BACKUP_DIR}")
    folder = wallpapers.Settings(ctx.themes_config["wallpaper"]).folder
    print(f"  wallpapers:  {len(wallpapers.images(folder))} pictures, "
          f"{wallpapers.size(folder) / 2**20:.0f} MB in {folder}")
    print("\nExtensions:")
    on = set(ext.enabled())
    for e in ctx.extensions:
        meta = ext.metadata(e["uuid"])
        rec = st["extensions"].get(e["uuid"], {})
        version = rec.get("version") or (meta or {}).get("version")
        version = version[:8] if isinstance(version, str) else (f"v{version}" if version else "")
        mark = "on " if e["uuid"] in on else "off"
        state_text = f"{mark} {version}" if meta else "not installed"
        print(f"  {e['name']:<30} {state_text}")
    return 0


def cmd_version(args) -> int:
    st = State.load()
    commit = (st.get("commit") or "")[:8]
    print(f"{APP_NAME} {__version__}" + (f" ({commit})" if commit else ""))
    return 0


def cmd_detect(args) -> int:
    ctx = make_context(args)
    hw = hardware.summary()
    out = {
        "distro": ctx.distro.describe(),
        "package_manager": ctx.distro.family or ctx.distro.guessed,
        "gnome_shell": ".".join(map(str, ctx.shell_version or ())),
        "terminal": (ctx.terminal or {}).get("cmd"),
        "software_center": (ctx.software or {}).get("cmd"),
        "extensions_app": ctx.extensions_app,
        "menu_logo": menulogo.choose(ctx)[1],
        **{k: json.loads(v) if isinstance(v, str) and v.startswith("{") else v for k, v in hw.items()},
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_backup(args) -> int:
    make_context(args)
    folder = dconf.backup("manual")
    if not folder:
        return 1
    ui.ok(f"Backed up to {folder}")
    return 0


def cmd_backups(args) -> int:
    st = State.load()
    for b in dconf.list_backups():
        tag = "  (before first install)" if str(b) == st.get("initial_backup") else ""
        print(f"{b.name}{tag}")
    return 0


def cmd_restore(args) -> int:
    ctx = make_context(args)
    st = ctx.state
    if args.name:
        folder = BACKUP_DIR / args.name
    elif st.get("initial_backup"):
        folder = Path(st["initial_backup"])
    else:
        ui.error("No backup given and none recorded; see `backups`.")
        return 1
    if not (folder / "dconf.ini").is_file():
        ui.error(f"{folder} isn't a backup.")
        return 1
    if not st["dconf_sections"] and not st["dconf_trees"]:
        ui.error("Nothing recorded as changed, so there's nothing to restore.")
        return 1
    ui.info(f"This puts back every setting {APP_NAME} manages as it was in {folder.name}.")
    backup = ui.confirm_backup("Restore?", False)
    if backup is None:
        return 1
    if backup and not dconf.backup("before-restore"):
        return 1
    if dconf.restore(folder, st["dconf_sections"], st["dconf_trees"]):
        ui.ok("Restored")
        session.offer_restart("Some changes only show after logging in again")
        return 0
    return 2


def cmd_modules(args) -> int:
    for m in ALL:
        print(f"  {m.name:<12} {m.summary}")
    return 0


# -- argument parsing ------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-y", "--yes", action="store_true", help="answer yes to every question")
    common.add_argument("-n", "--dry-run", action="store_true", help="show what would change, change nothing")
    common.add_argument("-v", "--verbose", action="store_true", help="show every step")

    p = argparse.ArgumentParser(prog=APP_NAME, description="knirby's GNOME setup, in one command.")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")

    s = sub.add_parser("install", parents=[common], help="set everything up (safe to rerun)")
    s.add_argument("--skip", nargs="+", metavar="MODULE", default=[], help="leave out these modules")
    s.add_argument("--only", nargs="+", metavar="MODULE", default=[], help="run only these modules")
    s.add_argument("--with", dest="with_", nargs="+", metavar="ADDON", default=[],
                   help="include opt-in addons (zsh)")
    s.add_argument("--force", action="store_true", help="run on an untested GNOME version")
    s.set_defaults(func=cmd_install)

    s = sub.add_parser("apply", parents=[common], help="re-apply some modules")
    s.add_argument("modules", nargs="+", metavar="MODULE")
    s.add_argument("--force", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_apply)

    s = sub.add_parser("update", parents=[common], help="update this tool and the extensions from GitHub")
    s.add_argument("--check", action="store_true", help="only say whether an update exists")
    s.add_argument("--reapply", action="store_true", help="re-apply the configuration afterwards")
    s.add_argument("--force", action="store_true", help="reinstall even when up to date")
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("_post-update", parents=[common])
    s.add_argument("--reapply", action="store_true")
    s.set_defaults(func=cmd_post_update)

    s = sub.add_parser("uninstall", parents=[common], help="remove everything this tool added")
    s.add_argument("--keep-settings", action="store_true", help="don't restore the pre-install settings")
    s.set_defaults(func=cmd_uninstall)

    s = sub.add_parser("status", parents=[common], help="show what's installed")
    s.add_argument("--log", action="store_true", help="print the log of the last run")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("wallpapers", parents=[common], help="Bing wallpapers: status, sync or clean")
    s.add_argument("action", nargs="?", choices=["status", "sync", "clean"], default="status")
    s.add_argument("--all", action="store_true", help="clean: delete the current wallpaper too")
    s.add_argument("--quiet", action="store_true", help=argparse.SUPPRESS)
    s.add_argument("--watch", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_wallpapers)

    sub.add_parser("version", help="print the version").set_defaults(func=cmd_version)
    sub.add_parser("detect", parents=[common], help="show what was detected on this machine").set_defaults(func=cmd_detect)
    sub.add_parser("modules", help="list the setup modules").set_defaults(func=cmd_modules)
    sub.add_parser("backup", parents=[common], help="back up the current settings").set_defaults(func=cmd_backup)
    sub.add_parser("backups", help="list settings backups").set_defaults(func=cmd_backups)
    s = sub.add_parser("restore", parents=[common], help="restore managed settings from a backup")
    s.add_argument("name", nargs="?", help="backup folder name (default: the pre-install one)")
    s.set_defaults(func=cmd_restore)

    # Keep the help listing free of the internal command.
    sub._choices_actions = [a for a in sub._choices_actions if a.dest != "_post-update"]
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print()
        ui.warn("Interrupted. Rerunning is safe; settings backups are in " + str(BACKUP_DIR))
        return 130
