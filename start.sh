#!/usr/bin/env bash
set -Eeuo pipefail

# Install dependencies when needed, build/install the app, and start it.
# The user's SQLite database is intentionally preserved.

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
EXTENSION_UUID="modular-toolbar@example.com"
SERVICE_NAME="modular-toolbar.service"
SETTINGS_APP_PATH="${HOME}/.local/bin/modular-toolbar-settings"
DATABASE_PATH="${XDG_CONFIG_HOME:-${HOME}/.config}/modular-toolbar/toolbar.db"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/modular-toolbar-${UID}}"
SOCKET_PATH="${RUNTIME_DIR}/modular-toolbar.sock"

APT_PACKAGES=(
    ca-certificates
    golang-go
    make
    gnome-shell
    sqlite3
    python3
    python3-gi
    gir1.2-gtk-4.0
    gir1.2-adw-1
)

log() {
    printf '\n==> %s\n' "$*"
}

fail() {
    printf '\nERROR: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

install_missing_dependencies() {
    require_command dpkg-query
    local package
    local -a missing_packages=()

    for package in "${APT_PACKAGES[@]}"; do
        if ! dpkg-query -W -f='${Status}' "${package}" 2>/dev/null \
            | grep -q '^install ok installed$'; then
            missing_packages+=("${package}")
        fi
    done

    if ((${#missing_packages[@]} == 0)); then
        log "All required Ubuntu packages are already installed"
        return
    fi

    require_command sudo
    require_command apt-get
    log "Installing missing Ubuntu dependencies: ${missing_packages[*]}"
    sudo apt-get update
    sudo apt-get install --yes "${missing_packages[@]}"
}

report_profiles() {
    local valid_count=0
    local enabled_count=0
    local invalid_count=0
    local rows=""

    if [[ ! -f "${DATABASE_PATH}" ]]; then
        printf 'Database does not exist yet: %s\n' "${DATABASE_PATH}"
        printf 'VALID_PROFILE_COUNT=0\n'
        return 0
    fi

    rows="$(sqlite3 -separator $'\t' "${DATABASE_PATH}" \
        "SELECT id, name, enabled, module_id, CASE WHEN trim(api_key) <> '' THEN 1 ELSE 0 END FROM profiles ORDER BY name;" \
        2>/dev/null || true)"

    if [[ -z "${rows}" ]]; then
        printf 'No profiles are stored in the database.\n'
        printf 'VALID_PROFILE_COUNT=0\n'
        return 0
    fi

    printf 'Stored profiles (API keys hidden):\n'
    while IFS=$'\t' read -r id name enabled module_id has_key; do
        [[ -n "${id}" ]] || continue
        if [[ "${enabled}" == "1" ]]; then
            enabled_count=$((enabled_count + 1))
        fi

        if [[ "${enabled}" == "1" && "${module_id}" == "avalai_credit_info" && "${has_key}" == "1" && -n "${name}" ]]; then
            printf '  [VALID]   %s (%s)\n' "${name}" "${id}"
            valid_count=$((valid_count + 1))
        else
            printf '  [INVALID] %s (%s) — must be enabled, use module avalai_credit_info, have a name, and have an API key\n' \
                "${name:-unnamed}" "${id}"
            invalid_count=$((invalid_count + 1))
        fi
    done <<< "${rows}"

    printf 'Profile summary: %d valid, %d enabled, %d invalid\n' \
        "${valid_count}" "${enabled_count}" "${invalid_count}"
    printf 'VALID_PROFILE_COUNT=%s\n' "${valid_count}"
}

[[ "${EUID}" -ne 0 ]] || fail "Run this script as your normal user, not with sudo. It uses sudo only when installing Ubuntu packages."

install_missing_dependencies
require_command go
require_command make
require_command systemctl
require_command sqlite3
require_command install

cd -- "${PROJECT_DIR}"

log "Preserving the existing database"
if [[ -f "${DATABASE_PATH}" ]]; then
    printf 'Keeping existing database: %s\n' "${DATABASE_PATH}"
else
    printf 'A new database will be created by the backend at: %s\n' "${DATABASE_PATH}"
fi

log "Downloading Go dependencies"
go mod download

log "Running project tests"
make test

log "Disabling the current GNOME extension before updating it"
if command -v gnome-extensions >/dev/null 2>&1; then
    gnome-extensions disable "${EXTENSION_UUID}" >/dev/null 2>&1 || true
fi

log "Building, installing, and starting the user service"
# make install replaces the application files and service but leaves the DB intact.
make install

INSTALLED_EXTENSION_DIR="${HOME}/.local/share/gnome-shell/extensions/${EXTENSION_UUID}"
INSTALLED_METADATA="${INSTALLED_EXTENSION_DIR}/metadata.json"
INSTALLED_EXTENSION="${INSTALLED_EXTENSION_DIR}/extension.js"
[[ -f "${INSTALLED_METADATA}" ]] || fail "Installed extension metadata is missing: ${INSTALLED_METADATA}"
[[ -f "${INSTALLED_EXTENSION}" ]] || fail "Installed extension source is missing: ${INSTALLED_EXTENSION}"
grep -q '"50"' "${INSTALLED_METADATA}" \
    || fail "Installed extension metadata does not declare GNOME 50 support: ${INSTALLED_METADATA}"
cmp -s extension/extension.js "${INSTALLED_EXTENSION}" \
    || fail "Installed extension source is stale: ${INSTALLED_EXTENSION}"
cmp -s extension/metadata.json "${INSTALLED_METADATA}" \
    || fail "Installed extension metadata is stale: ${INSTALLED_METADATA}"
[[ -x "${SETTINGS_APP_PATH}" ]] || fail "Settings application is missing: ${SETTINGS_APP_PATH}"

log "Checking saved profiles"
profile_report="$(report_profiles)"
printf '%s\n' "${profile_report}" | sed '/^VALID_PROFILE_COUNT=/d'
valid_profile_count="$(printf '%s\n' "${profile_report}" | sed -n 's/^VALID_PROFILE_COUNT=//p')"

if [[ "${valid_profile_count}" == "0" ]]; then
    printf 'No valid enabled Avalai profile exists. The top bar will remain inactive until one is added.\n'
    if [[ -t 0 ]]; then
        read -r -p 'Create a profile now? [Y/n] ' answer
        if [[ -z "${answer}" || "${answer}" =~ ^[Yy]$ ]]; then
            "${PROJECT_DIR}/add-profile.sh"
            printf '\nUpdated profile check:\n'
            updated_report="$(report_profiles)"
            printf '%s\n' "${updated_report}" | sed '/^VALID_PROFILE_COUNT=/d'
        else
            printf 'Continuing without a valid profile.\n'
        fi
    else
        printf 'Run ./add-profile.sh to create one.\n'
    fi
fi

log "Starting the backend user service"
systemctl --user daemon-reload
systemctl --user enable "${SERVICE_NAME}" >/dev/null
systemctl --user restart "${SERVICE_NAME}"

log "Waiting for the backend IPC socket"
for attempt in {1..10}; do
    [[ -S "${SOCKET_PATH}" ]] && break
    sleep 0.2
done
if [[ ! -S "${SOCKET_PATH}" ]]; then
    printf 'Warning: backend socket was not found at %s\n' "${SOCKET_PATH}" >&2
    printf 'Recent backend logs:\n' >&2
    journalctl --user -u "${SERVICE_NAME}" -n 30 --no-pager >&2 || true
else
    socket_mode="$(stat -c '%a' "${SOCKET_PATH}" 2>/dev/null || true)"
    if [[ "${socket_mode}" != "600" ]]; then
        printf 'Warning: socket mode is %s, expected 600: %s\n' \
            "${socket_mode:-unknown}" "${SOCKET_PATH}" >&2
    fi
fi

log "Enabling the GNOME top-panel extension"
if command -v gnome-extensions >/dev/null 2>&1; then
    gnome-extensions enable "${EXTENSION_UUID}" || {
        printf 'Warning: GNOME did not enable the extension immediately.\n' >&2
        printf 'Try: gnome-extensions enable %s\n' "${EXTENSION_UUID}" >&2
        printf 'You may need to log out and back in for GNOME Shell to reload it.\n' >&2
    }
    printf '\nGNOME extension status:\n'
    extension_info="$(gnome-extensions info "${EXTENSION_UUID}" 2>&1 || true)"
    printf '%s\n' "${extension_info}"
    if grep -q 'State: ERROR' <<<"${extension_info}"; then
        printf 'Warning: GNOME reported an extension error; inspect the Shell journal below.\n' >&2
    fi
else
    printf 'Warning: gnome-extensions was not found. Is GNOME Shell running?\n' >&2
fi

log "Application status"
systemctl --user --no-pager --full status "${SERVICE_NAME}" || true
printf '\nDatabase: %s\n' "${DATABASE_PATH}"
printf 'IPC socket: %s\n' "${SOCKET_PATH}"
printf 'Extension: %s\n' "${EXTENSION_UUID}"
printf 'Settings: %s\n' "${SETTINGS_APP_PATH}"
printf '\nTroubleshooting commands if the top bar is still empty:\n'
printf '  journalctl --user -u %s -n 100 --no-pager\n' "${SERVICE_NAME}"
printf '  gnome-extensions info %s\n' "${EXTENSION_UUID}"
printf '  ./add-profile.sh  # required if no valid profile exists\n'
printf '\nThe backend is running as a per-user systemd service.\n'
