#!/usr/bin/env bash
# Rebuild the in-process agent + launcher into agent/bin/. Requires the .NET SDK (installed by setup.sh).
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
E2E_HOME="${E2E_HOME:-/opt/winapp-linuxvm-e2e-skill}"
export DOTNET_ROOT="${DOTNET_ROOT_SDK:-$E2E_HOME/dotnet}"; export PATH="$DOTNET_ROOT:$PATH"
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
command -v dotnet >/dev/null || { echo "dotnet SDK not found (run scripts/setup.sh)"; exit 1; }
SRC="$SKILL_DIR/agent/src"; BIN="$SKILL_DIR/agent/bin"; TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$BIN/core" "$BIN/net48"
# Embedded debug info plus PathMap: stack traces keep file/line, and the binaries carry no absolute build paths.
PORTABLE=(-p:DebugType=embedded "-p:PathMap=$SRC=/agent-src/" -p:Deterministic=true)
dotnet build "$SRC/E2EAgent/E2EAgent.csproj" -c Release -f net6.0-windows -o "$TMP/core"  "${PORTABLE[@]}" -v q -nologo
dotnet build "$SRC/E2EAgent/E2EAgent.csproj" -c Release -f net48          -o "$TMP/net48" "${PORTABLE[@]}" -v q -nologo
dotnet build "$SRC/E2ELauncher/E2ELauncher.csproj" -c Release -o "$TMP/launcher" -p:E2EAgentDll="$TMP/net48/E2EAgent.dll" "${PORTABLE[@]}" -v q -nologo
cp "$TMP/core/E2EAgent.dll" "$BIN/core/"
cp "$TMP/net48/E2EAgent.dll" "$TMP/launcher/E2ELauncher.exe" "$TMP/launcher/E2ELauncher.exe.config" "$BIN/net48/"
rm -f "$BIN"/core/*.pdb "$BIN"/net48/*.pdb   # debug info is embedded in the assemblies
rm -rf "$SRC"/*/bin "$SRC"/*/obj
ls -l "$BIN"/core "$BIN"/net48
