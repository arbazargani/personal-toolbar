# Architecture decisions

## IPC

The backend creates `$XDG_RUNTIME_DIR/modular-toolbar.sock`, a Unix-domain socket with mode `0600`. JSON request/response messages keep the protocol small and local. The native GTK settings application currently accesses profile CRUD through SQLite using parameterized statements; API keys are only read when needed for polling or replaced through the masked editor and are never sent to the extension.

## Module contract

Modules implement `ID`, `Start`, and `Stop`, and emit common `module.Status` values. The rotation engine consumes statuses rather than knowing the Avalai schema. A module can therefore provide arbitrary display text while retaining common lifecycle and error handling.

## Requirements not fully reliable cross-version

GNOME Shell panel internals and extension JavaScript module loading changed significantly in GNOME 45. A single extension source cannot be guaranteed unchanged across Ubuntu 22.04 (GNOME 42) and newer Ubuntu releases. Ship versioned extension entry points or port the imports per target release after testing. The backend and IPC protocol remain stable.

Animations are also subject to Shell frame scheduling and accessibility settings. The next stage will use `St.Label`/`Clutter` native actors, serialize transitions, freeze widths, and skip animation when reduced motion is enabled; it cannot guarantee identical frame timing on every compositor.
