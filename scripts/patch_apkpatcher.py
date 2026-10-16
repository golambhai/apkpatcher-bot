#!/usr/bin/env python3
"""Post-install patcher for the ApkPatcher package.

Two jobs:

1) Force the installed ApkPatcher to use the system aapt2 for apktool builds.

   The non-Windows download APKTool_Termux.jar bundles an aarch64 aapt2 under
   prebuilt/linux/aapt2. On an x86_64 CI runner that binary cannot execute, so
   apktool falls back to running it through a shell and fails with
   "ELF ... not found" / "Syntax error: ( unexpected".

   Passing the system aapt2 via apktool's --aapt flag overrides the bundled
   binary and fixes both normal and -e (emulator) builds.

2) Rebrand all user-visible strings to CRACKED GR / ZX ROCK 007.

   Only DISPLAY strings are touched. Functional identifiers are kept intact:
   - smali package path "RK_TECHNO_INDIA" (AES.py hook target)
   - raw resource names "Techno_India" / "Techno_India.pem" (CERT_NSC.py)
   - download URLs on github.com/TechnoIndian (Files_Check.py)
   The ASCII banner is stored zlib+base64 encoded in APK_PATCHER.py, so it is
   decoded, re-branded and re-encoded here.
"""

import base64
import os
import re
import sys
import zlib

import ApkPatcher

PKG_DIR = os.path.dirname(ApkPatcher.__file__)

TARGET = os.path.join(PKG_DIR, "Utils", "Decompile_Compile.py")

ANCHOR = 'cmd = ["java", "-jar", APKTool_Path, "b", decompile_dir, "-o", build_dir, "-p", decompile_dir, "-f", "--copy-original"]'

MARKER = "# patcher: use system aapt2"

FIX = ANCHOR + f"""

        _aapt2 = M.shutil.which("aapt2")
        if _aapt2:  {MARKER}
            cmd += ["--aapt", _aapt2]
"""

# (old, new) — most specific first. Never contains plain "RK_TECHNO_INDIA",
# "Techno_India" or "TechnoIndian" (those are functional identifiers/URLs).
REPLACEMENTS = [
    ("🇮🇳 AbhiTheM0dder 🇮🇳", "🛠️ CRACKED GR 🛠️"),
    ("AbhiTheM0dder", "ZX ROCK 007"),
    ("残页", "CRACKED GR"),
    ("@canyie", "@ZX_ROCK_007"),
    ("(canyie)", "(ZX ROCK 007)"),
    ("@rktechnoindians", "@ZX_ROCK_007"),
    ("@RK_TECHNO_INDIA", "@ZX_ROCK_007"),
    ("TechnoIndia's", "CRACKED GR's"),
    ("Techno - India", "CRACKED GR"),
    ("Techno India", "CRACKED GR"),
]

BANNER_REPLACEMENTS = [
    ("Techno India", "CRACKED GR"),
    (" Techno - India ", " CRACKED GR "),
    ("@rktechnoindians", "@ZX_ROCK_007"),
    ("@RK_TECHNO_INDIA", "@ZX_ROCK_007"),
]

NEW_GLYPH_LINE = "𓄂 ZX 𓆐 ︻デ═一 ࿗ ROCK 007 ࿗"

CREDITS_PY = '''from ..ANSI_COLORS import ANSI; C = ANSI()


# ---------------- Credits ----------------
def Credits():
    exit(f"""
                     🛠️  CRACKED GR  🛠️

{C.S} Tool {C.E}{C.G} CRACKED GR APK Patcher {C.S}{C.P} Full Suite {C.E}

{C.S} TEAM {C.E}{C.G} CRACKED GR {C.S}{C.P} @ZX_ROCK_007 {C.E}

{C.S} DEVELOPER {C.E}{C.G} ZX ROCK 007 {C.S}{C.P} @ZX_ROCK_007 {C.E}


{C.S}  NOTE  {C.E} {C.Y} Unauthorized re-distribution prohibited. 🛡️🛡️

    """)
'''


def apply_aapt2_patch() -> int:
    with open(TARGET, encoding="utf-8") as f:
        src = f.read()

    if MARKER in src or ("isEmulator:" in src and "--aapt" in src):
        print("[patch] aapt2: already applied")
        return 0

    count = src.count(ANCHOR)
    if count != 1:
        print(
            f"[patch] aapt2: anchor not found exactly once (count={count}) — package layout changed",
            file=sys.stderr,
        )
        return 1

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src.replace(ANCHOR, FIX, 1))

    print(f"[patch] aapt2: applied to {TARGET}")
    return 0


def rebrand_file(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        src = f.read()
    out = src
    for old, new in REPLACEMENTS:
        out = out.replace(old, new)
    if out == src:
        return 0
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    return 1


def rebrand_banner() -> int:
    path = os.path.join(PKG_DIR, "APK_PATCHER.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()

    m = re.search(r'b64 = """(.*?)"""', src, re.S)
    if not m:
        print("[patch] banner: b64 blob not found", file=sys.stderr)
        return 0

    art = zlib.decompress(base64.b64decode(m.group(1))).decode("utf-8")
    new_art = art
    for old, new in BANNER_REPLACEMENTS:
        new_art = new_art.replace(old, new)

    i = new_art.find("𓄂")
    j = new_art.find("\x1b[0m", i)
    if i != -1 and j != -1 and "ROCK 007" not in new_art[i:j]:
        new_art = new_art[:i] + NEW_GLYPH_LINE + new_art[j:]

    if new_art == art:
        print("[patch] banner: already branded")
        return 0

    new_b64 = base64.b64encode(zlib.compress(new_art.encode("utf-8"))).decode()
    with open(path, "w", encoding="utf-8") as f:
        f.write(src[: m.start(1)] + new_b64 + src[m.end(1):])
    print("[patch] banner: rebranded")
    return 1


def rewrite_credits() -> int:
    path = os.path.join(PKG_DIR, "Utils", "Credits.py")
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == CREDITS_PY:
                print("[patch] credits: already rebranded")
                return 0
    except OSError:
        print("[patch] credits: missing", file=sys.stderr)
        return 0
    with open(path, "w", encoding="utf-8") as f:
        f.write(CREDITS_PY)
    print("[patch] credits: rebranded")
    return 1


def apply_branding():
    touched = 0
    for root, _dirs, files in os.walk(PKG_DIR):
        if "__pycache__" in root:
            continue
        for name in files:
            if name.endswith(".py"):
                touched += rebrand_file(os.path.join(root, name))
    changed = rebrand_banner() + rewrite_credits()
    print(f"[patch] branding: {touched} file(s) + banner/credits changed={changed}")


def main() -> int:
    rc = apply_aapt2_patch()
    try:
        apply_branding()
    except Exception as e:  # branding must never break the bot
        print(f"[patch] branding failed: {e}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
