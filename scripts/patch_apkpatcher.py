#!/usr/bin/env python3
"""Force the installed ApkPatcher to use the system aapt2 for apktool builds.

The non-Windows download APKTool_Termux.jar bundles an aarch64 aapt2 under
prebuilt/linux/aapt2. On an x86_64 CI runner that binary cannot execute, so
apktool falls back to running it through a shell and fails with
"ELF ... not found" / "Syntax error: ( unexpected".

Passing the system aapt2 (x86_64, already on PATH) via apktool's --aapt flag
overrides the bundled binary and fixes both normal and -e (emulator) builds.
"""

import os
import sys

import ApkPatcher

TARGET = os.path.join(
    os.path.dirname(ApkPatcher.__file__), "Utils", "Decompile_Compile.py"
)

ANCHOR = 'cmd = ["java", "-jar", APKTool_Path, "b", decompile_dir, "-o", build_dir, "-p", decompile_dir, "-f", "--copy-original"]'

MARKER = "# patcher: use system aapt2"

FIX = ANCHOR + f"""

        _aapt2 = M.shutil.which("aapt2")
        if _aapt2:  {MARKER}
            cmd += ["--aapt", _aapt2]
"""


def main() -> int:
    with open(TARGET, encoding="utf-8") as f:
        src = f.read()

    if MARKER in src or ("isEmulator:" in src and "--aapt" in src):
        print("[patch] already applied")
        return 0

    count = src.count(ANCHOR)
    if count != 1:
        print(
            f"[patch] anchor not found exactly once (count={count}) — package layout changed",
            file=sys.stderr,
        )
        return 1

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src.replace(ANCHOR, FIX, 1))

    print(f"[patch] applied to {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
