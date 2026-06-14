import os
import sqlite3
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from database import init_db

# Проксини системадан өчүрүү
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)

TOKEN = "8819848632:AAEAigdVRaYAg9mcmSCi_kEA4MhyO-huLzw"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Салам! Мектеп системасына кош келиңиз.")


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


def main():
    init_db()

    # Көңүл буруңуз: request параметрин алып салдык!
    # Бул китепкананын ички механизми өзү эле туура иштетүүгө жетиштүү.
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("teacher", teacher_register))

    print("🚀 Бот иштеп жатат...")
    app.run_polling()


if __name__ == "__main__":
    main()