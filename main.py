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
JSON_PATH = "droporders-288a5dfd161e.json"
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
        "Я уже здесь и разогрета до максимума!.\n"
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

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global total_messages, processed_messages, skipped_messages, current_row, last_order_data

    total_messages += 1
    print(f"\nОбрабатываю сообщение №{total_messages}")

    message = update.message

    if message.message_thread_id is not None and message.message_thread_id != ALLOWED_THREAD_ID:
        print(f"Пропущено: сообщение из другой темы (ID темы: {message.message_thread_id})")
        skipped_messages += 1
        return

    media_group_id = message.media_group_id

    if message.caption:
        caption = message.caption.strip()
        parts = [line.strip() for line in caption.split('\n') if line.strip()]

        size = parts[0] if parts else ""
        date_text = ""
        track_text = ""
        price = ""
        link = ""

        for part in parts[1:]:
            if "http" in part:
                link = part
            elif part.lower().startswith("от") or "от" in part.lower():
                date_text = part
            elif "+7" in part or "8" in part:
                track_text = part
            elif re.search(r"\d{1,2}\s[а-яА-Я]+", part):
                date_text = part
            elif ":" in part:
                track_text = part

        if not date_text:
            raise ValueError(f"Не удалось найти дату в сообщении: {caption}")

        formatted_date = parse_date(date_text)

        delivery_service = ""
        track_number = ""

        if track_text:
            if ":" in track_text:
                parts = track_text.split(":", 1)
                delivery_service = parts[0].strip()
                track_number = parts[1].strip()
            elif " " in track_text:
                parts = track_text.split(" ", 1)
                delivery_service = parts[0].strip()
                track_number = parts[1].strip()
            else:
                track_number = track_text

        if "?source=" in link:
            link = link.split("?source=")[0]

        last_order_data[media_group_id or message.message_id] = {
            "size": size,
            "date": formatted_date,
            "delivery_service": delivery_service,
            "track_number": track_number,
            "price": price,
            "link": link
        }

    order = last_order_data.get(media_group_id or message.message_id)
    if not order:
        print(f"Пропущено: нет сохранённых данных для этого фото")
        skipped_messages += 1
        return

    photo_formula = ""
    try:
        file = await context.bot.get_file(message.photo[-1].file_id)
        file_content = await file.download_as_bytearray()

        media = MediaInMemoryUpload(file_content, mimetype='image/jpeg')
        file_metadata = {'name': file.file_path.split('/')[-1], 'parents': [GOOGLE_DRIVE_FOLDER_ID]}
        uploaded_file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        photo_id = uploaded_file.get('id')

        drive_service.permissions().create(fileId=photo_id, body={'role': 'reader', 'type': 'anyone'}).execute()

        photo_formula = f'=IMAGE("https://drive.google.com/uc?export=view&id={photo_id}")'

        print("✅ Фото загружено и доступно")

    except Exception as e:
        print(f"⚠ Фото не загружено, заказ будет без фото: {e}")

    try:
        formatted_date = order["date"]
        order_month = formatted_date.split('.')[1]
        now_month = datetime.now().strftime("%m")

        worksheet_title = "Текущий" if order_month == now_month else f"{order_month}.25"
        worksheet = get_or_create_worksheet(worksheet_title)

        if worksheet_title not in current_row:
            existing_values = worksheet.get_all_values()
            current_row[worksheet_title] = len(existing_values) + 1

        this_row = current_row[worksheet_title]

        order_number_from_link = order["link"].split("/orders/")[-1] if "/orders/" in order["link"] else order["link"]

        new_row = [
            order["date"],
            "",
            order["size"],
            order["delivery_service"],
            order["track_number"],
            "",
            "",
            order["price"]
        ]

        worksheet.append_row(new_row)

        batch_update_body = {"valueInputOption": "USER_ENTERED", "data": []}

        if photo_formula:
            batch_update_body["data"].append({"range": f"{worksheet_title}!B{this_row}", "values": [[photo_formula]]})

        if order["link"]:
            batch_update_body["data"].append({"range": f"{worksheet_title}!F{this_row}", "values": [[f'=ГИПЕРССЫЛКА("{order["link"]}";"{order_number_from_link}")']]})

        batch_update_body["data"].append({"range": f"{worksheet_title}!G{this_row}", "values": [[""]]})

        if batch_update_body["data"]:
            sheets_service.spreadsheets().values().batchUpdate(spreadsheetId=GOOGLE_SHEET_ID, body=batch_update_body).execute()

        processed_messages += 1
        current_row[worksheet_title] += 1
        print(f"✅ Заказ добавлен (строка {this_row})")

    except Exception as e:
        print(f"❌ Ошибка при добавлении заказа в таблицу: {e}")
        skipped_messages += 1

async def shutdown(app):
    print("\n📋 ФИНАЛЬНЫЙ ОТЧЁТ:")
    print(f"Всего сообщений: {total_messages}")
    print(f"✅ Успешно обработано: {processed_messages}")
    print(f"❌ Пропущено: {skipped_messages}")
    print("\n🚀 Спасибо за работу!")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    loop = asyncio.get_event_loop()

    def handle_stop(*args):
        loop.create_task(shutdown(app))
        app.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_stop)

    app.run_polling()