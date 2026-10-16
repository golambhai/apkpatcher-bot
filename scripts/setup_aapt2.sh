#!/usr/bin/env bash
# Make an aapt2 binary available on PATH (used by apktool --aapt).
#
# Strategy 1 (preferred): run the "tilks" aarch64 community aapt2 build under
# qemu-user. It accepts legacy resource entry names like '$avd_hide_password__0'
# that EVERY official x86_64 build-tools aapt2 (30..37) rejects during compile.
# Strategy 2 (fallback): SDK build-tools <=34, else lzhiyong 34.0.3 static.
# (Both fallbacks are strict about '$' names - kept only as a last resort.)
set -euo pipefail

mkdir -p "$HOME/bin"

# Fake Termux `pkg` so the ApkPatcher dependency check passes on Linux CI.
cat > "$HOME/bin/pkg" <<'EOF'
#!/bin/bash
case "$1" in
  list-installed)
    echo "aapt2/stable,now 1.0.0 aarch64 [installed]"
    echo "openjdk-17/stable,now 17 aarch64 [installed]"
    echo "radare2/stable,now 6.2.4 aarch64 [installed]"
    ;;
  *) exit 0 ;;
esac
EOF
chmod +x "$HOME/bin/pkg"
echo "$HOME/bin" >> "$GITHUB_PATH"
echo "[pkg] shim installed (pretends aapt2/openjdk-17 installed)"

# No-op shims for Termux-only commands the patcher uses.
for shim in termux-wake-lock termux-wake-unlock; do
  printf '#!/bin/bash\nexit 0\n' > "$HOME/bin/$shim"
  chmod +x "$HOME/bin/$shim"
done
echo "[termux] wake-lock shims installed"

# Flutter SSL patch needs radare2 ('r2'); otherwise Flutter_SSL_Patch crashes
# with "'NoneType' object has no attribute 'split'".
if ! command -v r2 >/dev/null 2>&1; then
  echo "[r2] installing radare2..."
  sudo apt-get update -qq || true
  sudo apt-get install -y -qq radare2 >/dev/null 2>&1 || true
fi
if command -v r2 >/dev/null 2>&1; then
  echo "[r2] $(r2 -V 2>&1 | head -1)"
else
  echo "[r2] WARNING: radare2 not available - flutter patch will fail"
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ASSET="$REPO_ROOT/assets/tilks-aapt2-aarch64"

if [ -f "$ASSET" ]; then
  if ! command -v qemu-aarch64-static >/dev/null 2>&1 && ! command -v qemu-aarch64 >/dev/null 2>&1; then
    echo "[aapt2] installing qemu-user-static..."
    sudo apt-get update -qq || true
    sudo apt-get install -y -qq qemu-user-static >/dev/null 2>&1 || true
  fi
  QEMU=""
  if command -v qemu-aarch64-static >/dev/null 2>&1; then QEMU=qemu-aarch64-static
  elif command -v qemu-aarch64 >/dev/null 2>&1; then QEMU=qemu-aarch64
  fi
  if [ -n "$QEMU" ]; then
    cp "$ASSET" "$HOME/bin/aapt2-aarch64"
    chmod +x "$HOME/bin/aapt2-aarch64"
    if "$QEMU" "$HOME/bin/aapt2-aarch64" version >/dev/null 2>&1; then
      cat > "$HOME/bin/aapt2" <<EOF
#!/bin/bash
exec "$QEMU" "$HOME/bin/aapt2-aarch64" "\$@"
EOF
      chmod +x "$HOME/bin/aapt2"
      echo "[aapt2] tilks aarch64 build via $QEMU (accepts legacy '\$' entry names)"
    else
      echo "[aapt2] qemu cannot execute the tilks binary; falling back"
    fi
  else
    echo "[aapt2] qemu unavailable; falling back"
  fi
fi

if [ ! -x "$HOME/bin/aapt2" ]; then
  SDK_AAPT="$(find /usr/local/lib/android/sdk/build-tools -maxdepth 2 -name aapt2 -type f 2>/dev/null | grep -E '/(3[0-4])\.[0-9.]+/aapt2$' | sort -V | tail -1 || true)"
  if [ -n "$SDK_AAPT" ]; then
    cp "$SDK_AAPT" "$HOME/bin/aapt2"
    echo "[aapt2] installed from runner Android SDK: $SDK_AAPT"
  else
    echo "[aapt2] no SDK build-tools <=34 found, downloading 34.0.3 static build..."
    curl -fsSL -o /tmp/android-sdk-tools.zip \
      https://github.com/lzhiyong/android-sdk-tools/releases/download/34.0.3/android-sdk-tools-static-x86_64.zip

    python3 - <<'PY'
import os
import shutil
import zipfile

dest = os.path.expanduser("~/bin/aapt2")
with zipfile.ZipFile("/tmp/android-sdk-tools.zip") as z:
    names = [n for n in z.namelist() if n.endswith("aapt2")]
    if not names:
        raise SystemExit(f"aapt2 not found in zip: {z.namelist()}")
    with z.open(names[0]) as src, open(dest, "wb") as out:
        shutil.copyfileobj(src, out)
print("extracted to", dest)
PY
    echo "[aapt2] installed static 34.0.3 build"
  fi
fi

chmod +x "$HOME/bin/aapt2"
"$HOME/bin/aapt2" version || true
