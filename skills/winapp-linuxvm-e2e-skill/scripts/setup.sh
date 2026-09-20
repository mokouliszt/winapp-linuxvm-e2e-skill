#!/usr/bin/env bash
# Idempotent provisioning for winapp-linuxvm-e2e-skill (Ubuntu 24.04 x86_64, root).
#   scripts/setup.sh [--no-sdk] [--skip-apt]
# Env: E2E_HOME (default /opt/winapp-linuxvm-e2e-skill), WINE_VERSION (default 11.0), DOTNET_CHANNEL (default 8.0), E2E_DISPLAY (default :99)
# Network needed: archive.ubuntu.com, github.com (+ release asset CDN), dl.winehq.org, builds.dotnet.microsoft.com
set -euo pipefail
trap 'echo "setup failed at line $LINENO" >&2' ERR

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
E2E_HOME="${E2E_HOME:-/opt/winapp-linuxvm-e2e-skill}"
WINE_VERSION="${WINE_VERSION:-11.0}"
DOTNET_CHANNEL="${DOTNET_CHANNEL:-8.0}"
DISPLAY_ID="${E2E_DISPLAY:-:99}"
WITH_SDK=1; SKIP_APT=0
for a in "$@"; do case "$a" in --no-sdk) WITH_SDK=0;; --skip-apt) SKIP_APT=1;; *) echo "unknown option: $a"; exit 2;; esac; done
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

log() { printf '\n== %s\n' "$*"; }

# Downloads are verified by scripts/verify_download.py against every available source, which must agree:
#   the SHA-256 pinned below (default versions only), the digest GitHub recorded at upload time (release page), and the maintainer's sha256sums.txt.
# Fail closed: a download with no checksum source at all is discarded unless E2E_ALLOW_UNVERIFIED=1 is set.
declare -A PIN=(
  ["wine-11.0-amd64-wow64.tar.xz"]="39574efa1132c3ca0d5c77dd2eddbe4a49cca0d6cc2c290ff4924493a1c40314"
  ["wine-mono-10.4.1-x86.tar.xz"]="a16606ef0724202e6a6848ece6e0cbba64d11e2f11aefe744af1d93c6d9f99bb"
)
verify_download() {  # verify_download <file> <asset-name> <owner/repo> <tag> [sums-url]
  local rc=0 args=("$1" --name "$2" --github "$3" "$4")
  [ -n "${PIN[$2]:-}" ] && args+=(--pin "${PIN[$2]}")
  [ -n "${5:-}" ] && args+=(--sums-url "$5")
  python3 "$SKILL_DIR/scripts/verify_download.py" "${args[@]}" || rc=$?
  case "$rc" in
    0) ;;
    3) if [ "${E2E_ALLOW_UNVERIFIED:-0}" = 1 ]; then
         echo "WARNING: $2 is UNVERIFIED (no checksum source; E2E_ALLOW_UNVERIFIED=1)" >&2
       else
         rm -f "$1"
         echo "no checksum source for $2 - refusing to install it. Set E2E_ALLOW_UNVERIFIED=1 to override." >&2; exit 1
       fi ;;
    *) rm -f "$1"; echo "download discarded: $2" >&2; exit 1 ;;
  esac
}

# Extract into "<dir>.partial" and rename into place, so an interrupted setup never leaves a half-extracted
# directory that the next run mistakes for a finished install.
extract_atomically() {  # extract_atomically <archive> <dest-dir> <marker-relative-to-dest> [tar-flags...]
  local archive="$1" dest="$2" marker="$3"; shift 3
  rm -rf "$dest.partial"; mkdir -p "$dest.partial"
  tar -xf "$archive" -C "$dest.partial" "$@"
  [ -e "$dest.partial/$marker" ] || { rm -rf "$dest.partial"; echo "archive $(basename "$archive") did not contain $marker" >&2; exit 1; }
  rm -rf "$dest"; mv "$dest.partial" "$dest"
}

mkdir -p "$E2E_HOME" "$E2E_HOME/logs"

# ---------------------------------------------------------------- 1. apt packages
if [ "$SKIP_APT" = 0 ]; then
  log "apt packages"
  PKGS="xvfb xdotool xclip x11-utils imagemagick ffmpeg fonts-noto-cjk fonts-ipafont-gothic unzip curl xz-utils ca-certificates python3 binutils libwine"
  MISSING=""; for p in $PKGS; do dpkg -s "$p" >/dev/null 2>&1 || MISSING="$MISSING $p"; done
  if [ -n "$MISSING" ]; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $MISSING
  else echo "all present"; fi
fi

# ---------------------------------------------------------------- 2. Wine (Kron4ek wow64 build)
WINE_DIR="$E2E_HOME/wine"
if [ -x "$WINE_DIR/bin/wine" ]; then
  INSTALLED_WINE_VERSION="$("$WINE_DIR/bin/wine" --version 2>/dev/null || true)"
  [ "$INSTALLED_WINE_VERSION" = "wine-$WINE_VERSION" ] || {
    echo "existing $WINE_DIR is ${INSTALLED_WINE_VERSION:-unusable}, but WINE_VERSION=$WINE_VERSION was requested; use an empty E2E_HOME to change versions" >&2
    exit 1
  }
fi
if [ ! -x "$WINE_DIR/bin/wine" ]; then
  log "Wine $WINE_VERSION (wow64 build)"
  curl -fsSL --retry 3 -o "$TMP_DIR/wine.tar.xz" "https://github.com/Kron4ek/Wine-Builds/releases/download/${WINE_VERSION}/wine-${WINE_VERSION}-amd64-wow64.tar.xz"
  verify_download "$TMP_DIR/wine.tar.xz" "wine-${WINE_VERSION}-amd64-wow64.tar.xz" Kron4ek/Wine-Builds "$WINE_VERSION" \
    "https://github.com/Kron4ek/Wine-Builds/releases/download/${WINE_VERSION}/sha256sums.txt"
  extract_atomically "$TMP_DIR/wine.tar.xz" "$WINE_DIR" bin/wine --strip-components=1
fi

# ---------------------------------------------------------------- 3. wine-mono (exact version Wine asks for; else an installer dialog blocks forever)
# the version string is stored as UTF-16LE inside appwiz.cpl -> strings -e l
MONO="$( (strings -a -e l "$WINE_DIR/lib/wine/x86_64-windows/appwiz.cpl" | grep -o 'wine-mono-[0-9][0-9.]*-x86' | head -1 | sed 's/-x86$//') || true )"
[ -n "$MONO" ] || { echo "could not determine required wine-mono version" >&2; exit 1; }
if [ ! -d "$WINE_DIR/share/wine/mono/$MONO" ]; then
  log "$MONO"
  MONO_VER="${MONO#wine-mono-}"   # canonical host: WineHQ (independent of GitHub, whose release-page digest is the cross-check); GitHub as fallback
  curl -fsSL --retry 3 -o "$TMP_DIR/mono.tar.xz" "https://dl.winehq.org/wine/wine-mono/${MONO_VER}/${MONO}-x86.tar.xz" \
    || curl -fsSL --retry 3 -o "$TMP_DIR/mono.tar.xz" "https://github.com/wine-mono/wine-mono/releases/download/${MONO}/${MONO}-x86.tar.xz"
  verify_download "$TMP_DIR/mono.tar.xz" "${MONO}-x86.tar.xz" wine-mono/wine-mono "$MONO"
  extract_atomically "$TMP_DIR/mono.tar.xz" "$WINE_DIR/share/wine/mono" "$MONO"
fi

# ---------------------------------------------------------------- 4. Xvfb
export DISPLAY="$DISPLAY_ID"
if ! xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
  log "Xvfb $DISPLAY"
  setsid nohup Xvfb "$DISPLAY" -screen 0 1280x800x24 -nolisten tcp >"$E2E_HOME/logs/xvfb.log" 2>&1 </dev/null &
  for _ in $(seq 1 20); do xdpyinfo -display "$DISPLAY" >/dev/null 2>&1 && break; sleep 0.5; done
  xdpyinfo -display "$DISPLAY" >/dev/null 2>&1 || { echo "Xvfb did not come up on $DISPLAY (see $E2E_HOME/logs/xvfb.log)" >&2; exit 1; }
fi

# ---------------------------------------------------------------- 5. Wine prefix + fonts
export WINE="$WINE_DIR/bin/wine" WINEPREFIX="$E2E_HOME/prefix" WINEARCH=win64 WINEDEBUG=-all WINEDLLOVERRIDES="mshtml="
if [ ! -f "$WINEPREFIX/system.reg" ]; then
  log "creating Wine prefix"
  timeout 240 "$WINE" wineboot -u || true      # wineboot may exit non-zero although the prefix is fine; check the result instead
  timeout 60 "$WINE_DIR/bin/wineserver" -w || true
  [ -f "$WINEPREFIX/system.reg" ] || { echo "wineboot did not create the Wine prefix ($WINEPREFIX)" >&2; exit 1; }
fi
if [ ! -f "$WINEPREFIX/.e2e-fonts-imported" ]; then
  log "importing font substitutions"
  { printf '\xff\xfe'; iconv -f UTF-8 -t UTF-16LE "$SKILL_DIR/assets/fonts.reg"; } > "$TMP_DIR/fonts16.reg"
  timeout 60 "$WINE" regedit "$TMP_DIR/fonts16.reg" && touch "$WINEPREFIX/.e2e-fonts-imported"
  timeout 60 "$WINE_DIR/bin/wineserver" -w || true
fi

# ---------------------------------------------------------------- 6. .NET SDK (Linux) for building apps / rebuilding the agent
# The tarball is downloaded and SHA-512-verified directly from Microsoft's release metadata: dotnet-install.sh itself is an
# unverified script executed as root, so it is only a fallback (E2E_ALLOW_UNVERIFIED=1).
# Installs the requested channel next to any SDK already there (DOTNET_CHANNEL=10.0 adds SDK 10 for net9/net10 apps; the newest SDK is used for builds).
SDK_MAJOR="${DOTNET_CHANNEL%%.*}"
if [ "$WITH_SDK" = 1 ] && { [ ! -x "$E2E_HOME/dotnet/dotnet" ] || ! "$E2E_HOME/dotnet/dotnet" --list-sdks 2>/dev/null | grep -q "^${SDK_MAJOR}\."; }; then
  log ".NET SDK $DOTNET_CHANNEL (the Ubuntu apt SDK lacks the WindowsDesktop SDK)"
  SDK_INFO="$(python3 "$SKILL_DIR/scripts/dotnet_sdk_url.py" "$DOTNET_CHANNEL")"   # prints: <url> <sha512>
  SDK_URL="${SDK_INFO%% *}"; SDK_SHA="${SDK_INFO##* }"
  curl -fsSL --retry 3 -o "$TMP_DIR/dotnet-sdk.tar.gz" "$SDK_URL"
  SDK_ACTUAL="$(sha512sum "$TMP_DIR/dotnet-sdk.tar.gz")"; SDK_ACTUAL="${SDK_ACTUAL%% *}"
  [ "$SDK_ACTUAL" = "$SDK_SHA" ] || { echo "SHA-512 mismatch for $SDK_URL" >&2; exit 1; }
  echo "sha512 ok: $(basename "$SDK_URL") (source: dotnet release metadata)"
  # an SDK is added next to existing ones, so extract in place after verifying the digest (a rename would drop older SDKs)
  mkdir -p "$E2E_HOME/dotnet"; tar -xzf "$TMP_DIR/dotnet-sdk.tar.gz" -C "$E2E_HOME/dotnet"
  "$E2E_HOME/dotnet/dotnet" --list-sdks | grep -q "^${SDK_MAJOR}\." || { echo "SDK $DOTNET_CHANNEL did not install" >&2; exit 1; }
fi

# ---------------------------------------------------------------- 7. env file
{
  printf 'export E2E_HOME=%q\n' "$E2E_HOME"
  printf 'export WINE=%q\n' "$WINE_DIR/bin/wine"
  printf 'export WINEPREFIX=%q WINEARCH=win64 WINEDEBUG=-all WINEDLLOVERRIDES=mshtml=\n' "$E2E_HOME/prefix"
  printf 'export DISPLAY=%q\n' "$DISPLAY_ID"
  printf 'export DOTNET_ROOT_SDK=%q DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1\n' "$E2E_HOME/dotnet"
  printf 'export PATH=%q:%q:$PATH\n' "$E2E_HOME/dotnet" "$WINE_DIR/bin"
} > "$E2E_HOME/env.sh"

log "doctor"
python3 "$SKILL_DIR/scripts/e2e.py" doctor
