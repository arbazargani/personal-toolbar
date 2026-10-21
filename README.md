# Modular Ubuntu Top-Bar Monitor

A Go backend and GNOME Shell extension for compact, live top-panel monitor data. The first module is `avalai_credit_info`.

## Architecture

```
Go backend (SQLite, polling, modules, IPC) <--0600 Unix socket JSON--> GNOME Shell extension (panel label + rotation/animation)
                                  \
                                   native GTK 4/libadwaita settings app
```

The extension is the only component that renders panel text; this is not a tray icon or floating window. The backend never exposes API keys over IPC and never logs them. SQLite is stored under `$XDG_CONFIG_HOME/modular-toolbar/toolbar.db` (normally `~/.config/...`), with the directory mode `0700`. The extension uses a GObject-registered `PanelMenu.Button` and asynchronous Gio socket I/O so GNOME Shell's main loop is never blocked by the backend.

### Structure

- `cmd/toolbar`: backend entry point
- `internal/config`: SQLite repository and validated persistence
- `internal/module`: module registration and common lifecycle/status contract
- `internal/ipc`: local socket protocol and restricted server
- `modules/avalai_credit_info`: typed API client and polling service
- `extension`: GNOME Shell panel integration
- `settings`: native GTK 4/libadwaita profile manager
- `systemd`: per-user autostart unit

## Install on Ubuntu

Dependencies: Go 1.22+, GNOME Shell, `make`, Python 3 with PyGObject, GTK 4, and libadwaita. The SQLite driver is pure Go (`modernc.org/sqlite`); first build requires Go module download access.

```sh
./start.sh
modular-toolbar-settings
```

Run it as your normal user. It uses `sudo` only when required Ubuntu packages are missing, then tests, builds, installs, and starts the app. It preserves saved profiles. Uninstall with `make uninstall`, then disable the extension if it remains enabled.

## Current stage and limitations

The native GTK settings application manages profile creation, editing, enable/disable state, and deletion. It uses standard GTK 4/libadwaita windows, preference rows, switches, password fields, confirmation dialogs, and toast messages. API keys are masked and never shown in the profile list. The extension currently uses a compact text label and error styling; it intentionally does not fall back to a tray icon or overlay window. After installation, create at least one enabled profile; without profiles the panel intentionally shows an inactive state.

The included extension targets the GNOME 45–50 ES-module API used by Ubuntu 24.04 and newer. Ubuntu 22.04/GNOME 42 requires a separate legacy-import extension entry point and is not currently supported by this extension file. Shell extension reload behavior also differs between Wayland and Xorg. Reduced-motion handling and exact digit animation require testing against the target Shell version.

## Manage profiles visually

Launch the profile manager with `modular-toolbar-settings`, choose `Manage Profiles…` from the top-bar indicator menu, or open `Modular Toolbar Settings` from the application launcher. The window uses GTK 4/libadwaita controls and supports adding, editing, enabling, disabling, and deleting profiles. API keys are entered in a masked field and remain hidden in the profile list; leave the key blank while editing to keep the existing one. The backend service restarts after saved profile changes.

## Diagnose a missing panel label

The extension logs its enable/disable lifecycle and IPC failures without logging profile data or API keys. Check the actual Shell exception rather than relying only on the extension state summary:

```sh
gnome-extensions info modular-toolbar@example.com
journalctl -b _COMM=gnome-shell --no-pager \
  | grep -i -E 'modular-toolbar|TypeError|ReferenceError|SyntaxError|Gio|PanelMenu'
```

Check the backend and its restricted socket separately:

```sh
systemctl --user status modular-toolbar.service
ls -l "$XDG_RUNTIME_DIR/modular-toolbar.sock"
journalctl --user -u modular-toolbar.service -n 100 --no-pager
```

The socket response contains status text and settings only; it never contains API keys. After changing extension files, run `./start.sh`, or disable and re-enable the extension. Under Wayland, `Alt+F2` then `r` is not available; log out and back in if GNOME Shell does not reload the new extension.

## Security notes

API keys are stored only in the local SQLite database and are never included in status messages. Error strings from the API are reduced to HTTP/status or transport errors before persistence. Use a user-owned database and do not run the service as root.
