import logging
import gspread
import re
import asyncio
import signal
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from datetime import datetime

# --- Настройки ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = "8140549776:AAGNFQ32trak1fkCuBxmW5p99rsci3HvC9k"
GOOGLE_SHEET_ID = "1sSKRIPV-d4JLsQ3UL5BO5Xi9UwwFB5DRJumf2KgvKA0"
JSON_PATH = "droporders-8bf97332068b.json"
GOOGLE_DRIVE_FOLDER_ID = "1oncIzcRaMTzdO07gmXJKcn8cG8MdqHch"
ALLOWED_THREAD_ID = 2

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets"
]
creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_PATH, scope)
gc = gspread.authorize(creds)
drive_service = build('drive', 'v3', credentials=creds)
sheets_service = build('sheets', 'v4', credentials=creds)

HEADER = ["Дата", "Фото", "Размер", "Служба доставки", "Трек-номер", "Ссылка на заказ", "Статус", "Цена"]

MONTHS = {
    "января": "01", "февраля": "02", "марта": "03", "апреля": "04",
    "мая": "05", "июня": "06", "июля": "07", "августа": "08",
    "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12"
}

total_messages = 0
processed_messages = 0
skipped_messages = 0
current_row = {}
last_order_data = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 Добрый день, шеф!\n"
        "Я уже здесь и разогрета до максимума!\n"
        "Всё готово к приёму новых задач — давай начнём! 🚀"
    )

def get_or_create_worksheet(sheet_name):
    try:
        worksheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = gc.open_by_key(GOOGLE_SHEET_ID).add_worksheet(title=sheet_name, rows="1000", cols="10")
        worksheet.append_row(HEADER)
    return worksheet

def parse_date(text):
    match = re.search(r"(\d{1,2})\s([а-яА-Я]+)", text)
    if match:
        day = match.group(1)
        month_name = match.group(2).lower()
        month_num = MONTHS.get(month_name)
        if month_num:
            return f"{day.zfill(2)}.{month_num}"

    match = re.search(r"от\s+(\d{1,2})\s+([а-яА-Я]+)", text.lower())
    if match:
        day = match.group(1)
        month_name = match.group(2).lower()
        month_num = MONTHS.get(month_name)
        if month_num:
            return f"{day.zfill(2)}.{month_num}"

    raise ValueError(f"Не удалось распарсить дату из строки: {text}")

async def debug_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if message:
        print(f"\n‼️ Поймал сообщение!")
        print(f"message_id: {message.message_id}")
        print(f"message_thread_id: {message.message_thread_id}")
        print(f"caption: {message.caption}")
        print(f"text: {message.text}")

async def shutdown(app):
    print("\n📋 ФИНАЛЬНЫЙ ОТЧёТ:")
    print(f"Всего сообщений: {total_messages}")
    print(f"✅ Успешно обработано: {processed_messages}")
    print(f"❌ Пропущено: {skipped_messages}")
    print("\n🚀 Спасибо за работу!")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, debug_message))

    loop = asyncio.get_event_loop()

    def handle_stop(*args):
        loop.create_task(shutdown(app))
        app.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_stop)

    app.run_polling()
