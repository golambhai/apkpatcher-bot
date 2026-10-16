#!/usr/bin/env bash
# Make an aapt2 binary available on PATH (used by apktool --aapt in -e mode).
set -euo pipefail

mkdir -p "$HOME/bin"

if command -v aapt2 >/dev/null 2>&1; then
  echo "[aapt2] already on PATH: $(command -v aapt2)"
  "$(command -v aapt2)" version || true
  exit 0
fi

SDK_AAPT="$(find /usr/local/lib/android/sdk/build-tools -maxdepth 2 -name aapt2 -type f 2>/dev/null | sort -V | tail -1 || true)"
if [ -n "$SDK_AAPT" ]; then
  cp "$SDK_AAPT" "$HOME/bin/aapt2"
  chmod +x "$HOME/bin/aapt2"
  echo "$HOME/bin" >> "$GITHUB_PATH"
  echo "[aapt2] installed from runner Android SDK: $SDK_AAPT"
  "$HOME/bin/aapt2" version || true
  exit 0
fi

echo "[aapt2] Android SDK build-tools not found, downloading static build..."
curl -fsSL -o /tmp/android-sdk-tools.zip \
  https://github.com/lzhiyong/android-sdk-tools/releases/download/35.0.2/android-sdk-tools-static-x86_64.zip

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

chmod +x "$HOME/bin/aapt2"
echo "$HOME/bin" >> "$GITHUB_PATH"
"$HOME/bin/aapt2" version || true
