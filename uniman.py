#!/usr/bin/env python3

import os
import re
import subprocess
import sys
import threading
import signal


if hasattr(sys, "_MEIPASS"):
    ASSET_PATH = os.path.join(sys._MEIPASS, "logos")
else:
    ASSET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logos")


def detect_package_manager():
    if os.path.exists("/usr/bin/pacman"):
        return "pacman"
    if os.path.exists("/usr/bin/apt"):
        return "apt"
    if os.path.exists("/usr/bin/dnf"):
        return "dnf"
    if os.path.exists("/usr/sbin/pkg") or os.path.exists("/usr/bin/pkg"):
        return "pkg"
    return None


def signal_handler(sig, frame):
    print("\nInterrupt received. Shutting down Uniman...")
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


def dependency_install_cmd():
    pm = detect_package_manager()
    if pm == "pacman":
        pkgs = ["python-distro", "python-gobject", "python-cairo", "gtk4", "librsvg"]
        return ["pkexec", "pacman", "-S", "--noconfirm", "--needed"] + pkgs
    if pm == "apt":
        pkgs = ["python3-distro", "python3-gi", "python3-cairo", "gir1.2-gtk-4.0", "gir1.2-rsvg-2.0"]
        return ["pkexec", "apt", "install", "-y"] + pkgs
    if pm == "dnf":
        pkgs = ["python3-distro", "python3-gobject", "python3-cairo", "gtk4", "librsvg2"]
        return ["pkexec", "dnf", "install", "-y"] + pkgs
    if pm == "pkg":
        pkgs = ["py311-distro", "py311-gobject3", "py311-cairo", "gtk4", "librsvg2-rust"]
        return ["pkexec", "pkg", "install", "-y"] + pkgs
    return None


def ensure_runtime_dependencies():
    try:
        import distro as _distro_check  # noqa: F401
        import gi as _gi_check  # noqa: F401
        _gi_check.require_version("Gtk", "4.0")
        _gi_check.require_version("Rsvg", "2.0")
        from gi.repository import Gtk as _gtk_check, Rsvg as _rsvg_check  # noqa: F401
        import cairo as _cairo_check  # noqa: F401
        return
    except Exception:
        pass

    in_container = os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")
    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    has_pkexec = os.path.exists("/usr/bin/pkexec")
    if in_container or (not has_display) or (not has_pkexec):
        print(
            "Missing GUI dependencies (distro, PyGObject/GTK4, cairo, Rsvg).\n"
            "Auto-install is disabled because pkexec/polkit is unavailable in this environment.\n"
            "Please install the required packages using your system package manager, then rerun."
        )
        sys.exit(1)

    cmd = dependency_install_cmd()
    if not cmd:
        print("Unsupported package manager. Please install: distro, PyGObject, cairo, GTK4, and Rsvg bindings.")
        sys.exit(1)

    print("[*] Missing GUI dependencies. Attempting to install system packages...")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        print("Dependency installation failed or was cancelled.")
        sys.exit(1)

    os.execv(sys.executable, [sys.executable] + sys.argv)


def parse_package_arg():
    if len(sys.argv) >= 2:
        arg = sys.argv[1].strip()
        if arg in {"-h", "--help"}:
            print("Usage: python3 uniman.py <package-name>")
            print("Or run an executable named like: install-<package>")
            sys.exit(0)
        if arg:
            return arg

    exe_name = os.path.basename(sys.argv[0] or "").strip()
    match = re.match(r"^install-([A-Za-z0-9._+-]+?)(?:\.py)?$", exe_name)
    if match:
        return match.group(1)

    print(
        "No package name was provided.\n"
        "Run as: python3 uniman.py <package-name>\n"
        "Or rename the executable to: install-<package>"
    )
    sys.exit(1)


ensure_runtime_dependencies()

# Don't parse PACKAGE_NAME at import time - let main() handle it
PACKAGE_NAME = None

import distro
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Rsvg", "2.0")
from gi.repository import GLib, Gtk, Rsvg
import cairo


DISTRO_ICON_KEYS = {
    "arch": "archlinux",
    "manjaro": "manjaro",
    "endeavouros": "endeavouros",
    "ubuntu": "ubuntu",
    "debian": "debian",
    "mint": "linuxmint",
    "fedora": "fedora",
    "centos": "centos",
    "rhel": "redhat",
    "freebsd": "freebsd",
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_DIR = os.path.join(SCRIPT_DIR, "logos")

PROGRESS_MAP = [
    ("resolving dependencies", 0.10),
    ("looking for conflicting", 0.20),
    ("checking keys in keyring", 0.35),
    ("checking package integrity", 0.50),
    ("loading package files", 0.62),
    ("checking for file conflicts", 0.72),
    ("checking available disk", 0.82),
    ("processing package changes", 0.90),
    ("running post-transaction", 0.97),
    ("downloading", 0.35),
    ("installing", 0.75),
]


def get_package_info(package, backend_id, native_pm, backend_options):
    """Fetch real package information from the selected backend"""
    info = {
        "name": package,
        "description": "No description available",
        "version": "Unknown",
        "size": "Unknown",
        "homepage": "Unknown",
        "license": "Unknown",
        "maintainer": "Unknown"
    }
    
    if backend_id == "system":
        return get_system_package_info(package, native_pm)
    elif backend_id == "flatpak":
        return get_flatpak_package_info(package, backend_options)
    elif backend_id == "aur":
        return get_aur_package_info(package, backend_options)
    elif backend_id == "snap":
        return get_snap_package_info(package)
    
    return info


def get_system_package_info(package, native_pm):
    """Get package info from system package manager"""
    info = {"name": package, "description": "No description available", "version": "Unknown", "size": "Unknown", "homepage": "Unknown", "license": "Unknown", "maintainer": "Unknown"}
    
    try:
        if native_pm == "pacman":
            ok, output = run_query_command(["pacman", "-Si", package])
            if ok and output:
                for line in output.split('\n'):
                    if line.startswith("Name"):
                        info["name"] = line.split(":", 1)[1].strip()
                    elif line.startswith("Version"):
                        info["version"] = line.split(":", 1)[1].strip()
                    elif line.startswith("Description"):
                        info["description"] = line.split(":", 1)[1].strip()
                    elif "Installed Size" in line:
                        info["size"] = line.split(":", 1)[1].strip()
                    elif "URL" in line:
                        info["homepage"] = line.split(":", 1)[1].strip()
                    elif "License" in line:
                        info["license"] = line.split(":", 1)[1].strip()
            else:
                pass
                        
        elif native_pm == "apt":
            ok, output = run_query_command(["apt-cache", "show", package])
            if ok and output:
                for line in output.split('\n'):
                    if line.startswith("Package:"):
                        info["name"] = line.split(":", 1)[1].strip()
                    elif line.startswith("Version:"):
                        info["version"] = line.split(":", 1)[1].strip()
                    elif line.startswith("Description:"):
                        info["description"] = line.split(":", 1)[1].strip()
                    elif line.startswith("Homepage:"):
                        info["homepage"] = line.split(":", 1)[1].strip()
                    elif line.startswith("License:"):
                        info["license"] = line.split(":", 1)[1].strip()
            else:
                pass
                        
        elif native_pm == "dnf":
            ok, output = run_query_command(["dnf", "info", package])
            if ok and output:
                for line in output.split('\n'):
                    if "Name" in line and ":" in line:
                        info["name"] = line.split(":", 1)[1].strip()
                    elif "Version" in line and ":" in line:
                        info["version"] = line.split(":", 1)[1].strip()
                    elif "Description" in line and ":" in line:
                        info["description"] = line.split(":", 1)[1].strip()
                    elif "Size" in line and ":" in line:
                        info["size"] = line.split(":", 1)[1].strip()
                    elif "URL" in line and ":" in line:
                        info["homepage"] = line.split(":", 1)[1].strip()
                    elif "License" in line and ":" in line:
                        info["license"] = line.split(":", 1)[1].strip()
            else:
                pass
                        
        elif native_pm == "pkg":
            ok, output = run_query_command(["pkg", "info", package])
            if ok and output:
                for line in output.split('\n'):
                    if line.startswith(f"{package}-"):
                        parts = line.split()
                        if len(parts) >= 2:
                            info["name"] = parts[0]
                            info["version"] = parts[1].strip("()")
                    elif "Description:" in line:
                        info["description"] = line.split(":", 1)[1].strip()
                    elif "WWW:" in line:
                        info["homepage"] = line.split(":", 1)[1].strip()
            else:
                pass
                        
    except Exception as e:
        pass  # Use defaults if query fails
    
    return info


def get_flatpak_package_info(package, backend_options):
    """Get package info from Flatpak"""
    info = {"name": package, "description": "No description available", "version": "Unknown", "size": "Unknown", "homepage": "Unknown", "license": "Unknown", "maintainer": "Unknown"}
    
    try:
        app_id = None
        for item in backend_options:
            if item["id"] == "flatpak":
                app_id = item.get("app_id")
                break
        
        if app_id:
            # Try to get package info from flatpak remote-info
            ok, output = run_query_command(["flatpak", "remote-info", "flathub", app_id])
            if ok and output:
                for line in output.split('\n'):
                    if line.startswith("ID:"):
                        info["name"] = line.split(":", 1)[1].strip()
                    elif line.startswith("Ref:"):
                        version_part = line.split("/")[-1].strip()
                        info["version"] = version_part
                    elif line.startswith("Description:"):
                        info["description"] = line.split(":", 1)[1].strip()
                    elif line.startswith("Homepage:"):
                        info["homepage"] = line.split(":", 1)[1].strip()
                    elif line.startswith("License:"):
                        info["license"] = line.split(":", 1)[1].strip()
            else:
                # Fallback: try to get info from search
                ok, output = run_query_command(["flatpak", "search", "--columns=application,description,version", package])
                if ok and output:
                    lines = output.split('\n')
                    for line in lines:
                        if line.strip() and app_id in line:
                            parts = line.split('\t')
                            if len(parts) >= 3:
                                info["name"] = parts[0].strip()
                                info["description"] = parts[1].strip()
                                info["version"] = parts[2].strip()
                                break
        else:
            pass
    except Exception as e:
        pass
    
    return info


def get_aur_package_info(package, backend_options):
    """Get package info from AUR"""
    info = {"name": package, "description": "No description available", "version": "Unknown", "size": "Unknown", "homepage": "Unknown", "license": "Unknown", "maintainer": "Unknown"}
    
    try:
        helper = None
        for item in backend_options:
            if item["id"] == "aur":
                helper = item.get("helper")
                break
        
        if helper:
            ok, output = run_query_command([helper, "-Si", package])
            if ok and output:
                for line in output.split('\n'):
                    if line.startswith("Name"):
                        info["name"] = line.split(":", 1)[1].strip()
                    elif line.startswith("Version"):
                        info["version"] = line.split(":", 1)[1].strip()
                    elif line.startswith("Description"):
                        info["description"] = line.split(":", 1)[1].strip()
                    elif "Installed Size" in line:
                        info["size"] = line.split(":", 1)[1].strip()
                    elif line.startswith("URL"):
                        info["homepage"] = line.split(":", 1)[1].strip()
                    elif line.startswith("License"):
                        info["license"] = line.split(":", 1)[1].strip()
            else:
                pass
        else:
            pass
    except Exception as e:
        pass
    
    return info


def get_snap_package_info(package):
    """Get package info from Snap"""
    info = {"name": package, "description": "No description available", "version": "Unknown", "size": "Unknown", "homepage": "Unknown", "license": "Unknown", "maintainer": "Unknown"}
    
    try:
        ok, output = run_query_command(["snap", "info", package])
        if ok:
            for line in output.split('\n'):
                if "name:" in line:
                    info["name"] = line.split(":", 1)[1].strip()
                elif "summary:" in line:
                    info["description"] = line.split(":", 1)[1].strip()
                elif "version:" in line:
                    info["version"] = line.split(":", 1)[1].strip()
                elif "size:" in line:
                    info["size"] = line.split(":", 1)[1].strip()
                elif "homepage:" in line:
                    info["homepage"] = line.split(":", 1)[1].strip()
                elif "license:" in line:
                    info["license"] = line.split(":", 1)[1].strip()
    except Exception:
        pass
    
    return info


def command_exists(command):
    return subprocess.call(["/usr/bin/env", "bash", "-lc", f"command -v {command} >/dev/null 2>&1"]) == 0


def run_query_command(cmd):
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=20)
        return proc.returncode == 0, proc.stdout or ""
    except Exception:
        return False, ""


def is_valid_flatpak_app_id(app_id):
    return app_id.count(".") >= 2 and " " not in app_id and "\t" not in app_id


def detect_flatpak_app_id(package):
    ok, output = run_query_command(["flatpak", "search", "--columns=application", package])
    if not ok and not output:
        return None

    candidates = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower() in {"application id", "application"}:
            continue
        token = line.split()[0]
        if is_valid_flatpak_app_id(token):
            candidates.append(token)

    if not candidates:
        return None
    package_lower = package.lower()
    for app_id in candidates:
        if app_id.lower() == package_lower:
            return app_id
    for app_id in candidates:
        if package_lower in app_id.lower():
            return app_id
    return candidates[0]


def detect_distro():
    name = distro.id()
    if name in {"arch", "manjaro", "endeavouros"}:
        return "pacman", name
    if name in {"ubuntu", "debian", "mint"}:
        return "apt", name
    if name in {"fedora", "rhel", "centos"}:
        return "dnf", name
    if name in {"freebsd"}:
        return "pkg", name
    return "unknown", name


def get_backend_options(native_pm, package):
    system_supported = native_pm in {"pacman", "apt", "dnf", "pkg"}
    aur_helper = "yay" if command_exists("yay") else ("paru" if command_exists("paru") else None)
    system_reason = "No supported system package manager was detected."
    if system_supported:
        if native_pm == "pacman":
            system_supported, _ = run_query_command(["pacman", "-Si", package])
        elif native_pm == "apt":
            system_supported, out = run_query_command(["apt-cache", "show", package])
            system_supported = system_supported and ("Package:" in out)
        elif native_pm == "dnf":
            system_supported, _ = run_query_command(["dnf", "info", package])
        elif native_pm == "pkg":
            ok, out = run_query_command(["pkg", "search", "-n", package])
            system_supported = ok and any(line.startswith(package) for line in out.splitlines())
        if not system_supported:
            system_reason = "package not published on this backend"

    aur_supported = aur_helper is not None
    aur_reason = "yay or paru is required for AUR installs."
    if aur_supported:
        aur_supported, _ = run_query_command([aur_helper, "-Si", package])
        if not aur_supported:
            aur_reason = "package not published on this backend"

    flatpak_supported = command_exists("flatpak")
    flatpak_reason = "flatpak command was not found."
    flatpak_app_id = None
    if flatpak_supported:
        flatpak_app_id = detect_flatpak_app_id(package)
        flatpak_supported = flatpak_app_id is not None
        if not flatpak_supported:
            flatpak_reason = "package not published on this backend"

    # Determine the best recommendation for beginners
    recommended_backend = None
    if system_supported:
        recommended_backend = "system"
    elif flatpak_supported:
        recommended_backend = "flatpak"
    elif aur_supported:
        recommended_backend = "aur"
    elif command_exists("snap"):
        recommended_backend = "snap"

    # Create backend labels with recommendations
    def get_backend_label(backend_id, default_label):
        if backend_id == recommended_backend:
            if backend_id == "system":
                return "System repository (recommended for beginners)"
            elif backend_id == "flatpak":
                return "Flatpak (recommended for beginners)"
            elif backend_id == "aur":
                return "AUR (recommended for beginners)"
            elif backend_id == "snap":
                return "Snap (recommended for beginners)"
        return default_label

    options = [
        {
            "id": "system",
            "label": get_backend_label("system", "System repository"),
            "desc": f"Install from your distro's default repositories ({native_pm}).",
            "supported": system_supported,
            "reason": system_reason,
        },
        {
            "id": "flatpak",
            "label": get_backend_label("flatpak", "Flatpak"),
            "desc": "Install as a sandboxed Flatpak application from Flathub.",
            "supported": flatpak_supported,
            "reason": flatpak_reason,
            "app_id": flatpak_app_id,
        },
        {
            "id": "aur",
            "label": get_backend_label("aur", "AUR"),
            "desc": "Install from the Arch User Repository using yay/paru.",
            "supported": aur_supported,
            "reason": aur_reason,
            "helper": aur_helper,
        },
        {
            "id": "snap",
            "label": get_backend_label("snap", "Snap"),
            "desc": "Install as a confined Snap package.",
            "supported": command_exists("snap"),
            "reason": "snap command was not found.",
        },
    ]
    return options


def get_install_plan(package, backend_id, native_pm, backend_options):
    if backend_id == "system":
        if native_pm == "pacman":
            return {"cmd": ["pacman", "-S", "--noconfirm", "--needed", package], "needs_sudo": True}
        if native_pm == "apt":
            return {"cmd": ["apt-get", "install", "-y", package], "needs_sudo": True}
        if native_pm == "dnf":
            return {"cmd": ["dnf", "install", "-y", package], "needs_sudo": True}
        if native_pm == "pkg":
            return {"cmd": ["pkg", "install", "-y", package], "needs_sudo": True}
        return None
    if backend_id == "flatpak":
        app_id = None
        for item in backend_options:
            if item["id"] == "flatpak":
                app_id = item.get("app_id")
                break
        if app_id:
            return {"cmd": ["flatpak", "install", "-y", "flathub", app_id], "needs_sudo": False}
        return None
    if backend_id == "snap":
        return {"cmd": ["snap", "install", package], "needs_sudo": True}
    if backend_id == "aur":
        helper = None
        for item in backend_options:
            if item["id"] == "aur":
                helper = item.get("helper")
                break
        if helper:
            # AUR helpers need sudo for installation, even though they handle it internally
            return {"cmd": [helper, "-S", "--noconfirm", "--needed", package], "needs_sudo": True}
    return None


def ask_sudo_password(parent, backend_name=None):
    dialog = Gtk.Dialog(title="Authentication Required", transient_for=parent, modal=True)
    dialog.set_default_size(420, -1)
    dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
    ok_btn = dialog.add_button("Authenticate", Gtk.ResponseType.OK)
    ok_btn.add_css_class("suggested-action")

    content = dialog.get_content_area()
    content.set_spacing(10)
    content.set_margin_top(16)
    content.set_margin_bottom(8)
    content.set_margin_start(16)
    content.set_margin_end(16)

    if backend_name:
        label = Gtk.Label(label=f"Enter your sudo password to install from {backend_name}:")
    else:
        label = Gtk.Label(label="Enter your sudo password to continue installation:")
    label.set_xalign(0)

    entry = Gtk.PasswordEntry()
    entry.set_show_peek_icon(True)
    dialog.set_default_response(Gtk.ResponseType.OK)
    
    def on_entry_activate(widget):
        dialog.response(Gtk.ResponseType.OK)
    
    entry.connect("activate", on_entry_activate)

    content.append(label)
    content.append(entry)

    loop = GLib.MainLoop()
    result = {"response": Gtk.ResponseType.CANCEL}

    def on_response(_dialog, response_id):
        result["response"] = response_id
        loop.quit()

    dialog.connect("response", on_response)
    dialog.present()
    entry.grab_focus()
    loop.run()

    password = entry.get_text() if result["response"] == Gtk.ResponseType.OK else None
    dialog.destroy()
    return password


def fetch_distro_logo(distro_id):
    path = os.path.join(LOGO_DIR, f"{distro_id}.svg")
    return path if os.path.isfile(path) else None


def append_output(textview, text):
    buf = textview.get_buffer()
    end = buf.get_end_iter()
    buf.insert(end, text)
    # Only scroll if we're not getting too much output (prevents UI lag)
    if len(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)) < 50000:
        textview.scroll_to_iter(buf.get_end_iter(), 0, False, 0, 0)


def clear_window(win):
    if win.get_child():
        win.set_child(None)


def make_box():
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
    box.set_margin_top(32)
    box.set_margin_bottom(32)
    box.set_margin_start(32)
    box.set_margin_end(32)
    return box


def create_context():
    native_pm, distro_id = detect_distro()
    options = get_backend_options(native_pm, PACKAGE_NAME)
    selected = "system" if options[0]["supported"] else next((o["id"] for o in options if o["supported"]), "system")
    return {
        "package": PACKAGE_NAME,
        "native_pm": native_pm,
        "distro_id": distro_id,
        "backend_options": options,
        "selected_backend": selected,
    }


def screen1(win, ctx):
    clear_window(win)
    box = make_box()
    logo_area = Gtk.DrawingArea()
    logo_area.set_size_request(80, 80)
    logo_path = fetch_distro_logo(ctx["distro_id"])

    def on_draw(_area, cr, w, h):
        if logo_path:
            try:
                handle = Rsvg.Handle.new_from_file(logo_path)
                # FIX: set attributes individually, not as keyword args
                vp = Rsvg.Rectangle()
                vp.x = 0
                vp.y = 0
                vp.width = w
                vp.height = h
                handle.render_document(cr, vp)
                return
            except Exception:
                pass
        cr.set_source_rgb(0.4, 0.4, 0.8)
        cr.arc(w / 2, h / 2, min(w, h) / 2 - 4, 0, 2 * 3.14159)
        cr.fill()

    logo_area.set_draw_func(on_draw)

    title = Gtk.Label()
    title.set_markup("<span size='18000' weight='bold'>Welcome to Uniman</span>")
    title.set_xalign(0.5)

    desc = Gtk.Label()
    desc.set_markup(
        f"Detected system: <b>{distro.name()}</b>\n\n"
        f"Uniman will help you install <b>{ctx['package']}</b> safely."
    )
    desc.set_xalign(0.5)
    desc.set_justify(Gtk.Justification.CENTER)

    spacer = Gtk.Box()
    spacer.set_vexpand(True)

    btn = Gtk.Button(label="Continue")
    btn.set_size_request(-1, 44)
    btn.add_css_class("suggested-action")
    
    def on_continue_clicked(widget):
        screen2(win, ctx)
    
    btn.connect("clicked", on_continue_clicked)

    box.append(logo_area)
    box.append(title)
    box.append(Gtk.Separator())
    box.append(desc)
    box.append(spacer)
    box.append(btn)
    win.set_child(box)


def screen2(win, ctx):
    clear_window(win)
    box = make_box()
    title = Gtk.Label()
    title.set_markup(f"<span size='18000' weight='bold'>Install details for {ctx['package']}</span>")
    title.set_xalign(0)

    def row(icon, text):
        h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        h.append(Gtk.Label(label=icon))
        lbl = Gtk.Label(label=text)
        lbl.set_xalign(0)
        h.append(lbl)
        return h

    # Get real package information
    package_info = get_package_info(ctx['package'], ctx['selected_backend'], ctx['native_pm'], ctx['backend_options'])
    
    spacer = Gtk.Box()
    spacer.set_vexpand(True)

    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    back = Gtk.Button(label="← Back")
    next_btn = Gtk.Button(label="Next →")
    next_btn.add_css_class("suggested-action")
    next_btn.set_hexpand(True)
    
    def on_back_clicked(widget):
        screen1(win, ctx)
    
    def on_next_clicked(widget):
        screen_backend(win, ctx)
    
    back.connect("clicked", on_back_clicked)
    next_btn.connect("clicked", on_next_clicked)
    
    btn_box.append(back)
    btn_box.append(next_btn)

    box.append(title)
    box.append(Gtk.Separator())
    box.append(row("📦", f"Package: {package_info['name']}"))
    box.append(row("📝", f"Version: {package_info['version']}"))
    box.append(row("📄", f"Description: {package_info['description'][:80]}{'...' if len(package_info['description']) > 80 else ''}"))
    box.append(row("💾", f"Size: {package_info['size']}"))
    box.append(row("🏠", f"Homepage: {package_info['homepage'][:60]}{'...' if len(package_info['homepage']) > 60 else ''}"))
    box.append(row("🐧", f"Distro: {distro.name()}"))
    box.append(row("🔒", "You review and confirm before install starts."))
    box.append(row("🧭", "Next step: choose install source/backend."))
    box.append(spacer)
    box.append(btn_box)
    win.set_child(box)


def screen_backend(win, ctx):
    clear_window(win)
    box = make_box()

    title = Gtk.Label()
    title.set_markup("<span size='18000' weight='bold'>Where do you want to install this from?</span>")
    title.set_xalign(0)

    # Determine the recommended backend for beginners
    recommended_backend = None
    for option in ctx["backend_options"]:
        if option["supported"]:
            recommended_backend = option["id"]
            break
    
    # Create dynamic hint text
    if recommended_backend:
        if recommended_backend == "system":
            hint_text = "System repository is recommended for most beginners."
        elif recommended_backend == "flatpak":
            hint_text = "Flatpak is recommended for beginners (sandboxed and easy to manage)."
        elif recommended_backend == "aur":
            hint_text = "AUR is recommended for beginners (community-maintained packages)."
        elif recommended_backend == "snap":
            hint_text = "Snap is recommended for beginners (auto-updating and confined)."
        else:
            hint_text = "Choose the best option for beginners."
    else:
        hint_text = "No suitable installation backend found."
    
    hint = Gtk.Label(label=hint_text)
    hint.set_xalign(0)

    ctx.setdefault("beginner_auto_select", True)
    ctx.setdefault("manual_selected_backend", ctx.get("selected_backend"))

    auto_checkbox = Gtk.CheckButton.new_with_label("Choose the best option for beginners (recommended)")
    auto_checkbox.set_active(bool(ctx["beginner_auto_select"]))

    group = []
    radios = []
    for option in ctx["backend_options"]:
        suffix = "" if option["supported"] else f" (Unavailable: {option['reason']})"
        btn = Gtk.CheckButton.new_with_label(option["label"] + suffix)
        if group:
            btn.set_group(group[0])
        group.append(btn)
        btn.set_sensitive(option["supported"])
        if option["id"] == ctx["selected_backend"] and option["supported"]:
            btn.set_active(True)
        desc = Gtk.Label(label=option["desc"])
        desc.set_xalign(0)
        desc.add_css_class("dim-label")
        radios.append((btn, option["id"]))
        box.append(btn)
        box.append(desc)

    def first_supported_backend():
        for option in ctx["backend_options"]:
            if option["supported"]:
                return option["id"]
        return ctx.get("selected_backend")

    def apply_backend_mode():
        auto_mode = auto_checkbox.get_active()
        ctx["beginner_auto_select"] = auto_mode

        if auto_mode:
            for rb, option_id in radios:
                if rb.get_active():
                    ctx["manual_selected_backend"] = option_id
                    break
            ctx["selected_backend"] = first_supported_backend()
        else:
            manual = ctx.get("manual_selected_backend")
            if manual:
                for option in ctx["backend_options"]:
                    if option["id"] == manual and option["supported"]:
                        ctx["selected_backend"] = manual
                        break

        for rb, option_id in radios:
            is_supported = any(opt["id"] == option_id and opt["supported"] for opt in ctx["backend_options"])
            if auto_mode:
                rb.set_sensitive(False)
            else:
                rb.set_sensitive(is_supported)
            rb.set_active(option_id == ctx["selected_backend"])

    def on_checkbox_toggled(widget):
        apply_backend_mode()
    
    auto_checkbox.connect("toggled", on_checkbox_toggled)
    apply_backend_mode()

    spacer = Gtk.Box()
    spacer.set_vexpand(True)
    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    back = Gtk.Button(label="← Back")
    next_btn = Gtk.Button(label="Next →")
    next_btn.add_css_class("suggested-action")
    next_btn.set_hexpand(True)

    def go_next(_b):
        if not auto_checkbox.get_active():
            for rb, option_id in radios:
                if rb.get_active():
                    ctx["selected_backend"] = option_id
                    ctx["manual_selected_backend"] = option_id
                    break
        screen3(win, ctx)

    def on_back_clicked(widget):
        screen2(win, ctx)

    back.connect("clicked", on_back_clicked)
    next_btn.connect("clicked", go_next)
    btn_box.append(back)
    btn_box.append(next_btn)

    box.append(title)
    box.append(Gtk.Separator())
    box.append(hint)
    box.append(auto_checkbox)
    box.append(spacer)
    box.append(btn_box)
    win.set_child(box)


def screen3(win, ctx):
    clear_window(win)
    box = make_box()
    title = Gtk.Label()
    title.set_markup("<span size='18000' weight='bold'>Compatibility Check</span>")
    title.set_xalign(0)

    plan = get_install_plan(ctx["package"], ctx["selected_backend"], ctx["native_pm"], ctx["backend_options"])
    if plan:
        cmd_preview = " ".join(plan["cmd"])
        compat_text = (
            "✅ Your setup is ready.\n\n"
            f"🐧 Distro: <b>{distro.name()}</b>\n"
            f"📦 Package: <b>{ctx['package']}</b>\n"
            f"🧰 Source: <b>{ctx['selected_backend']}</b>"
        )
        
        # Create command expander (hidden by default)
        cmd_expander = Gtk.Expander(label="Command to run:")
        cmd_expander.set_expanded(False)  # Hidden by default
        cmd_label = Gtk.Label()
        cmd_label.set_markup(f"<tt>{cmd_preview}</tt>")
        cmd_label.set_xalign(0)
        cmd_label.set_selectable(True)
        cmd_expander.set_child(cmd_label)
    else:
        compat_text = (
            "❌ This source is not available on your system.\n\n"
            "Go back and pick another source."
        )
        cmd_expander = None

    compat = Gtk.Label()
    compat.set_markup(compat_text)
    compat.set_xalign(0)
    compat.set_justify(Gtk.Justification.LEFT)

    spacer = Gtk.Box()
    spacer.set_vexpand(True)
    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    back = Gtk.Button(label="← Back")
    install = Gtk.Button(label="Install Now")
    install.add_css_class("suggested-action")
    install.set_hexpand(True)
    install.set_sensitive(plan is not None)
    def on_back_clicked(widget):
        screen_backend(win, ctx)
    
    def on_install_clicked(widget):
        screen4(win, ctx, plan)
    
    back.connect("clicked", on_back_clicked)
    install.connect("clicked", on_install_clicked)
    btn_box.append(back)
    btn_box.append(install)

    box.append(title)
    box.append(Gtk.Separator())
    box.append(compat)
    if cmd_expander:
        box.append(cmd_expander)
    box.append(spacer)
    box.append(btn_box)
    win.set_child(box)


def screen4(win, ctx, plan):
    clear_window(win)
    box = make_box()

    title = Gtk.Label()
    title.set_markup(f"<span size='18000' weight='bold'>Installing {ctx['package']}...</span>")
    title.set_xalign(0)

    pct_label = Gtk.Label()
    pct_label.set_markup("<b>Percentage Complete: 0%</b>")
    pct_label.set_xalign(0)

    progress = Gtk.ProgressBar()
    progress.set_fraction(0.0)

    status = Gtk.Label(label="Starting installation...")
    status.set_xalign(0)

    expander = Gtk.Expander(label="Show terminal output")
    scroll = Gtk.ScrolledWindow()
    scroll.set_min_content_height(180)
    scroll.set_vexpand(True)
    textview = Gtk.TextView()
    textview.set_editable(False)
    textview.set_monospace(True)
    textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    
    # Add CSS for better terminal appearance
    css_provider = Gtk.CssProvider()
    css_provider.load_from_data(b"""
        textview {
            background-color: #1e1e1e;
            color: #00ff00;
            font-family: monospace;
            font-size: 11px;
            padding: 8px;
            border: 1px solid #333;
        }
        textview text {
            background-color: #1e1e1e;
            color: #00ff00;
        }
        scrolledwindow {
            border: 1px solid #444;
        }
    """)
    textview.get_style_context().add_provider(
        css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    
    scroll.set_child(textview)
    expander.set_child(scroll)

    box.append(title)
    box.append(Gtk.Separator())
    box.append(pct_label)
    box.append(progress)
    box.append(status)
    box.append(expander)
    win.set_child(box)

    run_cmd = list(plan["cmd"])
    sudo_password = None
    if plan["needs_sudo"]:
        # Get backend name for better user context
        backend_name = ctx.get("selected_backend", "system")
        if backend_name == "system":
            backend_display = "system repository"
        elif backend_name == "aur":
            backend_display = "AUR"
        elif backend_name == "flatpak":
            backend_display = "Flatpak"
        elif backend_name == "snap":
            backend_display = "Snap"
        else:
            backend_display = backend_name
        
        sudo_password = ask_sudo_password(win, backend_display)
        if not sudo_password:
            status.set_markup("<span color='red' weight='bold'>❌ Installation cancelled</span>")
            return
        run_cmd = ["sudo", "-S"] + run_cmd
        status.set_text("Authenticating with sudo...")

    def set_progress(frac, status_text):
        progress.set_fraction(frac)
        pct_label.set_markup(f"<b>Percentage Complete: {int(frac*100)}%</b>")
        status.set_text(status_text)

    def task():
        GLib.idle_add(append_output, textview, "$ " + " ".join(run_cmd) + "\n")
        process = subprocess.Popen(
            run_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        if sudo_password and process.stdin is not None:
            try:
                process.stdin.write(sudo_password + "\n")
                process.stdin.flush()
            except Exception:
                pass
            try:
                process.stdin.close()
            except Exception:
                pass

        # Batch output processing to reduce UI lag
        output_buffer = []
        last_update_time = 0
        
        if process.stdout is not None:
            for line in process.stdout:
                output_buffer.append(line)
                current_time = GLib.get_monotonic_time()
                
                # Update UI every 100ms or when buffer gets large
                if (current_time - last_update_time > 100000) or len(output_buffer) > 10:
                    batch_text = ''.join(output_buffer)
                    GLib.idle_add(append_output, textview, batch_text)
                    
                    # Check for progress keywords in the batch
                    for output_line in output_buffer:
                        lower = output_line.lower().strip()
                        for keyword, frac in PROGRESS_MAP:
                            if keyword in lower:
                                GLib.idle_add(set_progress, frac, None, output_line.strip())
                                break
                    
                    output_buffer.clear()
                    last_update_time = current_time
        
        # Flush any remaining output
        if output_buffer:
            batch_text = ''.join(output_buffer)
            GLib.idle_add(append_output, textview, batch_text)
            output_buffer.clear()

        process.wait()
        if process.returncode == 0:
            GLib.idle_add(set_progress, 1.0, "✅ Done!")
            GLib.idle_add(
                status.set_markup,
                f"<span color='#00cc00' weight='bold'>✅ {ctx['package']} installed successfully!</span>",
            )
            # Show finish screen immediately without delay
            def show_finish_idle():
                show_finish(win, ctx)
                return False  # Don't repeat
            GLib.idle_add(show_finish_idle)
        else:
            GLib.idle_add(status.set_markup, "<span color='red' weight='bold'>❌ Installation failed</span>")
            GLib.idle_add(expander.set_expanded, True)

    threading.Thread(target=task, daemon=True).start()


def show_finish(win, ctx):
    clear_window(win)
    box = make_box()

    title = Gtk.Label()
    title.set_markup("<span size='18000' weight='bold'>Installation Complete</span>")
    title.set_xalign(0.5)

    msg = Gtk.Label()
    msg.set_markup(
        f"✅ <b>{ctx['package']}</b> has been installed.\n\n"
        f"Try running <tt>{ctx['package']} --help</tt> in your terminal."
    )
    msg.set_xalign(0.5)
    msg.set_justify(Gtk.Justification.CENTER)

    spacer = Gtk.Box()
    spacer.set_vexpand(True)
    btn = Gtk.Button(label="Finish")
    btn.set_size_request(-1, 44)
    btn.add_css_class("suggested-action")
    
    def on_finish_clicked(widget):
        win.close()
    
    btn.connect("clicked", on_finish_clicked)

    box.append(title)
    box.append(Gtk.Separator())
    box.append(msg)
    box.append(spacer)
    box.append(btn)
    win.set_child(box)


def on_activate(app):
    win = Gtk.ApplicationWindow(application=app)
    win.set_title("Uniman Package Manager")
    win.set_default_size(560, 460)
    win.set_resizable(False)
    ctx = create_context()
    screen1(win, ctx)
    win.present()
    
    # Handle window close to properly quit the application
    def on_window_close(widget):
        app.quit()
    
    win.connect("close-request", on_window_close)
    
    def on_shutdown(widget):
        print("GTK application shutting down...")
    
    app.connect("shutdown", on_shutdown)


def main(package_name=None):
    global PACKAGE_NAME
    if package_name:
        PACKAGE_NAME = package_name
    else:
        # Only parse arguments if no package name was explicitly provided
        PACKAGE_NAME = parse_package_arg()
    
    app = Gtk.Application(application_id="com.uniman.universal")
    app.connect("activate", on_activate)
    
    # Run the app and return when it's done
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    main()
