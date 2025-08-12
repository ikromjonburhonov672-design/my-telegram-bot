# bot.py
import os
import json
import threading
import time
from datetime import datetime, timedelta
import uuid

import telebot # type: ignore
from telebot import types, apihelper # pyright: ignore[reportMissingImports]

# ---- CONFIG ----
TOKEN = "8003233742:AAHz2XUKKLLO35INV0KKS6pCASxg5DgwFq8"  # <--- bu yerga token qo'ying
STICKER_ID = "CAACAgIAAxkBAAEIoH9mRv6dMfxz2qlLDWwVjD3xwKj5EAACNQADVp29Cj_yHOcUFUcyNgQ"
DATA_FILE = "reminders.json"
LANGS_FILE = "langs.json"

# network timeouts (kamroq ReadTimeout xatolari uchun)
apihelper.READ_TIMEOUT = 60
apihelper.CONNECT_TIMEOUT = 60

bot = telebot.TeleBot(TOKEN)
lock = threading.Lock()

# ---- Load langs ----
if not os.path.exists(LANGS_FILE):
    raise SystemExit(f"{LANGS_FILE} topilmadi. Bot papkasiga langs.json qo'ying.")

with open(LANGS_FILE, "r", encoding="utf-8") as f:
    LANGS = json.load(f)

# ---- Data: user languages + reminders ----
# reminders structure in JSON:
# { "<chat_id>": [ { "id": "<uuid>", "text": "...", "time": "2025-08-11T14:30:00", "sent": false }, ... ] }
user_languages = {}  # in-memory; also persisted inside reminders file under "_langs" key optionally

def load_data():
    global reminders, user_languages
    with lock:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    data = {}
        else:
            data = {}
        reminders = data.get("reminders", {})
        user_languages = data.get("langs", {})
        # convert keys to str for safety
        reminders = {str(k): v for k, v in reminders.items()}
        user_languages = {str(k): v for k, v in user_languages.items()}

def save_data():
    with lock:
        data = {
            "reminders": reminders,
            "langs": user_languages
        }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

# initialize
reminders = {}
load_data()

# ---- Helpers ----
def get_text(chat_id, key):
    lang = user_languages.get(str(chat_id), "uz")
    return LANGS.get(lang, LANGS.get("uz", {})).get(key, key)

def parse_user_datetime(dt_str):
    """Qabul qilingan dt_str ni parse qiladi.
       Accepts:
         - HH:MM
         - HH:MM:SS
         - YYYY-MM-DD HH:MM
         - YYYY-MM-DDTHH:MM
         - YYYY-MM-DD HH:MM:SS
    Returns datetime (naive, local). Raises ValueError if not parsable.
    """
    now = datetime.now()
    dt_str = dt_str.strip()
    fmts = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%H:%M",
        "%H:%M:%S",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(dt_str, fmt)
            # if only time provided -> set to today (or tomorrow if already passed)
            if fmt in ("%H:%M", "%H:%M:%S"):
                dt = dt.replace(year=now.year, month=now.month, day=now.day)
                if dt < now:
                    dt += timedelta(days=1)
            return dt
        except ValueError:
            continue
    raise ValueError("invalid datetime")

def safe_send_message(chat_id, text, **kwargs):
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        print(f"[WARN] send_message failed for {chat_id}: {e}")

# ---- Reminder checker thread ----
def reminder_checker():
    while True:
        try:
            now = datetime.now()
            with lock:
                # iterate copy of keys to be safe
                for chat_id in list(reminders.keys()):
                    items = reminders.get(str(chat_id), [])
                    for item in items[:]:
                        if not item.get("sent", False):
                            # parse stored ISO format
                            try:
                                rem_dt = datetime.fromisoformat(item["time"])
                            except Exception:
                                # if someone saved plain "HH:MM", try parse
                                try:
                                    rem_dt = parse_user_datetime(item["time"])
                                except Exception:
                                    # bad entry - skip
                                    continue
                            if rem_dt <= now:
                                text = f"⏰ {item['text']}"
                                safe_send_message(int(chat_id), text)
                                item["sent"] = True
                                save_data()
            time.sleep(15)
        except Exception as e:
            print("Reminder checker xatosi:", e)
            time.sleep(5)

# start checker thread
threading.Thread(target=reminder_checker, daemon=True).start()

# ---- /start: sticker + language keyboard ----
@bot.message_handler(commands=["start"])
def cmd_start(message):
    chat_id = message.chat.id
    # send sticker (pre-tested file_id)
    try:
        bot.send_sticker(message.chat.id, "CAACAgIAAxkBAAEPCeVoiSxeQDcomXJSLjpN96eafuzyEwACNQEAAjDUnRG0uDX9ZqC2fDYE")
    except Exception as e:
        print("Sticker yuborilmadi:", e)
    # language keyboard (one_time so user picks)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("🇺🇿 O'zbekcha", "🇷🇺 Русский", "🇬🇧 English")
    bot.send_message(chat_id, "Salom! Tilni tanlang / Please choose language / Пожалуйста, выберите язык:", reply_markup=markup)

# ---- language selection handler ----
@bot.message_handler(func=lambda m: m.text in ["🇺🇿 O'zbekcha", "🇷🇺 Русский", "🇬🇧 English"])
def handle_lang_choice(message):
    chat_id = str(message.chat.id)
    txt = message.text
    if "O'zbek" in txt:
        code = "uz"
    elif "Русский" in txt:
        code = "ru"
    else:
        code = "en"
    user_languages[chat_id] = code
    save_data()
    # send main menu
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(LANGS[code]["add_reminder"], LANGS[code]["remove_reminder"])
    kb.row(LANGS[code]["list_reminders"], LANGS[code].get("menu_help", "ℹ️ Help"))
    bot.send_message(int(chat_id), LANGS[code].get("language_set", "Language set!"), reply_markup=kb)

# ---- Add reminder flow ----
# store temporary per-user step state in memory
pending = {}  # { chat_id_str: {"stage": "text" or "time", "text": "..."} }

@bot.message_handler(func=lambda m: True)
def main_router(message):
    chat_id = str(message.chat.id)
    # if user hasn't selected language, ask to choose
    if chat_id not in user_languages:
        # re-run start to force language pick
        cmd_start(message)
        return

    lang = user_languages[chat_id]
    text = message.text or ""

    # If user is in pending flow
    state = pending.get(chat_id)
    if state:
        if state["stage"] == "text":
            # we got reminder text
            pending[chat_id]["text"] = text
            pending[chat_id]["stage"] = "time"
            bot.send_message(int(chat_id), LANGS[lang]["enter_reminder_time"])
            return
        elif state["stage"] == "time":
            # we got time -> try parse and save
            time_str = text
            try:
                dt = parse_user_datetime(time_str)
            except Exception:
                bot.send_message(int(chat_id), LANGS[lang].get("invalid_time", "❌ Invalid time format!"))
                # ask time again
                bot.send_message(int(chat_id), LANGS[lang]["enter_reminder_time"])
                return
            # save reminder
            rid = str(uuid.uuid4())
            item = {
                "id": rid,
                "text": state["text"],
                "time": dt.isoformat(),
                "sent": False
            }
            with lock:
                reminders.setdefault(chat_id, []).append(item)
                save_data()
            pending.pop(chat_id, None)
            bot.send_message(int(chat_id), LANGS[lang]["reminder_saved"])
            return

    # No pending -> check main menu buttons
    if text == LANGS[lang]["add_reminder"]:
        pending[chat_id] = {"stage": "text"}
        bot.send_message(int(chat_id), LANGS[lang]["enter_reminder_text"])
        return
    elif text == LANGS[lang]["list_reminders"]:
        with lock:
            items = reminders.get(chat_id, [])
        if not items:
            bot.send_message(int(chat_id), LANGS[lang]["no_reminders"])
            return
        # build text and inline keyboard for deletion
        lines = []
        kb = types.InlineKeyboardMarkup()
        for i, it in enumerate(items, 1):
            dt_display = it["time"]
            # try pretty format
            try:
                dt_display = datetime.fromisoformat(it["time"]).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
            lines.append(f"{i}. {dt_display} — {it['text']}")
            kb.add(types.InlineKeyboardButton(f"❌ {i}", callback_data=f"del:{it['id']}"))
        bot.send_message(int(chat_id), "\n".join(lines), reply_markup=kb)
        return
    elif text == LANGS[lang]["remove_reminder"]:
        with lock:
            items = reminders.get(chat_id, [])
        if not items:
            bot.send_message(int(chat_id), LANGS[lang]["no_reminders"])
            return
        kb = types.InlineKeyboardMarkup()
        for i, it in enumerate(items, 1):
            dt_display = it["time"]
            try:
                dt_display = datetime.fromisoformat(it["time"]).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
            kb.add(types.InlineKeyboardButton(f"{i}. {dt_display} — {it['text']}", callback_data=f"del:{it['id']}"))
        bot.send_message(int(chat_id), LANGS[lang]["choose_reminder_delete"], reply_markup=kb)
        return
    else:
        # unknown command/text
        bot.send_message(int(chat_id), LANGS[lang].get("unknown_command", "Unknown command"))

# ---- Callback handler for deletion ----
@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("del:"))
def callback_delete(call):
    chat_id = str(call.from_user.id)
    _, rid = call.data.split(":", 1)
    with lock:
        items = reminders.get(chat_id, [])
        for i, it in enumerate(items):
            if it["id"] == rid:
                items.pop(i)
                save_data()
                bot.answer_callback_query(call.id, LANGS[user_languages.get(chat_id, "uz")].get("reminder_deleted", "Deleted"))
                safe_send_message(int(chat_id), LANGS[user_languages.get(chat_id, "uz")].get("reminder_deleted", "Deleted"))
                return
    bot.answer_callback_query(call.id, "Item not found")

# ---- Start polling ----
if __name__ == "__main__":
    print("Bot ishga tushdi...")
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except KeyboardInterrupt:
        print("Stopped by user")
