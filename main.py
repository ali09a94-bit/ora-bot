"""
╔══════════════════════════════════════════════════════════════╗
║               ORA BOT — Zero-Click Download Build            ║
║          بوت أورا — تحميل فوري بدون أزرار اختيار            ║
║                                                              ║
║  ⚠️  SECURITY: NEVER paste your token in any chat.           ║
║     Revoke any exposed token at @BotFather immediately.      ║
║     Set BOT_TOKEN as an environment variable in production.  ║
║                                                              ║
║  Environment Variables:                                      ║
║    BOT_TOKEN    → Token from @BotFather                      ║
║    ADMIN_ID     → Your numeric Telegram user ID              ║
║    CHANNEL_ID   → Forced-sub channel  (default @Ora333)      ║
║    BOT_USERNAME → Username without @  (default ali09a933BOT) ║
║    PORT         → Web-server port     (default 8080)         ║
╚══════════════════════════════════════════════════════════════╝
"""

# ══════════════════════════════════════════════════════════════
#  IMPORTS
# ══════════════════════════════════════════════════════════════
import os
import re
import json
import time
import logging
import tempfile
import shutil
from threading import Thread
from urllib.parse import urlparse, parse_qs

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
from flask import Flask

# ══════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("OraBot")

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION  — env vars override these defaults
# ══════════════════════════════════════════════════════════════
TOKEN        = os.getenv("BOT_TOKEN",    "YOUR_NEW_TOKEN_HERE")   # ← paste NEW token after revoking
ADMIN_ID     = int(os.getenv("ADMIN_ID", "5289253636"))
CHANNEL_ID   = os.getenv("CHANNEL_ID",   "@Ora333")
BOT_USERNAME = os.getenv("BOT_USERNAME", "ali09a933BOT")
DATA_FILE    = "bot_data.json"
MAX_FILE_MB  = 50     # Telegram hard cap for bot uploads

# ══════════════════════════════════════════════════════════════
#  BOT INSTANCE
# ══════════════════════════════════════════════════════════════
bot = telebot.TeleBot(TOKEN, parse_mode=None)

# ══════════════════════════════════════════════════════════════
#  KEEP-ALIVE WEB SERVER
# ══════════════════════════════════════════════════════════════
_flask = Flask(__name__)

@_flask.route("/")
def _home():
    return "✅ Ora Bot is Online!", 200

def _run_flask():
    port = int(os.getenv("PORT", 8080))
    _flask.run(host="0.0.0.0", port=port, use_reloader=False)

def keep_alive():
    Thread(target=_run_flask, daemon=True, name="Flask").start()
    log.info("Keep-alive web server started.")

# ══════════════════════════════════════════════════════════════
#  PERSISTENT STORAGE  — never overwrites an existing file
# ══════════════════════════════════════════════════════════════
def _init_data():
    if not os.path.exists(DATA_FILE):
        _write_data({"users": [], "total_dl": 0})
        log.info("Created new bot_data.json")
    else:
        d = _read_data()
        log.info(
            f"Loaded existing data — "
            f"users: {len(d.get('users', []))}, "
            f"total_dl: {d.get('total_dl', 0)}"
        )

def _read_data() -> dict:
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {"users": [], "total_dl": 0}

def _write_data(data: dict):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.error(f"Failed to write data: {exc}")

def register_user(uid: int, first_name: str):
    data = _read_data()
    if uid not in data["users"]:
        data["users"].append(uid)
        _write_data(data)
        log.info(f"New user: {uid} ({first_name})")
        try:
            bot.send_message(
                ADMIN_ID,
                f"🆕 *مستخدم جديد!*\n"
                f"👤 الاسم  : `{first_name}`\n"
                f"🆔 المعرف : `{uid}`\n"
                f"👥 الإجمالي: `{len(data['users'])}`",
                parse_mode="Markdown",
            )
        except Exception:
            pass

def increment_dl():
    data = _read_data()
    data["total_dl"] = data.get("total_dl", 0) + 1
    _write_data(data)

# ══════════════════════════════════════════════════════════════
#  IN-MEMORY STATE
# ══════════════════════════════════════════════════════════════
# Stores  uid → url  for deferred MP3 conversion after video send
pending_mp3: dict = {}

# Admin UIDs currently in broadcast-input mode
broadcast_mode: set = set()

# ══════════════════════════════════════════════════════════════
#  URL VALIDATION HELPERS
# ══════════════════════════════════════════════════════════════

# Patterns that indicate a channel / user / playlist — NOT a single video
_CHANNEL_PATTERNS = [
    r"youtube\.com/@",                      # @handle URLs
    r"youtube\.com/channel/",               # /channel/UC…
    r"youtube\.com/user/",                  # /user/name
    r"youtube\.com/c/",                     # /c/name (old custom URLs)
    r"[?&]list=",                           # any playlist parameter
]
_CHANNEL_RE = re.compile("|".join(_CHANNEL_PATTERNS), re.IGNORECASE)

# Recognised single-video URL shapes
_VIDEO_RE = re.compile(
    r"(youtube\.com/watch\?.*v=[\w-]+|youtu\.be/[\w-]+|"
    r"instagram\.com/|facebook\.com/|fb\.watch/|"
    r"tiktok\.com/|twitter\.com/|x\.com/|"
    r"snapchat\.com/|pinterest\.com/|likee\.video/|"
    r"vimeo\.com/|dailymotion\.com/)",
    re.IGNORECASE,
)

def is_channel_url(url: str) -> bool:
    """Return True if the URL points to a channel/user/playlist, not a video."""
    return bool(_CHANNEL_RE.search(url))

def is_supported_url(url: str) -> bool:
    """Return True if the URL looks like a downloadable media link."""
    return bool(_VIDEO_RE.search(url))

# ══════════════════════════════════════════════════════════════
#  FORCED SUBSCRIPTION
# ══════════════════════════════════════════════════════════════
def is_subscribed(uid: int) -> bool:
    try:
        status = bot.get_chat_member(CHANNEL_ID, uid).status
        return status in ("member", "administrator", "creator")
    except Exception as exc:
        log.warning(f"Sub check error for {uid}: {exc}")
        return True   # fail-open

def kb_subscribe() -> InlineKeyboardMarkup:
    m = InlineKeyboardMarkup()
    m.row(InlineKeyboardButton(
        "📢 اشترك في قناة أورا",
        url=f"https://t.me/{CHANNEL_ID.lstrip('@')}",
    ))
    m.row(InlineKeyboardButton("✅ اشتركت، تحقق الآن", callback_data="verify_sub"))
    return m

def gate_sub(uid: int, chat_type: str) -> bool:
    """Send subscription gate and return True if user is blocked."""
    if chat_type != "private":
        return False
    if not is_subscribed(uid):
        bot.send_message(
            uid,
            "⚠️ *يجب الاشتراك في قناة أورا أولاً للاستخدام:*\n\n"
            "بعد الاشتراك اضغط زر التحقق 👇",
            parse_mode="Markdown",
            reply_markup=kb_subscribe(),
        )
        return True
    return False

# ══════════════════════════════════════════════════════════════
#  KEYBOARDS
# ══════════════════════════════════════════════════════════════
def kb_mp3(url: str) -> InlineKeyboardMarkup:
    """Inline button attached to the sent video offering MP3 conversion."""
    m = InlineKeyboardMarkup()
    m.row(InlineKeyboardButton(
        "🎵 تحويل إلى MP3",
        callback_data=f"mp3|{url}",
    ))
    return m

def kb_admin() -> InlineKeyboardMarkup:
    m = InlineKeyboardMarkup()
    m.row(InlineKeyboardButton("📣 بث رسالة للجميع",   callback_data="adm_broadcast"))
    m.row(InlineKeyboardButton("🔄 تحديث الإحصائيات",  callback_data="adm_refresh"))
    return m

# ══════════════════════════════════════════════════════════════
#  YOUTUBE SEARCH  (يوت prefix only)
# ══════════════════════════════════════════════════════════════
def yt_search_url(query: str):
    """Return YouTube watch URL for the top result of `query`."""
    opts = {
        "quiet":         True,
        "skip_download": True,
        "extract_flat":  True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if info and info.get("entries"):
                vid_id = info["entries"][0].get("id")
                if vid_id:
                    return f"https://www.youtube.com/watch?v={vid_id}"
    except Exception as exc:
        log.error(f"YouTube search error: {exc}")
    return None

# ══════════════════════════════════════════════════════════════
#  CORE DOWNLOADER
# ══════════════════════════════════════════════════════════════
def _build_ydl_opts(fmt: str, tmp_dir: str) -> dict:
    if fmt == "audio":
        return {
            "format":   "bestaudio/best",
            "outtmpl":  os.path.join(tmp_dir, "%(title)s.%(ext)s"),
            "quiet":    True,
            "postprocessors": [{
                "key":              "FFmpegExtractAudio",
                "preferredcodec":   "mp3",
                "preferredquality": "192",
            }],
        }
    return {
        "format": (
            "bestvideo[ext=mp4][filesize<45M]+bestaudio[ext=m4a]"
            "/best[ext=mp4][filesize<45M]"
            "/best[filesize<45M]"
        ),
        "outtmpl":             os.path.join(tmp_dir, "%(title)s.%(ext)s"),
        "quiet":               True,
        "merge_output_format": "mp4",
    }


def _locate_file(tmp_dir: str, fmt: str, ydl, info: dict):
    """Find the downloaded file inside tmp_dir."""
    if fmt == "audio":
        for fn in os.listdir(tmp_dir):
            if fn.endswith(".mp3"):
                return os.path.join(tmp_dir, fn)
        return None

    base = os.path.splitext(ydl.prepare_filename(info))[0]
    for ext in ("mp4", "mkv", "webm"):
        candidate = f"{base}.{ext}"
        if os.path.exists(candidate):
            return candidate

    # Last resort: largest file in dir
    files = [os.path.join(tmp_dir, f) for f in os.listdir(tmp_dir)]
    return max(files, key=os.path.getsize) if files else None


def download_and_send(uid: int, url: str, fmt: str,
                      status_msg_id: int = None, reply_id: int = None):
    """
    Download `url` in `fmt` ('video' | 'audio'), send to `uid`.
    After a successful VIDEO send, attach a 🎵 MP3 button.
    Always wipes the temp directory in the finally block.
    """
    tmp_dir = tempfile.mkdtemp(prefix="ora_")
    ydl_opts = _build_ydl_opts(fmt, tmp_dir)

    # Create or reuse a status message
    if status_msg_id is None:
        status_text = (
            "🎵 جارٍ استخراج الصوت بجودة 192kbps..." if fmt == "audio"
            else "⏳ جارٍ تحميل الفيديو..."
        )
        status = bot.send_message(uid, status_text,
                                  reply_to_message_id=reply_id)
    else:
        status = type("_M", (), {"message_id": status_msg_id})()   # lightweight proxy

    try:
        # ── Download ─────────────────────────────────────────
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            final_file = _locate_file(tmp_dir, fmt, ydl, info)

        if not final_file or not os.path.exists(final_file):
            raise FileNotFoundError("Output file missing after download.")

        # ── Size guard ────────────────────────────────────────
        size_mb = os.path.getsize(final_file) / (1024 * 1024)
        if size_mb > MAX_FILE_MB:
            _safe_edit(uid, status.message_id,
                       f"⚠️ حجم الملف ({size_mb:.1f} MB) يتجاوز "
                       f"حد تيليغرام ({MAX_FILE_MB} MB).")
            return

        # ── Send ──────────────────────────────────────────────
        caption = (
            f"✅ *@{BOT_USERNAME}*\n"
            f"{'🎵 MP3 · 192 kbps' if fmt == 'audio' else '🎬 MP4'}"
        )

        with open(final_file, "rb") as fh:
            if fmt == "audio":
                bot.send_audio(uid, fh,
                               caption=caption,
                               parse_mode="Markdown")
            else:
                # Attach the MP3 conversion button directly to the video
                bot.send_video(uid, fh,
                               caption=caption,
                               parse_mode="Markdown",
                               supports_streaming=True,
                               reply_markup=kb_mp3(url))

        increment_dl()

        # Delete the "downloading…" status message
        try:
            bot.delete_message(uid, status.message_id)
        except Exception:
            pass

    except FileNotFoundError as exc:
        log.error(f"[{uid}] {exc}")
        _safe_edit(uid, status.message_id,
                   "❌ تعذّر إيجاد الملف بعد التحميل. حاول مرة أخرى.")

    except yt_dlp.utils.DownloadError as exc:
        log.error(f"[{uid}] DownloadError: {exc}")
        _safe_edit(uid, status.message_id,
                   "❌ فشل التحميل.\n"
                   "قد يكون الرابط خاصاً أو محمياً أو غير مدعوم.")

    except Exception as exc:
        log.exception(f"[{uid}] Unexpected: {exc}")
        _safe_edit(uid, status.message_id,
                   "❌ خطأ غير متوقع. حاول لاحقاً.")

    finally:
        # ✅ Always nuke temp files — no leftovers on the server
        shutil.rmtree(tmp_dir, ignore_errors=True)
        log.info(f"[{uid}] Temp dir cleaned.")


def _safe_edit(uid: int, msg_id: int, text: str):
    try:
        bot.edit_message_text(text, uid, msg_id)
    except Exception:
        try:
            bot.send_message(uid, text)
        except Exception:
            pass


def spawn(uid: int, url: str, fmt: str,
          status_msg_id: int = None, reply_id: int = None):
    """Launch download_and_send in a daemon thread."""
    Thread(
        target=download_and_send,
        args=(uid, url, fmt, status_msg_id, reply_id),
        daemon=True,
        name=f"DL-{uid}",
    ).start()

# ══════════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════
@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid  = message.chat.id
    name = message.from_user.first_name or "مستخدم"

    if message.chat.type == "private":
        register_user(uid, name)
        if gate_sub(uid, "private"):
            return

    bot.send_message(
        uid,
        f"👋 أهلاً *{name}*!\n\n"
        "📥 *بوت أورا للتحميل الفوري*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔗 أرسل رابط الفيديو ← يبدأ التحميل فوراً\n"
        "🔍 للبحث في يوتيوب: ابدأ بـ *يوت* ثم اسم الفيديو\n"
        "    مثال: `يوت اسم الأغنية`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "بعد إرسال الفيديو يظهر زر 🎵 لتحويله إلى MP3",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["admin"])
def cmd_admin(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ هذا الأمر للمشرف فقط.")
        return
    data = _read_data()
    bot.send_message(
        ADMIN_ID,
        f"🛠 *لوحة تحكم Ora Bot*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 المستخدمون : `{len(data.get('users', []))}`\n"
        f"📥 التحميلات  : `{data.get('total_dl', 0)}`",
        parse_mode="Markdown",
        reply_markup=kb_admin(),
    )

# ══════════════════════════════════════════════════════════════
#  MAIN TEXT / URL HANDLER
# ══════════════════════════════════════════════════════════════
@bot.message_handler(
    func=lambda m: m.text and not m.text.startswith("/"),
    content_types=["text"],
)
def handle_text(message):
    uid  = message.chat.id
    text = message.text.strip()

    # Register + enforce subscription in private
    if message.chat.type == "private":
        register_user(uid, message.from_user.first_name or "")
        if gate_sub(uid, "private"):
            return

    # ── Admin broadcast collection ────────────────────────────
    if uid == ADMIN_ID and uid in broadcast_mode:
        broadcast_mode.discard(uid)
        data    = _read_data()
        users   = data.get("users", [])
        sent_ok = 0
        prog = bot.reply_to(message,
                            f"📣 جارٍ الإرسال لـ {len(users)} مستخدم...")
        for user_id in users:
            try:
                bot.send_message(user_id, text)
                sent_ok += 1
            except Exception:
                pass
            time.sleep(0.05)
        bot.edit_message_text(
            f"✅ تم الإرسال بنجاح لـ *{sent_ok}* / {len(users)} مستخدم.",
            uid, prog.message_id,
            parse_mode="Markdown",
        )
        return

    # ── يوت search (exclusive trigger) ───────────────────────
    if text.startswith("يوت "):
        query = text[4:].strip()
        if not query:
            bot.reply_to(message,
                         "✏️ اكتب اسم الفيديو بعد *يوت*\nمثال: `يوت اسم الأغنية`",
                         parse_mode="Markdown")
            return
        searching = bot.reply_to(message, "🔍 جارٍ البحث في يوتيوب...")
        url = yt_search_url(query)
        if not url:
            _safe_edit(uid, searching.message_id,
                       "❌ لم يُعثر على نتائج. جرّب كلمات مختلفة.")
            return
        # Edit status → "Downloading…" then trigger immediate video download
        bot.edit_message_text("⏳ تم العثور على الفيديو، جارٍ التحميل...",
                              uid, searching.message_id)
        spawn(uid, url, "video",
              status_msg_id=searching.message_id,
              reply_id=message.message_id)
        return

    # ── URL handling ──────────────────────────────────────────
    if text.startswith(("http://", "https://")):
        url = text.split()[0]   # take first token in case of trailing text

        # Anti-channel protection
        if is_channel_url(url):
            bot.reply_to(
                message,
                "⚠️ عذراً، أرسل رابط فيديو فقط، لا يمكن تحميل القنوات.",
            )
            return

        # Must be a recognisable media URL (or we try anyway for any-site)
        status = bot.reply_to(message, "⏳ جارٍ التحميل...")
        spawn(uid, url, "video",
              status_msg_id=status.message_id,
              reply_id=message.message_id)
        return

    # ── Anything else → gentle hint ──────────────────────────
    bot.reply_to(
        message,
        "📎 أرسل رابط فيديو للتحميل الفوري\n"
        "🔍 أو ابدأ بـ *يوت* للبحث في يوتيوب",
        parse_mode="Markdown",
    )

# ══════════════════════════════════════════════════════════════
#  CALLBACK QUERY HANDLER
# ══════════════════════════════════════════════════════════════
@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
    uid    = call.message.chat.id
    data   = call.data
    msg_id = call.message.message_id

    # ── Subscription verification ─────────────────────────────
    if data == "verify_sub":
        if is_subscribed(uid):
            bot.answer_callback_query(call.id, "✅ تم التحقق! أهلاً بك.")
            bot.edit_message_text(
                "✅ *تم التحقق من اشتراكك!*\n\n"
                "أرسل رابط الفيديو أو ابدأ بـ *يوت* للبحث:",
                uid, msg_id,
                parse_mode="Markdown",
            )
        else:
            bot.answer_callback_query(
                call.id,
                "❌ لم تشترك بعد! اشترك ثم اضغط التحقق مجدداً.",
                show_alert=True,
            )
        return

    # ── MP3 conversion request ────────────────────────────────
    if data.startswith("mp3|"):
        url = data[4:]
        bot.answer_callback_query(call.id,
