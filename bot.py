#!/usr/bin/env python3
"""ApkPatcher Telegram Bot - full wrapper around ApkPatcherX (ApkPatcher CLI)."""

import asyncio
import html
import json
import logging
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN environment variable is required")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PATCHER_DIR = os.path.join(BASE_DIR, "patcher")
RUNNER = os.path.join(PATCHER_DIR, "run_patch.py")
JOBS_DIR = os.path.join(BASE_DIR, "data", "jobs")
LOGS_DIR = os.path.join(BASE_DIR, "data", "logs")
PYTHON = sys.executable

SHARED_BASE = os.environ.get("SHARED_BASE", "/storage/emulated/0/Download/ApkPatcherBot")
INBOX_DIR = os.path.join(SHARED_BASE, "input")
OUTBOX_DIR = os.path.join(SHARED_BASE, "output")

WEB_HOST = os.environ.get("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("WEB_PORT", "8799"))
WEB_ENABLED = os.environ.get("WEB_DISABLE") != "1"
TOKENS_FILE = os.path.join(BASE_DIR, "data", "webtokens.json")
WEB_TOKENS: dict = {}
CHAT_TOKENS: dict = {}
SCAN_FILES: dict = {}

TG_DOWNLOAD_LIMIT = 19 * 1024 * 1024
TG_UPLOAD_LIMIT = 49 * 1024 * 1024

LOCAL_API = os.environ.get("LOCAL_API") == "1"
LOCAL_API_URL = os.environ.get("LOCAL_API_URL", "http://127.0.0.1:8081/bot")
if LOCAL_API:
    TG_DOWNLOAD_LIMIT = 1990 * 1024 * 1024
    TG_UPLOAD_LIMIT = 1990 * 1024 * 1024

APK_EXTS = {".apk", ".apks", ".apkm", ".xapk"}
SPLIT_EXTS = {".apks", ".apkm", ".xapk"}
CERT_EXTS = {".pem", ".crt", ".cert", ".der"}

ALLOWED_USERS = {
    int(x)
    for x in os.environ.get("ALLOWED_USERS", "").replace(";", ",").split(",")
    if x.strip().isdigit()
}

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

TOGGLES = [
    ("a", "APKEditor"),
    ("e", "PC Emulator"),
    ("u", "Unsigned APK"),
    ("f", "Flutter SSL"),
    ("p", "Pairip"),
    ("x", "CoreX (-p)"),
    ("r", "Fake Device Info"),
    ("rmads", "Remove Ads"),
    ("rmss", "Bypass Screenshot"),
    ("rmusb", "Bypass USB Debug"),
    ("pkg", "Spoof PKG Detect"),
    ("A", "AES Logs"),
    ("A2", "Algorithm Logs"),
    ("s", "Separate AES Dex (-A)"),
    ("t", "TG / Plus Patch"),
    ("P", "Purchase / Paid"),
    ("pine", "Pine Hook"),
]

BOOL_FLAG_ORDER = ["a", "e", "u", "f", "p", "x", "r", "rmads", "rmss", "rmusb", "pkg", "A", "A2", "s", "t", "P"]

TOO_BIG_TEXT = (
    "⚠️ ফাইলটা Telegram Bot API এর ডাউনলোড লিমিট (20MB) এর চেয়ে বড়।\n"
    "Telegram নিজেই এই লিমিট দেয় — বট দিয়ে ২০MB+ সাইজ পাঠানো/নেওয়া যায় না।\n\n"
    "✅ <b>লিমিট ছাড়া ৩টি উপায়:</b>\n\n"
    "1️⃣ 🌐 <b>Local Web Upload</b> (সবচেয়ে সহজ):\n"
    "   এই চ্যাটে <code>/web</code> দিন → লিংক আসবে → ফোনের ব্রাউজারে খুলে যত বড় ফাইল হোক আপলোড করুন।\n\n"
    "2️⃣ 📂 <b>Folder পদ্ধতি</b>:\n"
    "   ফাইল ম্যানেজার দিয়ে APK টা এখানে কপি করুন —\n"
    "   <code>/storage/emulated/0/Download/ApkPatcherBot/input/</code>\n"
    "   তারপর <code>/scan</code> দিন।\n\n"
    "3️⃣ 🔗 <b>Link পদ্ধতি</b>: <code>/url &lt;direct-link&gt;</code> — বট নিজে নামিয়ে নেবে।"
)

if LOCAL_API:
    TOO_BIG_TEXT = (
        "⚠️ ফাইলটা 2GB এর চেয়ে বড় — এটা Telegram-এর সর্বোচ্চ ফাইল সাইজ।\n\n"
        "বিকল্প: <code>/url &lt;direct-link&gt;</code> — লিংক দিলে বট নিজে নামিয়ে নেবে।"
    )

LIMIT_NOTE = (
    "♾️ <b>Local Bot API server চালু আছে — Telegram-এ সরাসরি ~2GB পর্যন্ত ফাইল পাঠাতে পারবেন!</b>\n\n"
    if LOCAL_API
    else "⚠️ সরাসরি পাঠানোর লিমিট: ইনপুট ২০MB / আউটপুট ৫০MB (Telegram এর নিয়ম)। বড় ফাইলের জন্য /web, /scan, /url।\n\n"
)

HELP_TEXT = (
    "🛠️ <b>ApkPatcher Telegram Bot</b>\n"
    "ApkPatcherX CLI এর সম্পূর্ণ ফিচার বটে।\n\n"
    + (
        "📤 <b>ব্যবহারবিধি:</b> যেকোনো <b>.apk / .apks / .apkm / .xapk</b> সরাসরি পাঠান (২GB পর্যন্ত!)\n"
        if LOCAL_API
        else "📤 <b>ব্যবহারবিধি (ছোট ফাইল ≤20MB):</b>\n"
    )
    + "1️⃣ ফাইল পাঠান\n"
    "2️⃣ আসা মেনু থেকে দরকারি patch গুলো toggle করুন\n"
    "3️⃣ <b>▶️ START PATCH</b> চাপুন\n"
    "4️⃣ Live লগ আর patched APK ফেরত পাবেন\n\n"
    + (
        "♾️ <b>বড় ফাইল (কোনো MB লিমিট নেই):</b>\n"
        "🌐 <code>/web</code> — ফোনের ব্রাউজারে আপলোড লিংক (GB সাইজও চলবে)\n"
        "📂 <code>/scan</code> — <code>/sdcard/Download/ApkPatcherBot/input/</code> এ ফাইল কপি করে scan\n"
        "🔗 <code>/url &lt;link&gt;</code> — ডাইরেক্ট লিংক থেকে নিজে ডাউনলোড\n"
        "📤 patched APK সবসময় <code>/sdcard/Download/ApkPatcherBot/output/</code> এ জমা হয়।\n\n"
        if WEB_ENABLED
        else "♾️ <b>বড় ফাইল:</b> সরাসরি Telegram-এ ২GB পর্যন্ত পাঠান (Local Bot API server চালু আছে)।\n"
        "🔗 <code>/url &lt;link&gt;</code> — ডাইরেক্ট লিংক থেকেও APK নামাতে পারবেন।\n"
        "📤 patched APK সরাসরি Telegram-এ ফেরত আসে।\n\n"
    )
    + "⚠️ ডিফল্টে সবসময় <b>VPN &amp; SSL Bypass</b> apply হয় (আলাদা প্যাচ না দিলে)।\n\n"
    "⚡ <b>Special flags:</b>\n"
    "🔑 <b>Android ID</b> — 16 digit ID হুক (One Device Login Bypass)\n"
    "⏭️ <b>Skip Patch</b> — e.g. <code>getAcceptedIssuers</code>\n"
    "📜 <b>Certificates</b> — আপনার MITM cert (.pem/.crt) সিলেক্ট করতে extra ফাইল পাঠান\n"
    "🧩 <b>Modules</b> — Pine Hook এর জন্য Xposed/LSPosed module .apk পাঠান\n"
    "🔀 <b>Merge Only</b> — .apks/.xapk শুধু merge করে APK বানায়\n\n"
    "📌 <b>Commands:</b>\n"
    + (
        "/web — লিমিট-ফ্রি আপলোড লিংক\n"
        "/scan — input ফোল্ডার থেকে ফাইল বাছুন\n"
        if WEB_ENABLED
        else ""
    )
    + "/url — লিংক থেকে APK নামান\n"
    "/flags — সব flag এর লিস্ট ও ব্যাখ্যা\n"
    "/tools — সব tool &amp; flag এর সম্পূর্ণ গাইড\n"
    "/credits — ক্রেডিট\n"
    "/status — queue স্ট্যাটাস\n"
    "/cancel — চলমান patch বাতিল\n"
    "/new — নতুন সেশন (আগের ফাইল বাদ)\n"
    "/clean — পুরনো job ফাইল মুছে ফেলুন\n\n"
    "⚠️ <b>মনে রাখবেন:</b> <code>-rmads / -r / -A / -A2 / -t / -pine</code> দিলে tool এর নিজস্ব লজিক অনুযায়ী SSL/VPN smali patch apply হবে না।\n"
    "🛡️ শুধু নিজের APK/নিজের টেস্টে ব্যবহার করুন।"
)

FLAGS_TEXT = (
    "🛠️ <b>ApkPatcher — সব Tools &amp; Flags</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "📥 <b>Main Modes:</b>\n"
    "• ফাইল পাঠান → Smali Patcher (ডিফল্ট: <b>VPN &amp; SSL Bypass</b>)\n"
    "• 🔀 <b>-m</b> — Merge Only (.apks/.apkm/.xapk → এক APK)\n"
    "• 📜 <b>-C</b> — Credits (<code>/credits</code>)\n"
    "• ❓ <b>-h / -O</b> — Help / সব flag guide (<code>/help</code>)\n\n"
    "🧰 <b>Decompile &amp; Sign Tools:</b>\n"
    "• 🧩 <b>-a</b> — APKEditor দিয়ে decompile (ডিফল্ট APKTool)\n"
    "• 🖥️ <b>-e</b> — PC emulator এর জন্য (আলাদা APKTool)\n"
    "• 📦 <b>-u</b> — unsigned APK রাখে (sign ছাড়া output)\n"
    "• 📜 <b>-c cert1 cert2…</b> — নিজের CA cert embed (HttpCanary/Reqable/ProxyPin)\n\n"
    "🔐 <b>SSL / VPN / Pairip Tools:</b>\n"
    "• ♻️ ডিফল্ট — VPN &amp; SSL Bypass (Network Security Config)\n"
    "• 🦋 <b>-f</b> — Flutter SSL Bypass\n"
    "• 🛡️ <b>-p</b> — Pairip SSL Bypass (unsigned — VM/Multi App এ ইনস্টল করুন)\n"
    "• 🪝 <b>-p -x</b> — Pairip CoreX Hook (শুধু arm64, split input)\n\n"
    "📊 <b>Inject &amp; Spoof Tools:</b>\n"
    "• 🔐 <b>-A</b> — AES logs inject (MT Logs)\n"
    "• 🗂️ <b>-A -s</b> — আলাদা AES.smali dex\n"
    "• 🧮 <b>-A2</b> — Algorithm logs inject\n"
    "• 🔑 <b>-D &lt;16hex&gt;</b> — Android ID hook (One Device Login Bypass)\n"
    "• 🎭 <b>-r</b> — Fake/Random device info\n"
    "• 🎭 <b>-r -D &lt;16hex&gt;</b> — custom Android ID দিয়ে spoof\n\n"
    "🚫 <b>Bypass Tools:</b>\n"
    "• 🚫 <b>-rmads</b> — Ads bypass\n"
    "• 📸 <b>-rmss</b> — Screenshot restriction bypass\n"
    "• 🔌 <b>-rmusb</b> — USB debugging restriction bypass\n"
    "• 💳 <b>-P</b> — Purchase / Paid / Price bypass\n"
    "• 🕵️ <b>-pkg</b> — Package detection spoof (Dex/Manifest/Res)\n\n"
    "✈️ <b>Extra Tools:</b>\n"
    "• ✈️ <b>-t</b> — Telegram / Plus patch\n"
    "• 🌲 <b>-pine</b> — Pine Hook (Xposed/LSP module support)\n"
    "• 🧩 <b>-pine -l mod.apk</b> — Pine Hook + module embed\n"
    "• ⏭️ <b>-skip name1 name2</b> — নির্দিষ্ট smali patch স্কিপ (e.g. getAcceptedIssuers)\n\n"
    "🤖 <b>Bot নিজের Tools:</b>\n"
    "• 📊 Live log streaming + queue + <code>/cancel</code>\n"
    + (
        "• 🌐 <code>/web</code> — ব্রাউজার থেকে যেকোনো সাইজ আপলোড\n"
        "• 📂 <code>/scan</code> — input ফোল্ডার থেকে ফাইল বাছুন\n"
        if WEB_ENABLED
        else ""
    )
    + "• 🔗 <code>/url</code> — ডাইরেক্ট লিংক থেকে ডাউনলোড\n"
    + (
        "• 📤 Output → Telegram + <code>/sdcard/Download/ApkPatcherBot/output/</code> এ auto-save\n\n"
        if WEB_ENABLED
        else "• 📤 Output সরাসরি Telegram-এ ফেরত আসে (২GB পর্যন্ত)\n\n"
    )
    + "⚠️ <b>মনে রাখবেন:</b> <code>-A / -A2 / -r / -rmads / -t / -pine</code> এর যেকোনোটা দিলে tool শুধু সেটাই apply করে (ডিফল্ট SSL/NSC বাদ) — CLI এর exact আচরণ।\n"
    "🛡️ শুধু নিজের APK/নিজের টেস্টে ব্যবহার করুন।"
)


def esc(text: str) -> str:
    return html.escape(str(text), quote=False)


def sanitize_name(name: str) -> str:
    name = os.path.basename(name)
    name = re.sub(r"[^A-Za-z0-9._\-]+", "_", name)
    name = re.sub(r"_{2,}", "_", name).strip("._") or "app.apk"
    return name


def human_size(num) -> str:
    num = float(num or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.1f} {unit}"
        num /= 1024


def clean_log_tail(path: str, max_chars: int = 3200, last_lines: int = 20) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            data = f.read()
    except FileNotFoundError:
        return "(লগ ফাইল পাওয়া যায়নি)"
    lines = []
    for raw in data.replace("\r\n", "\n").split("\n"):
        lines.append(raw.split("\r")[-1])
    text = ANSI_RE.sub("", "\n".join(lines))
    text = "".join(c if (c == "\n" or c == "\t" or ord(c) >= 32) else "" for c in text)
    tail = [ln for ln in text.splitlines() if ln.strip()][-last_lines:]
    out = "\n".join(tail)
    if len(out) > max_chars:
        out = "…" + out[-max_chars:]
    return out or "(এখনো কোনো আউটপুট নেই)"


class Session:
    def __init__(self, chat_id: int):
        self.uid = uuid.uuid4().hex[:8]
        self.chat_id = chat_id
        self.dir = os.path.join(JOBS_DIR, f"{int(time.time())}_{self.uid}")
        os.makedirs(self.dir, exist_ok=True)
        self.input_path = None
        self.name = None
        self.size = 0
        self.flags = set()
        self.android_id = None
        self.skip = []
        self.certs = []
        self.modules = []
        self.merge = False
        self.await_mode = None
        self.panel_msg_id = None

    @property
    def ext(self) -> str:
        return os.path.splitext(self.name or "")[1].lower()


class Job:
    def __init__(self, job_id: str, chat_id: int, session: Session, args: list, merge_only: bool):
        self.id = job_id
        self.chat_id = chat_id
        self.input_path = session.input_path
        self.args = args
        self.merge_only = merge_only
        self.log_path = os.path.join(LOGS_DIR, f"job_{job_id}.log")
        self.msg_id = None
        self.status = "queued"
        self.proc = None
        self.started = None
        self.finished = None

    @property
    def out_path(self) -> str:
        base, _ = os.path.splitext(self.input_path)
        return base + (".apk" if self.merge_only else "_Patched.apk")


SESSIONS: dict = {}
CHAT_SESSION: dict = {}
JOBS: dict = {}
QUEUE: asyncio.Queue = asyncio.Queue()


def get_session(chat_id: int):
    uid = CHAT_SESSION.get(chat_id)
    return SESSIONS.get(uid) if uid else None


def purge_session(chat_id: int, remove_dir: bool = False):
    s = get_session(chat_id)
    if not s:
        return
    CHAT_SESSION.pop(chat_id, None)
    SESSIONS.pop(s.uid, None)
    if remove_dir:
        shutil.rmtree(s.dir, ignore_errors=True)


def ensure_shared_dirs():
    for d in (INBOX_DIR, OUTBOX_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception as e:
            print(f"[shared] cannot create {d}: {e}", flush=True)


def load_tokens():
    try:
        with open(TOKENS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for token, chat in data.items():
            WEB_TOKENS[token] = int(chat)
            CHAT_TOKENS[int(chat)] = token
    except Exception:
        pass


def save_tokens():
    try:
        os.makedirs(os.path.dirname(TOKENS_FILE), exist_ok=True)
        with open(TOKENS_FILE, "w", encoding="utf-8") as f:
            json.dump({t: c for t, c in WEB_TOKENS.items()}, f)
    except Exception as e:
        print(f"[tokens] save failed: {e}", flush=True)


def get_token(chat_id: int) -> str:
    token = CHAT_TOKENS.get(chat_id)
    if not token:
        token = secrets.token_urlsafe(9)
        WEB_TOKENS[token] = chat_id
        CHAT_TOKENS[chat_id] = token
        save_tokens()
    return token


def web_link(path: str) -> str:
    base = os.environ.get("PUBLIC_BASE_URL")
    if base:
        return base.rstrip("/") + path
    return f"http://{WEB_HOST}:{WEB_PORT}{path}"


def publish_output(job) -> str:
    try:
        ensure_shared_dirs()
        name = os.path.basename(job.out_path)
        dest = os.path.join(OUTBOX_DIR, name)
        if os.path.exists(dest):
            base, ext = os.path.splitext(name)
            dest = os.path.join(OUTBOX_DIR, f"{base}_{job.id}{ext}")
        if os.path.dirname(os.path.abspath(job.out_path)) == os.path.abspath(INBOX_DIR):
            shutil.move(job.out_path, dest)
        else:
            shutil.copy2(job.out_path, dest)
        return dest
    except Exception as e:
        print(f"[publish] {e}", flush=True)
        return ""


def busy_jobs(chat_id: int) -> list:
    return [
        j
        for j in JOBS.values()
        if j.chat_id == chat_id and j.status in ("running", "queued")
    ]


async def activate_session(bot, chat_id: int, s: Session, input_path: str, name: str, size=None):
    if busy_jobs(chat_id):
        raise RuntimeError("এখন একটি job চলছে — শেষ হলে আবার চেষ্টা করুন (বা /cancel)।")
    old = get_session(chat_id)
    if old and old.uid != s.uid:
        SESSIONS.pop(old.uid, None)
        shutil.rmtree(old.dir, ignore_errors=True)
    s.input_path = input_path
    s.name = name
    s.size = size if size is not None else os.path.getsize(input_path)
    SESSIONS[s.uid] = s
    CHAT_SESSION[chat_id] = s.uid
    panel = await bot.send_message(
        chat_id, panel_text(s), reply_markup=panel_keyboard(s), parse_mode=ParseMode.HTML
    )
    s.panel_msg_id = panel.message_id
    await bot.send_message(
        chat_id,
        "📁 প্যাচ শেষে আউটপুট: <code>" + esc(OUTBOX_DIR) + "</code>\n"
        "🌐 অথবা /web লিংক থেকে ডাউনলোড করতে পারবেন।",
        parse_mode=ParseMode.HTML,
        disable_notification=True,
    )
    return s


def scan_inbox() -> list:
    ensure_shared_dirs()
    files = []
    try:
        for name in os.listdir(INBOX_DIR):
            p = os.path.join(INBOX_DIR, name)
            if not os.path.isfile(p):
                continue
            if os.path.splitext(name)[1].lower() not in APK_EXTS:
                continue
            try:
                files.append((p, os.path.getsize(p), os.path.getmtime(p)))
            except OSError:
                continue
    except Exception as e:
        print(f"[scan] {e}", flush=True)
    files.sort(key=lambda x: x[2], reverse=True)
    return [(p, size) for p, size, _ in files]


def build_args(s: Session) -> list:
    if s.merge:
        base = ["-m", s.input_path]
    else:
        base = ["-i", s.input_path]
        for key in BOOL_FLAG_ORDER:
            if key in s.flags:
                base.append(f"-{key}")
        if s.android_id:
            base += ["-D", s.android_id]
        if "pine" in s.flags:
            base.append("-pine")
            if s.modules:
                base += ["-l", *s.modules]
        else:
            if s.certs:
                base += ["-c", *s.certs]
        if s.skip:
            base += ["-skip", *s.skip]
    return [PYTHON, "-u", RUNNER, *base]


def panel_text(s: Session) -> str:
    active = " ".join("-" + k for k in BOOL_FLAG_ORDER if k in s.flags)
    if "pine" in s.flags and "pine" not in BOOL_FLAG_ORDER:
        active = (active + " -pine").strip()
    if s.android_id:
        active = (active + " -D").strip()
    if s.merge:
        active = "-m (merge only)"
    if not active:
        active = "ডিফল্ট → VPN & SSL Bypass"
    return (
        f"📦 <b>{esc(s.name)}</b> ({human_size(s.size)})\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔧 Active: <code>{esc(active)}</code>\n"
        f"🔑 Android ID: <code>{esc(s.android_id or '—')}</code>\n"
        f"⏭️ Skip: <code>{esc(' '.join(s.skip) or '—')}</code>\n"
        f"📜 Certs: <b>{len(s.certs)}</b>   |   🧩 Modules: <b>{len(s.modules)}</b>\n"
        f"🔀 Merge Only: {'✅' if s.merge else '⬜'}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "নিচের বাটন থেকে patch বেছে নিন 👇"
    )


def panel_keyboard(s: Session) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(TOGGLES), 2):
        row = []
        for key, label in TOGGLES[i : i + 2]:
            mark = "✅" if key in s.flags else "⬜"
            row.append(InlineKeyboardButton(f"{mark} {label}", callback_data=f"{s.uid}|t|{key}"))
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                f"🔑 ID: {s.android_id or 'set'}", callback_data=f"{s.uid}|id"
            ),
            InlineKeyboardButton(
                f"⏭️ Skip ({len(s.skip)})", callback_data=f"{s.uid}|skip"
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(f"📜 Certs ({len(s.certs)})", callback_data=f"{s.uid}|certs"),
            InlineKeyboardButton(f"🧩 Mods ({len(s.modules)})", callback_data=f"{s.uid}|mods"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                f"🔀 Merge Only {'✅' if s.merge else '⬜'}", callback_data=f"{s.uid}|merge"
            ),
            InlineKeyboardButton("♻️ Reset", callback_data=f"{s.uid}|reset"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton("📖 সব Tools", callback_data=f"{s.uid}|tools"),
            InlineKeyboardButton("❓ Help", callback_data=f"{s.uid}|help"),
        ]
    )
    rows.append([InlineKeyboardButton("▶️ START PATCH", callback_data=f"{s.uid}|start")])
    return InlineKeyboardMarkup(rows)


async def edit_panel(context: ContextTypes.DEFAULT_TYPE, s: Session):
    if not s.panel_msg_id:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=s.chat_id,
            message_id=s.panel_msg_id,
            text=panel_text(s),
            reply_markup=panel_keyboard(s),
            parse_mode=ParseMode.HTML,
        )
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
        try:
            msg = await context.bot.send_message(
                s.chat_id,
                panel_text(s),
                reply_markup=panel_keyboard(s),
                parse_mode=ParseMode.HTML,
            )
            s.panel_msg_id = msg.message_id
        except TelegramError:
            pass
    except TelegramError:
        pass


async def job_status_edit(bot, job: Job, header: str, tail: bool = True):
    body = header
    if tail:
        body += f"\n\n<pre>{esc(clean_log_tail(job.log_path))}</pre>"
    try:
        await bot.edit_message_text(
            chat_id=job.chat_id, message_id=job.msg_id, text=body, parse_mode=ParseMode.HTML
        )
    except BadRequest:
        pass
    except TelegramError:
        pass


def validate_session(s: Session) -> list:
    errs = []
    if s.merge and s.ext not in SPLIT_EXTS:
        errs.append("🔀 Merge Only শুধু .apks / .apkm / .xapk এর জন্য")
    if "x" in s.flags and "p" not in s.flags:
        errs.append("🪝 CoreX (-x) এর সাথে Pairip (-p) সিলেক্ট করতে হবে")
    if "x" in s.flags and s.ext not in SPLIT_EXTS:
        errs.append("🪝 CoreX (-x) শুধু split (.apks/.apkm/.xapk) input এ কাজ করে")
    if "s" in s.flags and "A" not in s.flags:
        errs.append("🗂️ Separate AES Dex (-s) এর সাথে -A সিলেক্ট করুন")
    if not s.merge and "pine" in s.flags and s.android_id:
        errs.append("🌲 Pine Hook এর সাথে Android ID একসাথে চলে না")
    return errs


async def run_job(app: Application, job: Job):
    bot = app.bot
    job.status = "running"
    job.started = time.time()
    os.makedirs(LOGS_DIR, exist_ok=True)
    logf = open(job.log_path, "wb")
    try:
        job.proc = await asyncio.create_subprocess_exec(
            *job.args,
            stdout=logf,
            stderr=asyncio.subprocess.STDOUT,
            cwd=PATCHER_DIR,
            preexec_fn=os.setsid,
        )
    except Exception as e:
        logf.close()
        job.status = "failed"
        await job_status_edit(bot, job, f"❌ Job <code>{job.id}</code> শুরু করা যায়নি: {esc(e)}", tail=False)
        return

    header = f"🚀 <b>Patch চলছে…</b> <code>{job.id}</code>"
    await job_status_edit(bot, job, header)

    while True:
        try:
            await asyncio.wait_for(job.proc.wait(), timeout=8)
            break
        except asyncio.TimeoutError:
            await job_status_edit(bot, job, header)
    logf.close()

    job.finished = time.time()
    duration = job.finished - job.started
    rc = job.proc.returncode

    base = os.path.splitext(job.input_path)[0]
    for leftover in (f"{base}_decompiled", f"{base}_SigBlock"):
        if os.path.isdir(leftover):
            shutil.rmtree(leftover, ignore_errors=True)

    if job.status == "cancelled":
        await job_status_edit(bot, job, f"🚫 Job <code>{job.id}</code> বাতিল হয়েছে।", tail=False)
        return

    out = job.out_path
    log_ok = False
    try:
        with open(job.log_path, "rb") as lf:
            raw_log = lf.read().decode("utf-8", errors="ignore")
        clean = ANSI_RE.sub("", raw_log)
        log_ok = ("Final APK" in clean) or (
            job.merge_only and "Anti-Split Successful" in clean
        )
    except OSError:
        pass
    ok = (rc == 0 or log_ok) and os.path.isfile(out) and os.path.getsize(out) > 0

    if ok:
        job.status = "done"
        outsize = os.path.getsize(out)
        dest = publish_output(job) if WEB_ENABLED else ""
        src = dest if dest else out
        token = get_token(job.chat_id)
        lines = [
            f"✅ <b>Patch সফল!</b> <code>{job.id}</code>",
            f"⏱️ {duration:.1f}s | 📦 {human_size(outsize)}",
        ]
        if dest:
            lines.append(f"📁 Storage: <code>{esc(dest)}</code>")
            lines.append(
                f"🌐 ডাউনলোড: {web_link('/d/' + token + '/' + urllib.parse.quote(os.path.basename(dest)))}"
            )
        elif WEB_ENABLED:
            lines.append(f"📁 ফাইল: <code>{esc(out)}</code>")
        sent_tg = False
        if outsize <= TG_UPLOAD_LIMIT:
            lines.append("📨 Telegram এও পাঠানো হচ্ছে…")
        else:
            lines.append(f"⚠️ ফাইলটা {human_size(TG_UPLOAD_LIMIT)} এর চেয়ে বড় — Storage/লিংক থেকে নিন।")
        await job_status_edit(bot, job, "\n".join(lines), tail=False)
        if outsize <= TG_UPLOAD_LIMIT:
            try:
                if LOCAL_API:
                    from pathlib import Path

                    await bot.send_document(
                        chat_id=job.chat_id,
                        document=Path(src),
                        caption=f"✅ {os.path.basename(src)} | job {job.id}",
                    )
                else:
                    with open(src, "rb") as fh:
                        await bot.send_document(
                            chat_id=job.chat_id,
                            document=fh,
                            filename=os.path.basename(src),
                            caption=f"✅ {os.path.basename(src)} | job {job.id}",
                        )
                sent_tg = True
            except TelegramError as e:
                await bot.send_message(
                    job.chat_id,
                    f"⚠️ Telegram এ পাঠাতে সমস্যা: {esc(e)}",
                    parse_mode=ParseMode.HTML,
                )
        if sent_tg:
            return
    else:
        job.status = "failed"
        note = ""
        tailtext = clean_log_tail(job.log_path, max_chars=1000, last_lines=8).lower()
        if "flutter" in tailtext and "-f" not in job.args:
            note = "\n💡 এটা Flutter APK — 🦋 Flutter SSL (-f) toggle করে আবার চেষ্টা করুন।"
        elif "pairip" in tailtext and "-p" not in job.args:
            note = "\n💡 এটা Pairip APK — 🛡️ Pairip (-p) বা -p -x toggle করুন।"
        await job_status_edit(
            bot,
            job,
            f"❌ <b>Patch ব্যর্থ</b> <code>{job.id}</code> (exit {rc})\n"
            f"⏱️ {duration:.1f}s{note}",
        )
        try:
            with open(job.log_path, "rb") as fh:
                await bot.send_document(
                    chat_id=job.chat_id,
                    document=fh,
                    filename=f"job_{job.id}_full_log.txt",
                    caption="📄 সম্পূর্ণ লগ",
                )
        except TelegramError:
            pass


async def worker(app: Application):
    while True:
        job_id = await QUEUE.get()
        job = JOBS.get(job_id)
        try:
            if job is None or job.status == "cancelled":
                continue
            job.status = "running"
            queued_ahead = sum(
                1 for j in JOBS.values() if j.status == "queued" and j.id != job.id
            )
            if queued_ahead:
                await job_status_edit(
                    app.bot,
                    job,
                    f"🕒 অপেক্ষায়… queue অবস্থান ~{queued_ahead + 1}",
                    tail=False,
                )
            await run_job(app, job)
        except Exception as e:
            print(f"[worker] job {job_id} crashed: {e}", flush=True)
        finally:
            QUEUE.task_done()


def allowed(update: Update) -> bool:
    if not ALLOWED_USERS:
        return True
    user = update.effective_user
    return bool(user and user.id in ALLOWED_USERS)


async def deny(update: Update):
    user = update.effective_user
    text = (
        f"⛔ আপনি অনুমোদিত নন।\nআপনার Telegram ID: <code>{user.id if user else '?'}</code>\n"
        "অ্যাডমিনকে বলুন ALLOWED_USERS এ ID টা যোগ করতে।"
    )
    try:
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)
    except TelegramError:
        pass


def commands_list():
    return [
        BotCommand("start", "শুরু করুন"),
        BotCommand("help", "সাহায্য ও ব্যবহারবিধি"),
        BotCommand("web", "লিমিট-ফ্রি ব্রাউজার আপলোড"),
        BotCommand("scan", "input ফোল্ডার থেকে ফাইল বাছুন"),
        BotCommand("url", "লিংক থেকে APK নামান"),
        BotCommand("flags", "সব patch flag এর লিস্ট"),
        BotCommand("tools", "সব tool ও flag এর গাইড"),
        BotCommand("status", "Queue / job স্ট্যাটাস"),
        BotCommand("cancel", "চলমান patch বাতিল"),
        BotCommand("new", "নতুন সেশন শুরু"),
        BotCommand("clean", "পুরনো ফাইল মুছুন"),
        BotCommand("credits", "ক্রেডিট"),
        BotCommand("id", "আপনার Telegram ID"),
    ]


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    await update.message.reply_text(LIMIT_NOTE + HELP_TEXT, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    await update.message.reply_text(LIMIT_NOTE + HELP_TEXT, parse_mode=ParseMode.HTML)


async def cmd_flags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    await update.message.reply_text(FLAGS_TEXT, parse_mode=ParseMode.HTML)


async def cmd_tools(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    await update.message.reply_text(FLAGS_TEXT, parse_mode=ParseMode.HTML)


async def cmd_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    await update.message.reply_text(
        "💢 <b>Credits</b> 💢\n\n"
        "🦋 Flutter SSL & TG Patch — AbhiTheM0dder (@AbhiTheM0dder)\n"
        "🌲 Pine Hook — AbhiTheM0dder | 残页 (@canyie)\n"
        "🔐 MITM — Niklas Higi (apk-mitm)\n"
        "🔧 APKTool — Connor Tumbleson (@iBotPeaches)\n"
        "🧩 APKEditor — REAndroid (@kikfox)\n"
        "✍️ ApkSig — Android Tools Build\n"
        "👑 ApkPatcherX — RK_TECHNO_INDIA (@RK_TECHNO_INDIA)\n\n"
        "🛠️ Telegram Bot wrapper — আপনার জন্য বানানো",
        parse_mode=ParseMode.HTML,
    )


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 আপনার Telegram ID: <code>{update.effective_user.id}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    s = get_session(update.effective_chat.id)
    running = [j for j in JOBS.values() if j.chat_id == update.effective_chat.id and j.status == "running"]
    if running:
        return await update.message.reply_text("⚠️ আগে চলমান job শেষ/বাতিল করুন (/cancel)।")
    purge_session(update.effective_chat.id, remove_dir=True)
    await update.message.reply_text("♻️ সেশন রিসেট। নতুন APK পাঠান।")


async def cmd_clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    chat_id = update.effective_chat.id
    running = [j for j in JOBS.values() if j.chat_id == chat_id and j.status in ("running", "queued")]
    if running:
        return await update.message.reply_text("⚠️ চলমান/queue job থাকা অবস্থায় clean করা যাবে না।")
    s = get_session(chat_id)
    if s and os.path.isdir(s.dir):
        total = sum(
            os.path.getsize(os.path.join(root, f))
            for root, _, files in os.walk(s.dir)
            for f in files
            if os.path.isfile(os.path.join(root, f))
        )
        purge_session(chat_id, remove_dir=True)
        await update.message.reply_text(f"🧹 {human_size(total)} ফাইল মুছে ফেলা হয়েছে।")
    else:
        purge_session(chat_id, remove_dir=True)
        await update.message.reply_text("ℹ️ মুছে ফেলার মত কিছু নেই।")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    chat_id = update.effective_chat.id
    lines = ["📊 <b>Queue স্ট্যাটাস</b>", "━━━━━━━━━━━━━━━━━━"]
    mine = [j for j in JOBS.values() if j.chat_id == chat_id and j.status in ("running", "queued")]
    if not mine:
        lines.append("✅ আপনার কোনো চলমান job নেই।")
    for j in mine:
        tag = "🚀 চলছে" if j.status == "running" else "🕒 অপেক্ষায়"
        lines.append(f"{tag} — <code>{j.id}</code>")
    s = get_session(chat_id)
    if s and s.input_path:
        lines.append(f"\n📦 সেশন: <b>{esc(s.name)}</b>")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    chat_id = update.effective_chat.id
    cancelled = []
    for j in JOBS.values():
        if j.chat_id != chat_id:
            continue
        if j.status == "queued":
            j.status = "cancelled"
            cancelled.append(j.id)
        elif j.status == "running" and j.proc and j.proc.returncode is None:
            j.status = "cancelled"
            try:
                os.killpg(os.getpgid(j.proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            cancelled.append(j.id)
    if cancelled:
        await update.message.reply_text("🚫 বাতিল: " + ", ".join(cancelled))
    else:
        await update.message.reply_text("ℹ️ বাতিল করার মত কোনো job নেই।")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    msg = update.message
    doc = msg.document
    chat_id = update.effective_chat.id
    raw_name = doc.file_name or "file"
    ext = os.path.splitext(raw_name)[1].lower()
    s = get_session(chat_id)

    if ext in CERT_EXTS and s and s.input_path:
        await save_aux(update, context, s, "certs", raw_name, doc, "📜 Certificate")
        return
    if ext == ".apk" and s and s.await_mode == "module":
        await save_aux(update, context, s, "modules", raw_name, doc, "🧩 Module")
        return
    if ext not in APK_EXTS:
        if ext in CERT_EXTS:
            await msg.reply_text("ℹ️ আগে একটি APK পাঠান, তারপর certificate পাঠালে সেটা সেশনে যোগ হবে।")
        else:
            await msg.reply_text("❌ শুধু .apk / .apks / .apkm / .xapk / .pem / .crt / .cert সাপোর্টেড।")
        return

    if doc.file_size and doc.file_size > TG_DOWNLOAD_LIMIT:
        await msg.reply_text(TOO_BIG_TEXT, parse_mode=ParseMode.HTML)
        return

    running = [j for j in JOBS.values() if j.chat_id == chat_id and j.status in ("running", "queued")]
    if running:
        await msg.reply_text("⏳ আগের job চলছে। শেষ হলে নতুন ফাইল পাঠান (বা /cancel)।")
        return

    await msg.reply_chat_action(ChatAction.TYPING)
    new_s = Session(chat_id)
    safe = sanitize_name(raw_name)
    dest = os.path.join(new_s.dir, safe)
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(custom_path=dest)
    except (TelegramError, BadRequest):
        await msg.reply_text(TOO_BIG_TEXT, parse_mode=ParseMode.HTML)
        shutil.rmtree(new_s.dir, ignore_errors=True)
        return

    if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
        shutil.rmtree(new_s.dir, ignore_errors=True)
        return await msg.reply_text("❌ ফাইল ডাউনলোড ব্যর্থ। আবার চেষ্টা করুন।")

    try:
        await activate_session(context.bot, chat_id, new_s, dest, safe)
    except RuntimeError as e:
        shutil.rmtree(new_s.dir, ignore_errors=True)
        await msg.reply_text(f"⚠️ {esc(str(e))}", parse_mode=ParseMode.HTML)


async def save_aux(update: Update, context: ContextTypes.DEFAULT_TYPE, s: Session, kind: str, raw_name: str, doc, label: str):
    msg = update.message
    if doc.file_size and doc.file_size > TG_DOWNLOAD_LIMIT:
        return await msg.reply_text("⚠️ ফাইল 20MB এর বেশি, নেওয়া যাবে না।")
    folder = os.path.join(s.dir, kind)
    os.makedirs(folder, exist_ok=True)
    safe = sanitize_name(raw_name)
    dest = os.path.join(folder, f"{int(time.time())}_{safe}")
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(custom_path=dest)
    except TelegramError:
        return await msg.reply_text("❌ ডাউনলোড ব্যর্থ।")
    target = s.certs if kind == "certs" else s.modules
    target.append(dest)
    if kind in ("modules", "certs"):
        s.await_mode = None
    await edit_panel(context, s)
    await msg.reply_text(
        f"{label} যোগ হয়েছে ✔ এখন মোট {len(target)} টি।\n<b>{esc(safe)}</b>",
        parse_mode=ParseMode.HTML,
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    chat_id = update.effective_chat.id
    s = get_session(chat_id)
    if not s or not s.await_mode:
        return
    text = (update.message.text or "").strip()
    if s.await_mode in ("cert", "module"):
        what = "certificate (.pem/.crt)" if s.await_mode == "cert" else "module (.apk)"
        await update.message.reply_text(f"📎 এখন ফাইল হিসেবে {what} পাঠান।")
        return
    if s.await_mode == "id":
        if re.fullmatch(r"[0-9a-fA-F]{16}", text):
            s.android_id = text.lower()
            s.await_mode = None
            await edit_panel(context, s)
            await update.message.reply_text(f"🔑 Android ID সেট হয়েছে: <code>{esc(s.android_id)}</code>", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ ভুল ফরম্যাট। ১৬ digit hex দিন (e.g. <code>7e9f51f096bd5c83</code>)", parse_mode=ParseMode.HTML)
    elif s.await_mode == "skip":
        parts = [p for p in re.split(r"[\s,]+", text) if p]
        if parts:
            s.skip = parts
            s.await_mode = None
            await edit_panel(context, s)
            await update.message.reply_text("⏭️ Skip patch সেট: <code>" + esc(" ".join(parts)) + "</code>", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ কিছু লিখুন, যেমন: <code>getAcceptedIssuers</code>", parse_mode=ParseMode.HTML)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not allowed(update):
        await q.answer("⛔ অনুমোদিত নন", show_alert=True)
        return
    try:
        uid, action, *rest = q.data.split("|")
    except ValueError:
        await q.answer()
        return

    if uid == "scan":
        await handle_scan_callback(update, context, action, rest)
        return

    s = SESSIONS.get(uid)
    if not s or s.chat_id != update.effective_chat.id:
        await q.answer("⚠️ পুরনো মেনু — নতুন করে ফাইল পাঠান।", show_alert=True)
        return

    if action == "t":
        key = rest[0]
        if key in s.flags:
            s.flags.discard(key)
        else:
            s.flags.add(key)
            if key == "x":
                s.flags.add("p")
            if key == "s":
                s.flags.add("A")
        await q.answer()
        await edit_panel(context, s)
    elif action == "id":
        s.await_mode = "id"
        await q.answer()
        await context.bot.send_message(
            s.chat_id,
            "🔑 ১৬ digit Android ID পাঠান (hex), যেমন: <code>7e9f51f096bd5c83</code>\nবাতিল করতে /new",
            parse_mode=ParseMode.HTML,
        )
    elif action == "skip":
        s.await_mode = "skip"
        await q.answer()
        await context.bot.send_message(
            s.chat_id,
            "⏭️ Skip করতে চাওয়া patch এর নাম পাঠান (space/comma দিয়ে আলাদা), যেমন: <code>getAcceptedIssuers</code>",
            parse_mode=ParseMode.HTML,
        )
    elif action == "certs":
        s.await_mode = "cert"
        await q.answer()
        await context.bot.send_message(
            s.chat_id,
            "📜 আপনার MITM certificate (.pem / .crt / .cert) ফাইল পাঠান — একাধিক পাঠাতে পারেন।\n"
            "HttpCanary / Reqable / ProxyPin CA হলেই ভালো।",
            parse_mode=ParseMode.HTML,
        )
    elif action == "mods":
        s.await_mode = "module"
        await q.answer()
        await context.bot.send_message(
            s.chat_id,
            "🧩 Pine Hook এর জন্য Xposed/LSPosed module (.apk) পাঠান — একাধিক পাঠাতে পারেন।",
            parse_mode=ParseMode.HTML,
        )
    elif action == "merge":
        if s.ext in SPLIT_EXTS:
            s.merge = not s.merge
        else:
            await q.answer("⚠️ Merge Only শুধু .apks/.apkm/.xapk এ", show_alert=True)
        await edit_panel(context, s)
    elif action == "tools":
        await q.answer()
        await context.bot.send_message(
            s.chat_id, FLAGS_TEXT, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
    elif action == "help":
        await q.answer()
        await context.bot.send_message(
            s.chat_id,
            LIMIT_NOTE + HELP_TEXT,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    elif action == "reset":
        s.flags.clear()
        s.android_id = None
        s.skip = []
        s.certs = []
        s.modules = []
        s.merge = False
        s.await_mode = None
        await q.answer("♻️ Reset হয়েছে")
        await edit_panel(context, s)
    elif action == "start":
        errs = validate_session(s)
        if errs:
            await q.answer("⚠️ " + errs[0], show_alert=True)
            return
        s.await_mode = None
        job_id = uuid.uuid4().hex[:8]
        job = Job(job_id, s.chat_id, s, build_args(s), s.merge)
        JOBS[job_id] = job
        msg = await context.bot.send_message(
            s.chat_id, f"🕒 Job queued: <code>{job_id}</code>", parse_mode=ParseMode.HTML
        )
        job.msg_id = msg.message_id
        await QUEUE.put(job_id)
        await q.answer("▶️ শুরু হচ্ছে…")
        await edit_panel(context, s)
    else:
        await q.answer()


def scan_listing_keyboard(chat_id: int):
    files = scan_inbox()
    SCAN_FILES[chat_id] = files
    rows = []
    for idx, (p, size) in enumerate(files[:12]):
        label = f"📦 {os.path.basename(p)} ({human_size(size)})"
        if len(label) > 58:
            label = label[:55] + "…"
        rows.append([InlineKeyboardButton(label, callback_data=f"scan|use|{idx}")])
    rows.append([InlineKeyboardButton("🔄 Refresh", callback_data="scan|refresh|0")])
    return files, InlineKeyboardMarkup(rows)


async def handle_scan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, rest: list):
    q = update.callback_query
    chat_id = update.effective_chat.id
    if action == "refresh":
        files, kb = scan_listing_keyboard(chat_id)
        if not files:
            await q.answer("📂 input ফোল্ডারে কোনো APK নেই", show_alert=True)
            return
        await q.edit_message_text(
            "📂 <b>input ফোল্ডারের ফাইল</b>\nবেছে নিন 👇",
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )
        return
    if action == "use":
        try:
            idx = int(rest[0])
        except (ValueError, IndexError):
            await q.answer()
            return
        files = SCAN_FILES.get(chat_id) or []
        if idx >= len(files) or not os.path.isfile(files[idx][0]):
            await q.answer("⚠️ লিস্ট পুরনো — /scan আবার দিন", show_alert=True)
            return
        path, size = files[idx]
        s = Session(chat_id)
        try:
            await activate_session(context.bot, chat_id, s, path, os.path.basename(path), size)
            await q.answer("✅ সেশন তৈরি")
        except RuntimeError as e:
            shutil.rmtree(s.dir, ignore_errors=True)
            await q.answer(f"⚠️ {e}", show_alert=True)
        return
    await q.answer()


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    chat_id = update.effective_chat.id
    if busy_jobs(chat_id):
        return await update.message.reply_text("⏳ আগের job চলছে। শেষ হলে আবার /scan দিন।")
    files, kb = scan_listing_keyboard(chat_id)
    if not files:
        return await update.message.reply_text(
            "📂 <b>input ফোল্ডারে কোনো APK নেই</b>\n\n"
            "ফাইল ম্যানেজার দিয়ে APK কপি করুন এখানে:\n"
            f"<code>{esc(INBOX_DIR)}</code>\n\n"
            "তারপর আবার <code>/scan</code> দিন।",
            parse_mode=ParseMode.HTML,
        )
    await update.message.reply_text(
        "📂 <b>input ফোল্ডারের ফাইল</b>\nবেছে নিন 👇 (যেকোনো সাইজ চলবে)",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )


async def cmd_web(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    if not context.application.bot_data.get("web_ok"):
        return await update.message.reply_text(
            "❌ Web server চালু হয়নি (port busy হতে পারে)।\n"
            f"বিকল্প: ফাইল কপি করুন <code>{esc(INBOX_DIR)}</code> এ, তারপর /scan",
            parse_mode=ParseMode.HTML,
        )
    token = get_token(update.effective_chat.id)
    await update.message.reply_text(
        "🌐 <b>লিমিট-ফ্রি আপলোড (যেকোনো সাইজ)</b>\n\n"
        f"📤 ফোনের ব্রাউজারে আপলোড লিংক:\n{web_link('/u/' + token)}\n\n"
        f"📁 ফাইল/আউটপুট ব্রাউজার:\n{web_link('/f/' + token)}\n\n"
        "ℹ️ লিংকগুলো শুধু এই ডিভাইসে (127.0.0.1) কাজ করে। একই পেজ থেকে APK + "
        "cert (.pem/.crt) + module (.apk) একসাথে দিতে পারবেন।",
        parse_mode=ParseMode.HTML,
    )


async def cmd_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    chat_id = update.effective_chat.id
    if not context.args:
        return await update.message.reply_text(
            "ব্যবহার: <code>/url https://example.com/app.apk</code>",
            parse_mode=ParseMode.HTML,
        )
    url = context.args[0]
    if not url.lower().startswith(("http://", "https://")):
        return await update.message.reply_text("❌ http/https ডাইরেক্ট লিংক দিন।")
    if busy_jobs(chat_id):
        return await update.message.reply_text("⏳ আগের job চলছে। শেষ হলে আবার চেষ্টা করুন।")
    status = await update.message.reply_text("⬇️ ডাউনলোড শুরু হচ্ছে…")
    asyncio.create_task(download_url(context.bot, chat_id, url, status.message_id))


async def download_url(bot, chat_id: int, url: str, msg_id: int):
    s = Session(chat_id)
    progress = {"done": 0, "total": 0}

    def _download(dest):
        import requests

        with requests.get(
            url,
            stream=True,
            timeout=60,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Android) ApkPatcherBot"},
        ) as r:
            r.raise_for_status()
            progress["total"] = int(r.headers.get("content-length") or 0)
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1024 * 256):
                    if chunk:
                        f.write(chunk)
                        progress["done"] += len(chunk)

    try:
        name = sanitize_name(os.path.basename(urllib.parse.urlparse(url).path) or "app.apk")
        if os.path.splitext(name)[1].lower() not in APK_EXTS:
            name = name + ".apk"
        dest = os.path.join(s.dir, name)
        task = asyncio.create_task(asyncio.to_thread(_download, dest))
        while not task.done():
            await asyncio.sleep(5)
            text = f"⬇️ ডাউনলোড: {human_size(progress['done'])}"
            if progress["total"]:
                text += f" / {human_size(progress['total'])}"
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text)
            except TelegramError:
                pass
        await task
        if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
            raise RuntimeError("ফাইল খালি এসেছে")
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=f"✅ ডাউনলোড শেষ: {human_size(os.path.getsize(dest))}",
            )
        except TelegramError:
            pass
        await activate_session(bot, chat_id, s, dest, name)
    except Exception as e:
        shutil.rmtree(s.dir, ignore_errors=True)
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=f"❌ ডাউনলোড ব্যর্থ: {esc(str(e)[:200])}",
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass


def build_web_app(app):
    import flask

    web = flask.Flask("apkpatcher-web")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    css = (
        "body{font-family:sans-serif;background:#0f1216;color:#e8e8e8;padding:16px;max-width:720px;margin:auto}"
        ".card{background:#1b232c;border-radius:14px;padding:16px;margin:12px 0}"
        "input[type=file]{width:100%;margin:8px 0}"
        "button{background:#2ea043;color:#fff;border:0;border-radius:10px;padding:14px;font-size:17px;width:100%}"
        "a{color:#58a6ff;word-break:break-all}"
        "li{margin:6px 0}"
        "h2,h3{margin:8px 0}"
        ".err{color:#ff7b72}.ok{color:#3fb950;word-break:break-all}"
        "code{background:#0b0f13;padding:2px 6px;border-radius:6px;word-break:break-all}"
    )

    def page(title: str, body: str, code: int = 200):
        html_doc = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{css}</style></head>"
            f"<body><h2>🛠️ ApkPatcher</h2>{body}</body></html>"
        )
        return html_doc, code

    def valid(token: str):
        return WEB_TOKENS.get(token)

    def upload_body(token: str, error: str = "", ok: str = ""):
        err = f"<p class='err'>❌ {html.escape(error)}</p>" if error else ""
        okp = f"<p class='ok'>{html.escape(ok)}</p>" if ok else ""
        return (
            f"{err}{okp}"
            "<div class='card'><form method='post' enctype='multipart/form-data' action='/u/"
            f"{html.escape(token)}'>"
            "<input type='file' name='file' multiple "
            "accept='.apk,.apks,.apkm,.xapk,.pem,.crt,.cert,.der,.zip'>"
            "<button type='submit'>⬆️ আপলোড করে বটে পাঠান</button></form>"
            "<p>একসাথে দিতে পারেন: <b>main APK</b> + <b>cert</b> (.pem/.crt) + <b>module</b> (.apk)</p>"
            "<p>কোনো MB লিমিট নেই — যত বড় ফাইল হোক। আপলোড শেষে বট চ্যাটে patch মেনু চলে যাবে।</p>"
            f"<p><a href='/f/{html.escape(token)}'>📁 ফাইল/আউটপুট ব্রাউজার</a></p></div>"
        )

    @web.get("/")
    def index():
        return page(
            "ApkPatcher",
            "<div class='card'>বট চ্যাটে <code>/web</code> কমান্ড দিয়ে আপনার ব্যক্তিগত লিংক নিন।</div>",
        )

    @web.get("/u/<token>")
    def upload_form(token):
        if not valid(token):
            return page("Error", "<p class='err'>❌ ভুল বা পুরনো লিংক</p>", 404)
        return page("Upload", f"<div class='card'>{upload_body(token)}</div>")

    @web.post("/u/<token>")
    def upload(token):
        chat = valid(token)
        if not chat:
            return page("Error", "<p class='err'>❌ ভুল বা পুরনো লিংক</p>", 404)
        files = [f for f in flask.request.files.getlist("file") if f and f.filename]
        if not files:
            return page("Upload", f"<div class='card'>{upload_body(token, error='কোনো ফাইল সিলেক্ট করা হয়নি')}</div>", 400)
        s = Session(chat)
        main_saved = None
        certs, mods, skipped = [], [], []
        try:
            for f in files:
                safe = sanitize_name(f.filename)
                ext = os.path.splitext(safe)[1].lower()
                if ext in APK_EXTS and main_saved is None:
                    dest = os.path.join(s.dir, safe)
                    f.save(dest)
                    main_saved = (dest, safe)
                elif ext in CERT_EXTS:
                    d = os.path.join(s.dir, "certs")
                    os.makedirs(d, exist_ok=True)
                    dest = os.path.join(d, f"{int(time.time())}_{safe}")
                    f.save(dest)
                    certs.append(dest)
                elif ext == ".apk":
                    d = os.path.join(s.dir, "modules")
                    os.makedirs(d, exist_ok=True)
                    dest = os.path.join(d, f"{int(time.time())}_{safe}")
                    f.save(dest)
                    mods.append(dest)
                else:
                    skipped.append(safe)
        except Exception as e:
            shutil.rmtree(s.dir, ignore_errors=True)
            return page("Upload", f"<div class='card'>{upload_body(token, error=f'সেভ ব্যর্থ: {e}')}</div>", 500)
        if not main_saved:
            shutil.rmtree(s.dir, ignore_errors=True)
            return page(
                "Upload",
                f"<div class='card'>{upload_body(token, error='একটি APK ফাইল (.apk/.apks/.apkm/.xapk) দিন')}</div>",
                400,
            )
        s.certs.extend(certs)
        s.modules.extend(mods)
        loop = app.bot_data.get("loop")
        try:
            fut = asyncio.run_coroutine_threadsafe(
                activate_session(app.bot, chat, s, main_saved[0], main_saved[1]), loop
            )
            fut.result(timeout=120)
        except Exception as e:
            shutil.rmtree(s.dir, ignore_errors=True)
            return page(
                "Upload",
                f"<div class='card'>{upload_body(token, error=str(e))}</div>",
                500,
            )
        note = ""
        if certs:
            note += f"<p>📜 Cert যোগ: {len(certs)} টি</p>"
        if mods:
            note += f"<p>🧩 Module যোগ: {len(mods)} টি</p>"
        if skipped:
            note += f"<p class='err'>⚠️ বাদ পড়েছে: {html.escape(', '.join(skipped))}</p>"
        return page(
            "Done",
            "<div class='card'><h3 class='ok'>✅ আপলোড সফল!</h3>"
            f"<p>ফাইল: <b>{html.escape(main_saved[1])}</b> — বট চ্যাটে patch মেনু পাঠানো হয়েছে।</p>{note}"
            f"<p><a href='/f/{html.escape(token)}'>📁 ফাইল/আউটপুট ব্রাউজার</a> | "
            f"<a href='/u/{html.escape(token)}'>⬆️ আরও আপলোড</a></p></div>",
        )

    def folder_list(folder: str, token: str, prefix: str) -> str:
        items = []
        try:
            for name in sorted(os.listdir(folder)):
                p = os.path.join(folder, name)
                if not os.path.isfile(p):
                    continue
                size = human_size(os.path.getsize(p))
                url = web_link(f"{prefix}/{token}/" + urllib.parse.quote(name))
                items.append(f"<li><a href='{html.escape(url)}'>{html.escape(name)}</a> — {size}</li>")
        except Exception:
            pass
        return "".join(items) or "<li>খালি</li>"

    @web.get("/f/<token>")
    def files_page(token):
        if not valid(token):
            return page("Error", "<p class='err'>❌ ভুল বা পুরনো লিংক</p>", 404)
        body = (
            "<div class='card'><h3>📥 Input ফোল্ডার</h3>"
            f"<p><code>{html.escape(INBOX_DIR)}</code></p>"
            f"<ul>{folder_list(INBOX_DIR, token, '/i')}</ul></div>"
            "<div class='card'><h3>📤 Output ফোল্ডার (patched)</h3>"
            f"<p><code>{html.escape(OUTBOX_DIR)}</code></p>"
            f"<ul>{folder_list(OUTBOX_DIR, token, '/d')}</ul></div>"
            f"<p><a href='/u/{html.escape(token)}'>⬆️ আপলোড পেজ</a></p>"
        )
        return page("Files", body)

    def serve_from(folder: str, name: str):
        base = os.path.basename(name)
        p = os.path.join(folder, base)
        if not os.path.isfile(p):
            return page("Error", "<p class='err'>❌ ফাইল নেই</p>", 404)
        return flask.send_file(p, as_attachment=True, download_name=base)

    @web.get("/d/<token>/<path:name>")
    def dl_output(token, name):
        if not valid(token):
            return page("Error", "<p class='err'>❌ ভুল লিংক</p>", 404)
        return serve_from(OUTBOX_DIR, name)

    @web.get("/i/<token>/<path:name>")
    def dl_input(token, name):
        if not valid(token):
            return page("Error", "<p class='err'>❌ ভুল লিংক</p>", 404)
        return serve_from(INBOX_DIR, name)

    return web


async def post_init(app: Application):
    os.makedirs(JOBS_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
    ensure_shared_dirs()
    load_tokens()
    try:
        subprocess.Popen(
            ["termux-wake-lock"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass
    app.bot_data["loop"] = asyncio.get_running_loop()
    app.bot_data["web_ok"] = False
    if WEB_ENABLED:
        try:
            from werkzeug.serving import make_server

            web = build_web_app(app)
            server = make_server(WEB_HOST, WEB_PORT, web, threaded=True)
            threading.Thread(target=server.serve_forever, daemon=True, name="web").start()
            app.bot_data["web_ok"] = True
            print(f"[web] listening on http://{WEB_HOST}:{WEB_PORT}", flush=True)
        except Exception as e:
            print(f"[web] failed to start: {e}", flush=True)
    app.bot_data["worker"] = asyncio.create_task(worker(app))
    await app.bot.set_my_commands(commands_list())
    print("[bot] started", flush=True)


async def post_shutdown(app: Application):
    task = app.bot_data.get("worker")
    if task:
        task.cancel()
    try:
        subprocess.Popen(
            ["termux-wake-unlock"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .connect_timeout(30)
        .read_timeout(600)
        .write_timeout(1800)
        .pool_timeout(60)
        .base_url(LOCAL_API_URL if LOCAL_API else "https://api.telegram.org/bot")
        .local_mode(LOCAL_API)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("web", cmd_web))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("url", cmd_url))
    app.add_handler(CommandHandler("flags", cmd_flags))
    app.add_handler(CommandHandler("tools", cmd_tools))
    app.add_handler(CommandHandler("credits", cmd_credits))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("clean", cmd_clean))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
