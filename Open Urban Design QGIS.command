#!/bin/zsh
# Launch the local M2-A02 StudyArea slice in an isolated QGIS profile.
# Every mutable path below is inside this repository's runtime directory.  The
# default QGIS profile is never selected or modified by this script.

set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "$0")" && pwd -P)"
RUNTIME_ROOT="$PROJECT_ROOT/.urban_design_runtime"
QGIS_PROFILES_ROOT="$RUNTIME_ROOT/qgis-profiles"
QGIS_PROFILE_NAME="urban-design"
# QGIS expands --profiles-path to <root>/profiles/<name> (see QGIS --help).
QGIS_PROFILE_PATH="$QGIS_PROFILES_ROOT/profiles/$QGIS_PROFILE_NAME"
QGIS_INI="$QGIS_PROFILE_PATH/qgis.org/QGIS3.ini"
PROJECT_ID="rotterdam-m4h-pilot-project"
PROJECT_FILE="$RUNTIME_ROOT/$PROJECT_ID.qgs"
ANCHOR_CONFIG="$PROJECT_ROOT/config/rotterdam-m4h-anchor.json"
BRIDGE_PORT="${URBAN_DESIGN_BRIDGE_PORT:-8788}"
QGIS_MCP_PORT="9876"
QGIS_MCP_VERSION="0.14.0"
QGIS_BIN="${URBAN_DESIGN_QGIS_BIN:-/Applications/QGIS-LTR.app/Contents/MacOS/QGIS}"
# The project .venv is the pinned QGIS MCP/Ladybug runtime, but it predates the
# bridge's FastAPI dependency.  Use the configured host Python for the HTTP
# process and add the project runtime's site-packages only to that child.
BRIDGE_PYTHON="${URBAN_DESIGN_BRIDGE_PYTHON:-$(command -v python3)}"
QGIS_MCP_PYTHON="$PROJECT_ROOT/.venv/bin/python"
COMPANION_SOURCE="$PROJECT_ROOT/qgis_plugin/urban_design_study_area"
COMPANION_DEST="$QGIS_PROFILE_PATH/python/plugins/urban_design_study_area"
BRIDGE_DB="$RUNTIME_ROOT/state.sqlite3"
ARTIFACT_ROOT="$RUNTIME_ROOT/artifacts/study-area-bridge"
BRIDGE_LOG="$RUNTIME_ROOT/bridge.log"

fail() {
  print -u2 "Open Urban Design QGIS: $*"
  exit 1
}

# 8787 belongs to Hermes Web UI.  Reject it before touching the dedicated
# profile, generating a session token, or starting any child process.  The
# launcher never silently changes an explicitly requested port.
if [[ "$BRIDGE_PORT" =~ '^[0-9]+$' ]] && (( 10#$BRIDGE_PORT == 8787 )); then
  fail "port 8787 is reserved for the Hermes Web UI; Urban Design bridge uses 8788 (or another explicit non-Hermes port)"
fi
if ! [[ "$BRIDGE_PORT" =~ '^[0-9]+$' ]] || (( BRIDGE_PORT < 1 || BRIDGE_PORT > 65535 )); then
  fail "invalid Urban Design bridge port: $BRIDGE_PORT"
fi

# Validate the platform origin before touching runtime; explicit values never fall back.
export URBAN_DESIGN_API_BASE_URL="${URBAN_DESIGN_API_BASE_URL-http://127.0.0.1:8795}"
PLATFORM_API_ORIGIN_PATTERN='^http://(127[.]0[.]0[.]1|localhost)(:([0-9]+))?/?$'
if ! [[ "$URBAN_DESIGN_API_BASE_URL" =~ "$PLATFORM_API_ORIGIN_PATTERN" ]]; then
  fail "invalid platform API URL; HTTP 127.0.0.1/localhost origin required"
fi
PLATFORM_API_PORT="${match[3]:-80}"
if (( ${#PLATFORM_API_PORT} > 5 )) || (( 10#$PLATFORM_API_PORT < 1 || 10#$PLATFORM_API_PORT > 65535 )); then
  fail "invalid platform API port: $PLATFORM_API_PORT"
fi
if (( 10#$PLATFORM_API_PORT == 8787 || 10#$PLATFORM_API_PORT == 8644 || 10#$PLATFORM_API_PORT == 8788 )); then
  fail "platform API port $PLATFORM_API_PORT is reserved for Hermes or the QGIS bridge"
fi

# QGIS-LTR on this macOS installation does not expose a reliable second GUI
# instance when another QGIS process is already running: the second process
# can load the project and MCP socket without presenting an identifiable
# window.  Fail before creating the isolated profile, token, bridge, or MCP
# child so the operator cannot be sent to an unrelated QGIS canvas.  This is a
# deliberate single-instance boundary; the existing process is never closed,
# reused, or modified.
if ! command -v ps >/dev/null 2>&1; then
  fail "cannot verify QGIS GUI ownership: ps is required; save and close existing QGIS before retrying"
fi
if ! QGIS_RUNNING="$(ps -axo pid=,command= 2>/dev/null | awk '$2 ~ /\/QGIS$/ {found=1} END {if (found) print "QGIS_FOUND"}')"; then
  fail "cannot verify QGIS GUI ownership: process listing failed; save and close existing QGIS before retrying"
fi
if [[ -n "$QGIS_RUNNING" ]]; then
  fail "an existing QGIS process prevents a safe dedicated GUI launch; save and close every existing QGIS window, then retry"
fi

# Check ownership before creating runtime state.  A listener is reported and
# left untouched; this is deliberately a safe failure rather than a kill or a
# fallback to another port.  lsof is part of the macOS runtime used by this
# launcher and lets the operator identify a stale/competing process.
if ! command -v lsof >/dev/null 2>&1; then
  fail "cannot verify bridge port $BRIDGE_PORT ownership: lsof is required"
fi
BRIDGE_LISTENER="$(lsof -nP -iTCP:"$BRIDGE_PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "$BRIDGE_LISTENER" ]]; then
  fail "bridge port $BRIDGE_PORT is already in use; refusing to stop or share the owner:\n$BRIDGE_LISTENER"
fi

[[ -x "$BRIDGE_PYTHON" ]] || fail "project runtime is missing $BRIDGE_PYTHON"
[[ -x "$QGIS_MCP_PYTHON" ]] || fail "project runtime is missing $QGIS_MCP_PYTHON"
[[ -x "$QGIS_BIN" ]] || fail "QGIS executable not found: $QGIS_BIN"
[[ -d "$COMPANION_SOURCE" ]] || fail "companion plugin source not found: $COMPANION_SOURCE"
[[ -f "$ANCHOR_CONFIG" ]] || fail "project geographic anchor config not found: $ANCHOR_CONFIG"
"$BRIDGE_PYTHON" -c 'import fastapi, uvicorn' >/dev/null 2>&1 || fail \
  "bridge Python must provide FastAPI and uvicorn (set URBAN_DESIGN_BRIDGE_PYTHON)"
PYTHONPATH="$PROJECT_ROOT/src" "$BRIDGE_PYTHON" - "$ANCHOR_CONFIG" "$PROJECT_ROOT" <<'PY' || fail "project geographic anchor/context is unresolved"
import sys
from urban_design.project_anchor import load_project_anchor
load_project_anchor(sys.argv[1], root=sys.argv[2])
PY

# Check the package before starting anything.  The server and plugin must be
# the same exact pinned qgis-mcp release; no silent substitution is allowed.
MCP_SERVER_VERSION="$($QGIS_MCP_PYTHON - <<'PY'
import importlib.metadata
try:
    print(importlib.metadata.version("qgis-mcp"))
except importlib.metadata.PackageNotFoundError:
    raise SystemExit(2)
PY
)" || fail "qgis-mcp server package is unavailable in the project runtime"
[[ "$MCP_SERVER_VERSION" == "$QGIS_MCP_VERSION" ]] || fail \
  "qgis-mcp server must be exactly $QGIS_MCP_VERSION (found $MCP_SERVER_VERSION)"

MCP_PLUGIN_SOURCE="${URBAN_DESIGN_QGIS_MCP_PLUGIN_SOURCE:-}"
if [[ -z "$MCP_PLUGIN_SOURCE" ]]; then
  for candidate in \
    "$PROJECT_ROOT/.qgis_mcp_plugin" \
    "/private/tmp/qgis-mcp-src/qgis-mcp-main/qgis_mcp_plugin" \
    "/private/tmp/qgis-isolated/profiles/m1/python/plugins/qgis_mcp_plugin"; do
    if [[ -f "$candidate/metadata.txt" ]]; then
      MCP_PLUGIN_SOURCE="$candidate"
      break
    fi
  done
fi
[[ -n "$MCP_PLUGIN_SOURCE" && -f "$MCP_PLUGIN_SOURCE/metadata.txt" ]] || \
  fail "qgis-mcp plugin source is unavailable; set URBAN_DESIGN_QGIS_MCP_PLUGIN_SOURCE"
MCP_PLUGIN_VERSION="$(awk -F= '$1 == "version" {gsub(/[[:space:]]/, "", $2); print $2; exit}' "$MCP_PLUGIN_SOURCE/metadata.txt")"
[[ "$MCP_PLUGIN_VERSION" == "$QGIS_MCP_VERSION" ]] || fail \
  "qgis-mcp plugin must be exactly $QGIS_MCP_VERSION (found $MCP_PLUGIN_VERSION)"

mkdir -p "$QGIS_PROFILE_PATH/qgis.org" "$QGIS_PROFILE_PATH/python/plugins" "$ARTIFACT_ROOT"

# Install both plugins into this dedicated profile only.  The copy is
# repeatable and leaves the default QGIS profile untouched.
mkdir -p "$QGIS_PROFILE_PATH/python/plugins/qgis_mcp_plugin"
cp -R "$MCP_PLUGIN_SOURCE"/. "$QGIS_PROFILE_PATH/python/plugins/qgis_mcp_plugin"/
mkdir -p "$COMPANION_DEST"
cp -R "$COMPANION_SOURCE"/. "$COMPANION_DEST"/

# Configure only the dedicated profile.  Existing settings are preserved and
# only the two required plugin enablement keys are appended when absent.
if [[ ! -f "$QGIS_INI" ]]; then
  cat > "$QGIS_INI" <<'INI'
[qgis_mcp]
autostart=true
first_run=false

[PythonPlugins]
qgis_mcp_plugin=true
urban_design_study_area=true
INI
else
  if ! grep -q '^\[qgis_mcp\]$' "$QGIS_INI"; then
    cat >> "$QGIS_INI" <<'INI'

[qgis_mcp]
autostart=true
first_run=false
INI
  fi
  if ! grep -q '^qgis_mcp_plugin=true$' "$QGIS_INI"; then
    cat >> "$QGIS_INI" <<'INI'

[PythonPlugins]
qgis_mcp_plugin=true
INI
  fi
  if ! grep -q '^urban_design_study_area=true$' "$QGIS_INI"; then
    cat >> "$QGIS_INI" <<'INI'
urban_design_study_area=true
INI
  fi
fi

# A launch-scoped secret authenticates both the HTTP bridge and QGIS MCP.  It
# is intentionally generated after version/profile checks and never stored in
# the project or in QGIS settings.
SESSION_TOKEN="$($BRIDGE_PYTHON -c 'import secrets; print(secrets.token_urlsafe(32))')"
export QGIS_MCP_TOKEN="$SESSION_TOKEN"
export URBAN_DESIGN_SESSION_TOKEN="$SESSION_TOKEN"
export URBAN_DESIGN_BRIDGE_URL="http://127.0.0.1:$BRIDGE_PORT"
export URBAN_DESIGN_PROJECT_ROOT="$PROJECT_ROOT"
export URBAN_DESIGN_PROJECT_ID="$PROJECT_ID"
export URBAN_DESIGN_BRIDGE_PORT="$BRIDGE_PORT"
export URBAN_DESIGN_INSTANCE="$PROJECT_FILE"
export URBAN_DESIGN_ANCHOR_CONFIG="$ANCHOR_CONFIG"
export URBAN_DESIGN_ANCHOR_ROOT="$PROJECT_ROOT"

# QGIS accepts this small project file.  It carries only the project identity;
# no historical proposal or boundary is loaded or adopted here.
if [[ ! -f "$PROJECT_FILE" ]]; then
  cat > "$PROJECT_FILE" <<XML
<?xml version="1.0" encoding="UTF-8"?>
<qgis projectname="$PROJECT_ID" version="3.40.5">
  <projectMetadata/>
  <projectlayers/>
  <layer-tree-group name="" checked="Qt::Checked" expanded="1"/>
  <customproperties>
    <property key="urban_design/project_id" value="$PROJECT_ID"/>
  </customproperties>
</qgis>
XML
fi

# Start the bridge in a child process and stop exactly that process when QGIS
# exits or the launcher receives a signal.  Running the explicit factory binds
# state/artifacts and MCP credentials to this launch.
export URBAN_DESIGN_BRIDGE_DB="$BRIDGE_DB"
export URBAN_DESIGN_ARTIFACT_ROOT="$ARTIFACT_ROOT"
export URBAN_DESIGN_QGIS_MCP_PORT="$QGIS_MCP_PORT"
(
  cd "$PROJECT_ROOT"
  BRIDGE_SYSTEM_SITE="$($BRIDGE_PYTHON -c 'import site; print(site.getsitepackages()[0])')"
  BRIDGE_SITE_PACKAGES="$PROJECT_ROOT/.venv/lib/python$($BRIDGE_PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')/site-packages"
  # Keep FastAPI/Uvicorn and their Starlette dependency from the selected
  # bridge interpreter first; the project runtime is appended for Ladybug and
  # Honeybee imports.  Mixing the two in reverse order can pair incompatible
  # FastAPI/Starlette releases.
  export PYTHONPATH="$PROJECT_ROOT/src:$BRIDGE_SYSTEM_SITE${PYTHONPATH:+:$PYTHONPATH}"
  if [[ -d "$BRIDGE_SITE_PACKAGES" ]]; then
    export PYTHONPATH="$PROJECT_ROOT/src:$BRIDGE_SYSTEM_SITE:$BRIDGE_SITE_PACKAGES${PYTHONPATH:+:$PYTHONPATH}"
  fi
  RADIANCE_ROOT="${URBAN_DESIGN_RADIANCE_ROOT:-/private/tmp/radiance-arm64/radiance}"
  if [[ -d "$RADIANCE_ROOT/bin" ]]; then
    export BINPATH="$RADIANCE_ROOT/bin"
    export PATH="$RADIANCE_ROOT/bin:$PATH"
    [[ -d "$RADIANCE_ROOT/lib" ]] && export RAYPATH="$RADIANCE_ROOT/lib"
  fi
  exec "$BRIDGE_PYTHON" - <<'PY'
import os
import uvicorn

from urban_design.bridge import create_app

app = create_app(
    database_path=os.environ["URBAN_DESIGN_BRIDGE_DB"],
    artifact_root=os.environ["URBAN_DESIGN_ARTIFACT_ROOT"],
    qgis_host="127.0.0.1",
    qgis_port=int(os.environ["URBAN_DESIGN_QGIS_MCP_PORT"]),
    qgis_token=os.environ["QGIS_MCP_TOKEN"],
    qgis_server_version="0.14.0",
    instance_id=os.environ["URBAN_DESIGN_INSTANCE"],
    session_token=os.environ["URBAN_DESIGN_SESSION_TOKEN"],
    initialize_project=True,
    default_project_id=os.environ["URBAN_DESIGN_PROJECT_ID"],
    anchor_config_path=os.environ["URBAN_DESIGN_ANCHOR_CONFIG"],
    anchor_root=os.environ["URBAN_DESIGN_ANCHOR_ROOT"],
)
uvicorn.run(app, host="127.0.0.1", port=int(os.environ["URBAN_DESIGN_BRIDGE_PORT"]), log_level="info")
PY
) >| "$BRIDGE_LOG" 2>&1 &
BRIDGE_PID=$!

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  if kill -0 "$BRIDGE_PID" 2>/dev/null; then
    kill -TERM "$BRIDGE_PID" 2>/dev/null || true
    wait "$BRIDGE_PID" 2>/dev/null || true
  fi
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

# Give FastAPI a bounded opportunity to bind before launching QGIS.  The
# endpoint is authenticated with the same launch-scoped token and is polled on
# loopback only.
BRIDGE_READY=0
for _ in {1..30}; do
  if curl --silent --fail --max-time 1 \
    -H "X-Urban-Design-Session-Token: $SESSION_TOKEN" \
    "http://127.0.0.1:$BRIDGE_PORT/api/v1/integrations/status" >/dev/null 2>&1; then
    BRIDGE_READY=1
    break
  fi
  sleep 0.2
done
if [[ "$BRIDGE_READY" != "1" ]] || ! kill -0 "$BRIDGE_PID" 2>/dev/null; then
  fail "FastAPI bridge did not become ready; inspect $BRIDGE_LOG"
fi

"$QGIS_BIN" \
  --profiles-path "$QGIS_PROFILES_ROOT" \
  --profile "$QGIS_PROFILE_NAME" \
  --project "$PROJECT_FILE"
