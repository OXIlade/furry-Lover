import os
import asyncio
import logging
import sqlite3
import datetime
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from contextlib import contextmanager
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest

# ========== НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))
# =======================================================

# === ФЕЙКОВЫЙ ВЕБ-СЕРВЕР ДЛЯ RENDER ===
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b"Furry Lover Bot is running!")

    def log_message(self, *args):
        pass

def run_web_server():
    try:
        port = int(os.environ.get('PORT', 10000))
        server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
        print(f"🌐 Веб-сервер запущен на порту {port}")
        server.serve_forever()
    except Exception as e:
        print(f"⚠️ Ошибка веб-сервера: {e}")

threading.Thread(target=run_web_server, daemon=True).start()
print("✅ Веб-сервер в фоне")

# =======================================================

logging.basicConfig(level=logging.INFO)
print("🚀 БОТ ЗАПУСКАЕТСЯ")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# === БАЗА ДАННЫХ ===
@contextmanager
def get_db():
    conn = sqlite3.connect('bot_database.db', timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id INTEGER PRIMARY KEY,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_topics (
                user_id INTEGER PRIMARY KEY,
                topic_id INTEGER
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_messages (
                user_id INTEGER,
                message_type TEXT,
                message_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

init_db()

def is_banned(user_id: int) -> bool:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,))
        return cur.fetchone() is not None

def ban_user(user_id: int):
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (user_id,))
        conn.commit()

def unban_user(user_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
        conn.commit()

def get_user_topic(user_id: int):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT topic_id FROM user_topics WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        return row[0] if row else None

def save_user_topic(user_id: int, topic_id: int):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO user_topics (user_id, topic_id) VALUES (?, ?)", (user_id, topic_id))
        conn.commit()

def is_spam(user_id: int, msg_type: str) -> bool:
    if msg_type == "text":
        seconds = 5
    elif msg_type in ("sticker", "animation"):
        seconds = 10
    else:
        return False
    with get_db() as conn:
        conn.execute(f"""
            DELETE FROM user_messages
            WHERE user_id = ? AND message_type = ?
            AND message_time < datetime('now', '-{seconds} seconds')
        """, (user_id, msg_type))
        cur = conn.cursor()
        cur.execute(f"""
            SELECT COUNT(*) FROM user_messages
            WHERE user_id = ? AND message_type = ?
            AND message_time > datetime('now', '-{seconds} seconds')
        """, (user_id, msg_type))
        count = cur.fetchone()[0]
        conn.execute("INSERT INTO user_messages (user_id, message_type) VALUES (?, ?)", (user_id, msg_type))
        conn.commit()
        return count >= 5

# === КОМАНДЫ ===
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("Привет! Отправь арт, он попадёт админу.")

@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    if message.chat.id != GROUP_ID:
        return
    if not message.reply_to_message or not message.reply_to_message.forward_from:
        await message.reply("❌ Ответь на сообщение пользователя")
        return
    user_id = message.reply_to_message.forward_from.id
    ban_user(user_id)
    await message.reply(f"✅ {user_id} забанен")

@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if message.chat.id != GROUP_ID:
        return
    try:
        user_id = int(message.text.split()[1])
        unban_user(user_id)
        await message.reply(f"✅ {user_id} разбанен")
    except:
        await message.reply("❌ /unban ID")

# === ГЛАВНЫЙ ОБРАБОТЧИК ===
@dp.message()
async def handle_all(message: Message):
    if message.chat.id == GROUP_ID:
        if message.reply_to_message and message.reply_to_message.forward_from:
            uid = message.reply_to_message.forward_from.id
            if is_banned(uid):
                await message.reply("❌ Пользователь заблокирован")
                return
            try:
                await bot.send_message(uid, f"📨 ответ от Furry Lover:\n\n{message.text}")
                await message.reply("✅ Ответ отправлен")
            except:
                await message.reply("❌ Ошибка")
        return

    user = message.from_user
    uid = user.id

    if is_banned(uid):
        await message.answer("❌ Вы заблокированы")
        return

    # Тип
    if message.photo:
        msg_type = "photo"
    elif message.sticker:
        msg_type = "sticker"
    elif message.animation:
        msg_type = "animation"
    elif message.text:
        msg_type = "text"
    else:
        msg_type = "other"

    if msg_type != "photo" and is_spam(uid, msg_type):
        await message.answer("⚠️ Слишком много сообщений, подожди")
        return

    try:
        topic_id = get_user_topic(uid)
        if not topic_id:
            topic_name = f"{user.full_name}" + (f" (@{user.username})" if user.username else "")
            topic = await bot.create_forum_topic(GROUP_ID, topic_name[:40])
            topic_id = topic.message_thread_id
            save_user_topic(uid, topic_id)
            await bot.send_message(GROUP_ID, message_thread_id=topic_id,
                                   text=f"👤 Новый: {user.full_name}\n🆔 {uid}")

        await bot.forward_message(GROUP_ID, uid, message.message_id, message_thread_id=topic_id)

        answers = {
            "photo": "✅ Арт у админа!",
            "sticker": "✅ Стикер у админа!",
            "animation": "✅ GIF у админа!",
        }
        await message.answer(answers.get(msg_type, "✅ Сообщение полетело админу^-^"))
    except Exception as e:
        logging.exception("Ошибка")
        await message.answer("❌ Ошибка")

# === ЗАПУСК ===
async def main():
    print("🤖 Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
