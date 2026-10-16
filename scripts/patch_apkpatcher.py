#!/usr/bin/env python3
"""Apply the arm/emulator aapt2 fix to the installed ApkPatcher package.

The original APKTool jar used with -e (PC emulator mode) bundles an x86 aapt2
binary that cannot run on ARM (and is fragile on other hosts too). Force the
tool to use the system aapt2 via apktool's --aapt flag.
"""

import os
import sys

import ApkPatcher

TARGET = os.path.join(
    os.path.dirname(ApkPatcher.__file__), "Utils", "Decompile_Compile.py"
)

ANCHOR = 'cmd = ["java", "-jar", APKTool_Path, "b", decompile_dir, "-o", build_dir, "-p", decompile_dir, "-f", "--copy-original"]'

FIX = ANCHOR + """

        if isEmulator:
            _aapt2 = M.shutil.which("aapt2")
            if _aapt2:
                cmd += ["--aapt", _aapt2]
"""


def main() -> int:
    with open(TARGET, encoding="utf-8") as f:
        src = f.read()

    if "isEmulator:" in src and "--aapt" in src:
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
