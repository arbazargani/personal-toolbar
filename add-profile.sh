#!/usr/bin/env bash
set -Eeuo pipefail

DATABASE_PATH="${XDG_CONFIG_HOME:-${HOME}/.config}/modular-toolbar/toolbar.db"
SERVICE_NAME="modular-toolbar.service"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "${EUID}" -ne 0 ]] || fail "Run this as your normal user, not with sudo."
command -v sqlite3 >/dev/null 2>&1 || fail "sqlite3 is required. Install it with: sudo apt install sqlite3"
[[ -f "${DATABASE_PATH}" ]] || fail "Database not found: ${DATABASE_PATH}. Run ./start.sh first."

printf 'Profile display name (for example, Personal): '
IFS= read -r name
[[ -n "${name}" ]] || fail "Profile name cannot be empty."

printf 'Avalai API key (input hidden): '
IFS= read -r -s api_key
printf '\n'
[[ -n "${api_key}" ]] || fail "API key cannot be empty."

slug=$(printf '%s' "${name}" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-//; s/-$//')
[[ -n "${slug}" ]] || fail "Could not create a profile ID from that name."

# Avoid overwriting an existing profile accidentally.
if sqlite3 "${DATABASE_PATH}" "SELECT 1 FROM profiles WHERE id = '${slug//\'/\'\'}' LIMIT 1;" | grep -q '^1$'; then
    fail "A profile with ID '${slug}' already exists. Use a different name or edit it in SQLite."
fi

sql_escape() { printf '%s' "$1" | sed "s/'/''/g"; }
name_sql=$(sql_escape "${name}")
key_sql=$(sql_escape "${api_key}")
id_sql=$(sql_escape "${slug}")

sqlite3 "${DATABASE_PATH}" <<SQL
INSERT INTO profiles (id, module_id, name, api_key, enabled, last_error)
VALUES ('${id_sql}', 'avalai_credit_info', '${name_sql}', '${key_sql}', 1, '');
SQL

unset api_key key_sql

if command -v systemctl >/dev/null 2>&1 && systemctl --user cat "${SERVICE_NAME}" >/dev/null 2>&1; then
    systemctl --user restart "${SERVICE_NAME}"
fi

printf 'Added enabled profile: %s (id: %s)\n' "${name}" "${slug}"
printf 'The backend will fetch it immediately.\n'
