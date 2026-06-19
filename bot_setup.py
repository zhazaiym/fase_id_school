import os
import sqlite3
import sys
import traceback
from pathlib import Path

import msvcrt
from telegram import Update
from telegram.error import Conflict, Forbidden, InvalidToken, NetworkError, TelegramError, TimedOut
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.request import HTTPXRequest
from database import init_db

for proxy_name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(proxy_name, None)

TOKEN = "8819848632:AAEAigdVRaYAg9mcmSCi_kEA4MhyO-huLzw"
LOCK_FILE = Path("bot_setup.lock")
CONFLICT_STOP_REQUESTED = False


def acquire_single_instance_lock():
    lock_file = LOCK_FILE.open("w")
    try:
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock_file.close()
        print("Bot is already running in another terminal. Close the old bot_setup.py first.")
        return None

    lock_file.write(str(os.getpid()))
    lock_file.flush()
    return lock_file


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Салам! Мектеп системасына кош келиңиз.")


async def show_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your chat_id: {update.effective_chat.id}")


async def teacher_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("⚠️ Класс атын жазыңыз: /teacher 4_a")
        return

    class_name = "_".join(context.args).strip()
    conn = sqlite3.connect("school.db")
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO teachers (class_name, teacher_chat_id) VALUES (?, ?)",
                (class_name, str(chat_id)))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ {class_name} классына катталдыңыз.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    global CONFLICT_STOP_REQUESTED

    if isinstance(context.error, InvalidToken):
        print("Telegram bot error:")
        print("Bot token is invalid. Create a new token in BotFather.")
    elif isinstance(context.error, Conflict):
        if not CONFLICT_STOP_REQUESTED:
            CONFLICT_STOP_REQUESTED = True
            print("Telegram Conflict: this bot is already running in another terminal/process.")
            print("Stopping this copy. Leave only one python bot_setup.py running.")
            context.application.stop_running()
        return
    elif isinstance(context.error, Forbidden):
        print("Telegram bot error:")
        print("The user did not press /start or blocked the bot.")
    elif isinstance(context.error, TimedOut):
        print("Telegram bot error:")
        print("Telegram request timed out. Check internet/VPN access to api.telegram.org.")
    elif isinstance(context.error, NetworkError):
        print("Telegram bot error:")
        print(f"Telegram network error: {context.error}. Check internet/VPN/proxy/firewall.")
    elif isinstance(context.error, TelegramError):
        print("Telegram bot error:")
        print(f"Telegram API error: {context.error}")
    else:
        print("Telegram bot error:")
    traceback.print_exception(type(context.error), context.error, context.error.__traceback__)


def main():
    lock_file = acquire_single_instance_lock()
    if lock_file is None:
        sys.exit(1)

    init_db()

    # Көңүл буруңуз: request параметрин алып салдык!
    # Бул китепкананын ички механизми өзү эле туура иштетүүгө жетиштүү.
    request = HTTPXRequest(
        connect_timeout=20,
        read_timeout=30,
        write_timeout=30,
        pool_timeout=10,
    )
    updates_request = HTTPXRequest(
        connect_timeout=20,
        read_timeout=30,
        write_timeout=30,
        pool_timeout=10,
    )
    app = (
        Application.builder()
        .token(TOKEN)
        .request(request)
        .get_updates_request(updates_request)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", show_id))
    app.add_handler(CommandHandler("teacher", teacher_register))
    app.add_error_handler(error_handler)

    print("Bot is running...")
    try:
        app.run_polling(drop_pending_updates=True)
    except Conflict:
        print("Telegram Conflict: this bot token is already used by another running polling process.")
        print("Close all other terminals with python bot_setup.py, then run it once again.")


if __name__ == "__main__":
    main()
