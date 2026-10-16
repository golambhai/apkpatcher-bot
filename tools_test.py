#!/usr/bin/env python3
"""End-to-end verification of every ApkPatcher tool/flag via the real runner.

Runs patcher/run_patch.py (exact same entry the Telegram bot uses) once per
tool/flag on a copy of a small test APK, then records success/failure.
Success marker = "Final APK" (normal) / "Anti-Split Successful" (merge mode),
because on Termux the tool always exits 1 (posix wake-unlock exit).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
PATCHER_DIR = os.path.join(BASE, "patcher")
RUNNER = os.path.join(PATCHER_DIR, "run_patch.py")
PYTHON = sys.executable
WORK = os.path.join(BASE, "data", "tools_test")
SRC_APK = os.environ.get("TEST_SRC_APK", "/storage/emulated/0/Download/sha75.apk")
SRC_APKS = os.path.join(WORK, "_template.apks")
CERT = os.path.join(WORK, "_testcert.pem")
HOME = os.path.expanduser("~")

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
CASE_TIMEOUT = 1200
WORKERS = int(os.environ.get("TEST_WORKERS", "2"))

CASES = [
    ("default",      ["-i", "{apk}"]),
    ("editor_a",     ["-i", "{apk}", "-a"]),
    ("editor_mods",  ["-i", "{apk}", "-a", "-pine", "-l", "{mod}"]),
    ("emulator_e",   ["-i", "{apk}", "-e"]),
    ("unsigned_u",   ["-i", "{apk}", "-u"]),
    ("flutter_f",    ["-i", "{apk}", "-f"]),
    ("pairip_p",     ["-i", "{apk}", "-p"]),
    ("fakeinfo_r",   ["-i", "{apk}", "-r"]),
    ("rmads",        ["-i", "{apk}", "-rmads"]),
    ("rmss",         ["-i", "{apk}", "-rmss"]),
    ("rmusb",        ["-i", "{apk}", "-rmusb"]),
    ("spoofpkg_pkg", ["-i", "{apk}", "-pkg"]),
    ("aes_A",        ["-i", "{apk}", "-A"]),
    ("aes_A_s",      ["-i", "{apk}", "-A", "-s"]),
    ("algo_A2",      ["-i", "{apk}", "-A2"]),
    ("tg_t",         ["-i", "{apk}", "-t"]),
    ("pine",         ["-i", "{apk}", "-pine"]),
    ("pine_mods",    ["-i", "{apk}", "-pine", "-l", "{mod}"]),
    ("android_id_D", ["-i", "{apk}", "-D", "7e9f51f096bd5c83"]),
    ("purchase_P",   ["-i", "{apk}", "-P"]),
    ("skip",         ["-i", "{apk}", "-skip", "getAcceptedIssuers"]),
    ("certs_c",      ["-i", "{apk}", "-c", "{cert}"]),
    ("merge_m",      ["-m", "{apks}"]),
    ("corex_px",     ["-i", "{apks}", "-p", "-x"]),
]

MARKERS = [
    "Final APK",
    "Anti-Split Successful",
    "Sign Successful",
    "Decompile Successful",
    "Pine HooK",
    "Recompile Successful",
]

RESULTS = {}
LOCK = threading.Lock()


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def prepare():
    os.makedirs(WORK, exist_ok=True)
    if not os.path.isfile(SRC_APK):
        sys.exit(f"test apk missing: {SRC_APK}")

    shutil.copy(SRC_APK, os.path.join(WORK, "_base.apk"))
    with open(os.path.join(WORK, "_base.apk"), "rb") as f:
        data = f.read()
    import zipfile

    with zipfile.ZipFile(SRC_APKS, "w", zipfile.ZIP_STORED) as z:
        z.writestr("base.apk", data)
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", os.path.join(WORK, "_key.pem"), "-out", CERT,
            "-days", "365", "-subj", "/CN=tools-test-ca",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def cleanup_leftovers(name: str):
    for suffix in ("_decompiled", "_SigBlock"):
        path = os.path.join(HOME, f"{name}{suffix}")
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


def run_case(name: str, raw_args: list, slot: int):
    apk = os.path.join(WORK, f"{name}.apk")
    apks = os.path.join(WORK, f"{name}.apks")
    mod = os.path.join(WORK, f"{name}_mod.apk")
    shutil.copy(os.path.join(WORK, "_base.apk"), apk)
    shutil.copy(SRC_APKS, apks)
    shutil.copy(os.path.join(WORK, "_base.apk"), mod)

    args = [
        a.format(apk=apk, apks=apks, mod=mod, cert=CERT) for a in raw_args
    ]
    log_path = os.path.join(WORK, f"{name}.log")

    start = time.time()
    rc = None
    timed_out = False
    try:
        with open(log_path, "wb") as logf:
            proc = subprocess.Popen(
                [PYTHON, "-u", RUNNER, *args],
                stdout=logf,
                stderr=subprocess.STDOUT,
                cwd=PATCHER_DIR,
                env={**os.environ, "JAVA_TOOL_OPTIONS": os.environ.get("JAVA_TOOL_OPTIONS", "-Xmx640m")},
            )
            try:
                rc = proc.wait(timeout=CASE_TIMEOUT)
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.kill()
                rc = proc.wait()
    except Exception as e:
        rc = f"spawn-error: {e}"
    duration = time.time() - start

    try:
        with open(log_path, "rb") as f:
            text = strip_ansi(f.read().decode("utf-8", errors="ignore"))
    except OSError:
        text = ""

    merge_only = raw_args[0] == "-m"
    out = apks.rsplit(".", 1)[0] + ".apk" if merge_only else apk.replace(".apk", "_Patched.apk")

    if merge_only:
        marker_ok = "Anti-Split Successful" in text
    else:
        marker_ok = "Final APK" in text
    ok = (
        not timed_out
        and marker_ok
        and os.path.isfile(out)
        and os.path.getsize(out) > 0
    )

    found = [m for m in MARKERS if m in text]
    tail = "\n".join([ln for ln in text.splitlines() if ln.strip()][-6:])

    cleanup_leftovers(name)
    for leftover in (apk, apks, mod):
        try:
            os.remove(leftover)
        except OSError:
            pass

    with LOCK:
        RESULTS[name] = {
            "ok": bool(ok),
            "rc": rc,
            "timeout": timed_out,
            "secs": round(duration, 1),
            "out_size": os.path.getsize(out) if os.path.isfile(out) else 0,
            "markers": found,
            "tail": tail,
            "log": log_path,
        }
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"[{status}] {name} ({duration:.0f}s, rc={rc})", flush=True)
        if not ok:
            print(f"    markers={found}", flush=True)
            for ln in tail.splitlines():
                print(f"    | {ln}", flush=True)


def main():
    prepare()
    only = set(sys.argv[1:])
    queue = [c for c in CASES if not only or c[0] in only]
    queue_lock = threading.Lock()

    def worker(slot: int):
        while True:
            with queue_lock:
                if not queue:
                    return
                name, args = queue.pop(0)
            print(f"[slot{slot}] ▶ {name}", flush=True)
            try:
                run_case(name, args, slot)
            except Exception as e:
                with LOCK:
                    RESULTS[name] = {"ok": False, "error": str(e)}
                print(f"[❌ FAIL] {name} — harness error: {e}", flush=True)

    threads = [threading.Thread(target=worker, args=(i + 1,)) for i in range(WORKERS)]
    t0 = time.time()
    print(f"=== ApkPatcher tools verification — {len(CASES)} cases, {WORKERS} workers ===", flush=True)
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = time.time() - t0

    passed = sum(1 for r in RESULTS.values() if r.get("ok"))
    failed = [n for n, r in RESULTS.items() if not r.get("ok")]
    report = {
        "total": len(CASES),
        "passed": passed,
        "failed": failed,
        "elapsed_secs": round(total, 1),
        "results": RESULTS,
    }
    report_path = os.path.join(WORK, "report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n══════════════════════════════", flush=True)
    print(f"TOTAL {len(CASES)} | PASS {passed} | FAIL {len(failed)} | {total/60:.1f} min", flush=True)
    if failed:
        print("Failed: " + ", ".join(failed), flush=True)
    print(f"Report: {report_path}", flush=True)


if __name__ == "__main__":
    main()
