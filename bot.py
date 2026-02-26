import os
import asyncio
import logging
import sqlite3
import datetime
from contextlib import contextmanager
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))
# ================================

logging.basicConfig(level=logging.INFO)
print("=" * 50)
print("🚀 БОТ ЗАПУСКАЕТСЯ")
print("=" * 50)

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
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id INTEGER PRIMARY KEY,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_topics (
                user_id INTEGER PRIMARY KEY,
                topic_id INTEGER
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_messages (
                user_id INTEGER,
                message_type TEXT,
                message_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
    print("✅ База данных инициализирована")

init_db()

# === РАБОТА С БАНАМИ ===
def is_banned(user_id: int) -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None

def ban_user(user_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (user_id,))
        conn.commit()

def unban_user(user_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
        conn.commit()

# === РАБОТА С ТЕМАМИ ===
def get_user_topic(user_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT topic_id FROM user_topics WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        return result[0] if result else None

def save_user_topic(user_id: int, topic_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO user_topics (user_id, topic_id) VALUES (?, ?)", (user_id, topic_id))
        conn.commit()

# === КОМАНДА СТАРТ ===
@dp.message(Command("start"))
async def start_command(message: Message):
    await message.answer("Привет! Отправь арт, он попадёт админу.")

# === КОМАНДЫ АДМИНА ===
@dp.message(Command("ban"))
async def ban_command(message: Message):
    if message.chat.id != GROUP_ID:
        return
    if not message.reply_to_message or not message.reply_to_message.forward_from:
        await message.reply("❌ Ответь на сообщение пользователя")
        return
    user_id = message.reply_to_message.forward_from.id
    ban_user(user_id)
    await message.reply(f"✅ Пользователь {user_id} заблокирован")

@dp.message(Command("unban"))
async def unban_command(message: Message):
    if message.chat.id != GROUP_ID:
        return
    try:
        user_id = int(message.text.split()[1])
        unban_user(user_id)
        await message.reply(f"✅ Пользователь {user_id} разблокирован")
    except:
        await message.reply("❌ Использование: /unban USER_ID")

# === ГЛАВНЫЙ ОБРАБОТЧИК ===
@dp.message()
async def handle_all_messages(message: Message):
    if message.chat.id == GROUP_ID:
        if message.reply_to_message and message.reply_to_message.forward_from:
            user_id = message.reply_to_message.forward_from.id
            if is_banned(user_id):
                await message.reply("❌ Пользователь заблокирован")
                return
            try:
                await bot.send_message(user_id, f"📨 ответ от Furry Lover\n\n{message.text}")
                await message.reply("✅ Ответ отправлен пользователю")
            except:
                await message.reply("❌ Ошибка при отправке")
        return

    user = message.from_user
    user_id = user.id

    if is_banned(user_id):
        await message.answer("❌ Вы заблокированы")
        return

    # Тип сообщения
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

    try:
        topic_id = get_user_topic(user_id)
        
        if not topic_id:
            topic_name = f"{user.full_name}"
            if user.username:
                topic_name += f" (@{user.username})"
            topic_name = topic_name[:40]
            
            topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=topic_name)
            topic_id = topic.message_thread_id
            save_user_topic(user_id, topic_id)
            
            await bot.send_message(
                chat_id=GROUP_ID,
                message_thread_id=topic_id,
                text=f"👤 Новый пользователь: {user.full_name}\n🆔 ID: {user_id}"
            )
        
        await bot.forward_message(
            chat_id=GROUP_ID,
            from_chat_id=user_id,
            message_id=message.message_id,
            message_thread_id=topic_id
        )
        
        if msg_type == "photo":
            await message.answer("✅ Арт отправлен администратору на рассмотрение!")
        elif msg_type == "sticker":
            await message.answer("✅ Стикер отправлен администратору!")
        elif msg_type == "animation":
            await message.answer("✅ GIF отправлен администратору!")
        else:
            await message.answer("✅ Сообщение полетело админу^-^")
            
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")

# === ЗАПУСК ===
async def main():
    print(f"✅ Бот запущен! ID группы: {GROUP_ID}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
