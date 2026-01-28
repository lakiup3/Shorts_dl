import os
import threading
from queue import Queue
import requests
import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatAction
from flask import Flask
from threading import Thread
import time
import traceback

COOKIES_TXT_PATH = "cookies.txt"
if not os.path.exists(COOKIES_TXT_PATH):
    print(f"ERROR: Faylka '{COOKIES_TXT_PATH}' lama helin. Fadlan hubi inuu jiro.")

API_ID = 29169428
API_HASH = "55742b16a85aac494c7944568b5507e5"
BOT_TOKEN = "8380607635:AAG8k4aHddbLOuzHZk7gEZcgHLXXFUGqcqw"

DOWNLOAD_PATH = "downloads"
os.makedirs(DOWNLOAD_PATH, exist_ok=True)

MAX_CONCURRENT_DOWNLOADS = 2
MAX_VIDEO_DURATION = 2400

YDL_OPTS_PIN = {
    "format": "bestvideo+bestaudio/best",
    "outtmpl": os.path.join(DOWNLOAD_PATH, "%(title)s.%(ext)s"),
    "noplaylist": True,
    "quiet": True,
    "cookiefile": COOKIES_TXT_PATH
}

YDL_OPTS_YOUTUBE = {
    "format": "best",
    "outtmpl": os.path.join(DOWNLOAD_PATH, "%(title)s.%(ext)s"),
    "noplaylist": True,
    "quiet": True,
    "cookiefile": COOKIES_TXT_PATH
}

YDL_OPTS_DEFAULT = {
    "format": "best",
    "outtmpl": os.path.join(DOWNLOAD_PATH, "%(title)s.%(ext)s"),
    "noplaylist": True,
    "quiet": True,
    "cookiefile": COOKIES_TXT_PATH
}

SUPPORTED_DOMAINS = [
    "youtube.com", "youtu.be", "facebook.com", "fb.watch", "pin.it",
    "x.com", "tiktok.com", "snapchat.com", "instagram.com"
]

app = Client("video_downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
flask_app = Flask(__name__)

semaphore = threading.Semaphore(MAX_CONCURRENT_DOWNLOADS)
task_queue = Queue()

def download_thumbnail(url, target_path):
    try:
        resp = requests.get(url, stream=True, timeout=15)
        if resp.status_code == 200:
            with open(target_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            if os.path.exists(target_path):
                return target_path
    except Exception:
        pass
    return None

def extract_metadata_from_info(info):
    width = info.get("width")
    height = info.get("height")
    duration = info.get("duration")
    if not width or not height:
        formats = info.get("formats") or []
        best = None
        for f in formats:
            if f.get("width") and f.get("height"):
                best = f
                break
        if best:
            if not width:
                width = best.get("width")
            if not height:
                height = best.get("height")
            if not duration:
                dms = best.get("duration_ms")
                duration = info.get("duration") or (dms / 1000 if dms else None)
    return width, height, duration

def download_video_once(url):
    lowered = url.lower()
    is_pin = "pin.it" in lowered
    is_youtube = "youtube.com" in lowered or "youtu.be" in lowered
    if is_pin:
        ydl_opts = YDL_OPTS_PIN.copy()
    elif is_youtube:
        ydl_opts = YDL_OPTS_YOUTUBE.copy()
    else:
        ydl_opts = YDL_OPTS_DEFAULT.copy()

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    width, height, duration = extract_metadata_from_info(info)
    if duration and duration > MAX_VIDEO_DURATION:
        return None
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dl = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info_dl)
    title = info_dl.get("title") or ""
    desc = info_dl.get("description") or ""
    thumb = None
    thumb_url = info_dl.get("thumbnail")
    if thumb_url:
        thumb_path = os.path.splitext(filename)[0] + ".jpg"
        thumb = download_thumbnail(thumb_url, thumb_path)
    return title, desc, filename, width, height, duration, thumb

def download_video(url, retries=3, delay=2):
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return download_video_once(url)
        except Exception as e:
            last_exc = e
            if attempt < retries:
                time.sleep(delay)
            else:
                raise last_exc

def process_download_sync(client, message, url):
    try:
        client.send_chat_action(message.chat.id, ChatAction.TYPING)
        try:
            result = download_video(url)
        except Exception as e:
            tb = traceback.format_exc()
            short_tb = tb if len(tb) <= 3500 else tb[:3500] + "\n\n...[truncated]"
            try:
                message.reply_text(f"Qalad ayaa dhacay marka la soo dejinayo.\n\nFariin qalad:\n{str(e)}\n\nLog:\n{short_tb}")
            except Exception:
                pass
            return
        if result is None:
            try:
                message.reply_text("Masoo dajin kari video ka dheer 40 minute 👍")
            except Exception:
                pass
        else:
            title, desc, file_path, width, height, duration, thumb = result
            try:
                client.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
            except Exception:
                pass
            try:
                me = client.get_me()
                bot_username = None
                if getattr(me, "username", None):
                    bot_username = f"@{me.username}"
            except Exception:
                bot_username = None
            caption_source = title if title else desc.strip()
            if not caption_source:
                caption_source = bot_username or "SooDajiye Bot"
            caption = caption_source
            if len(caption) > 1024:
                caption = caption[:1021] + "..."
            send_kwargs = {"chat_id": message.chat.id, "video": file_path, "caption": caption, "supports_streaming": True}
            if width:
                try:
                    send_kwargs["width"] = int(width)
                except Exception:
                    pass
            if height:
                try:
                    send_kwargs["height"] = int(height)
                except Exception:
                    pass
            if duration:
                try:
                    send_kwargs["duration"] = int(float(duration))
                except Exception:
                    pass
            if thumb and os.path.exists(thumb):
                send_kwargs["thumb"] = thumb
            try:
                client.send_video(**send_kwargs)
            except Exception:
                try:
                    message.reply_text("Video waa la soo dhejiyay laakiin waxaa dhacay cilad gudbinta.")
                except Exception:
                    pass
            for fpath in [file_path, thumb]:
                if fpath and os.path.exists(fpath):
                    try:
                        os.remove(fpath)
                    except Exception:
                        pass
    finally:
        if not task_queue.empty():
            try:
                next_item = task_queue.get_nowait()
            except Exception:
                next_item = None
            if next_item:
                t_client, t_message, t_url = next_item
                try:
                    semaphore.acquire()
                    t = threading.Thread(target=threaded_worker, args=(t_client, t_message, t_url), daemon=True)
                    t.start()
                except Exception:
                    semaphore.release()
        semaphore.release()

def threaded_worker(client, message, url):
    try:
        process_download_sync(client, message, url)
    except Exception as e:
        tb = traceback.format_exc()
        short_tb = tb if len(tb) <= 3500 else tb[:3500] + "\n\n...[truncated]"
        try:
            message.reply_text(f"THREAD ERROR: {str(e)}\n\nLog:\n{short_tb}")
        except Exception:
            pass

@app.on_message(filters.private & filters.command("start"))
def start(client, message: Message):
    message.reply_text(
        "👋 Salaam!\n"
        "Iisoodir link Video kasocdo baraha hoos kuxusan si aan kuugu soo dajiyo.\n\n"
        "Supported sites:\n"
        "• YouTube\n"
        "• Facebook\n"
        "• Pinterest\n"
        "• X (Twitter)\n"
        "• TikTok\n"
        "• Instagram"
    )

@app.on_message(filters.private & filters.text)
def handle_link(client, message: Message):
    url = message.text.strip()
    if not any(domain in url.lower() for domain in SUPPORTED_DOMAINS):
        message.reply_text("kaliya Soodir link video saxa 👍")
        return
    acquired = semaphore.acquire(blocking=False)
    if acquired:
        t = threading.Thread(target=threaded_worker, args=(client, message, url), daemon=True)
        t.start()
    else:
        task_queue.put((client, message, url))
        try:
            message.reply_text("Waxaa lagu daray safka, fadlan sug inta aan kuu soo dhejinno.")
        except Exception:
            pass

@flask_app.route("/", methods=["GET", "POST", "HEAD"])
def keep_alive():
    return "Bot is alive ✅", 200

def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

def run_bot():
    app.run()

Thread(target=run_flask).start()
run_bot()
