import os
import asyncio
import logging
import sqlite3
import datetime
import time
from contextlib import contextmanager
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

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
                topic_id INTEGER,
                locked_until REAL DEFAULT 0
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

# === РАБОТА С ТЕМАМИ (С БЛОКИРОВКОЙ ЧЕРЕЗ БД) ===
def get_user_topic(user_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT topic_id FROM user_topics WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        return result[0] if result else None

def acquire_lock(user_id: int, timeout=10):
    """Пытаемся получить блокировку на создание темы"""
    start = time.time()
    while time.time() - start < timeout:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT locked_until FROM user_topics WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            
            now = time.time()
            if row is None:
                # Записи нет — вставляем с блокировкой
                cursor.execute(
                    "INSERT INTO user_topics (user_id, locked_until) VALUES (?, ?)",
                    (user_id, now + 30)
                )
                conn.commit()
                return True
            elif row[0] < now:
                # Блокировка истекла — забираем
                cursor.execute(
                    "UPDATE user_topics SET locked_until = ? WHERE user_id = ?",
                    (now + 30, user_id)
                )
                conn.commit()
                return True
        
        await asyncio.sleep(0.2)
    return False

def release_lock(user_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE user_topics SET locked_until = 0 WHERE user_id = ?", (user_id,))
        conn.commit()

def save_user_topic(user_id: int, topic_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO user_topics (user_id, topic_id, locked_until) VALUES (?, ?, 0)",
            (user_id, topic_id)
        )
        conn.commit()

# === АНТИСПАМ ===
def is_spam(user_id: int, msg_type: str) -> bool:
    if msg_type == "text":
        seconds = 5
    elif msg_type in ["sticker", "animation"]:
        seconds = 10
    else:
        return False

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            DELETE FROM user_messages 
            WHERE user_id = ? AND message_type = ? 
            AND message_time < datetime('now', '-{seconds} seconds')
        """, (user_id, msg_type))
        
        cursor.execute(f"""
            SELECT COUNT(*) FROM user_messages 
            WHERE user_id = ? AND message_type = ? 
            AND message_time > datetime('now', '-{seconds} seconds')
        """, (user_id, msg_type))
        
        count = cursor.fetchone()[0]
        cursor.execute("INSERT INTO user_messages (user_id, message_type) VALUES (?, ?)", 
                      (user_id, msg_type))
        conn.commit()
        return count >= 5

# === КОМАНДА СТАРТ ===
@dp.message(Command("start"))
async def start_command(message: Message):
    await message.answer(
        "Приветствую!\n\n"
        "Сюда вы можете отправить арт который вы хотите видеть на канале, "
        "и вскоре он может появится в посте furry lover. (ИИ не желательно)."
    )

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
    # Сообщения из группы (ответы админа)
    if message.chat.id == GROUP_ID:
        if message.reply_to_message and message.reply_to_message.forward_from:
            user_id = message.reply_to_message.forward_from.id
            
            if is_banned(user_id):
                await message.reply("❌ Пользователь заблокирован")
                return
            
            try:
                await bot.send_message(
                    user_id, 
                    f"📨 ответ от Furry Lover\n\n{message.text}"
                )
                await message.reply("✅ Ответ отправлен пользователю")
            except:
                await message.reply("❌ Ошибка при отправке")
        return
    
    # Сообщения от пользователей
    user = message.from_user
    user_id = user.id
    
    logging.info(f"📨 Сообщение от {user_id} (@{user.username})")
    
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
    
    # Антиспам
    if msg_type != "photo":
        if is_spam(user_id, msg_type):
            await message.answer("⚠️ Слишком много сообщений. Подождите немного.")
            return
    
    # === ГЛОБАЛЬНАЯ БЛОКИРОВКА ЧЕРЕЗ БД ===
    topic_id = get_user_topic(user_id)
    
    if topic_id is None:
        # Пытаемся захватить блокировку
        if not await acquire_lock(user_id):
            logging.warning(f"Не удалось получить блокировку для {user_id}, пропускаем")
            return
        
        try:
            # Двойная проверка после блокировки
            topic_id = get_user_topic(user_id)
            if topic_id is None:
                logging.info(f"🆕 Создаём тему для {user_id}")
                topic_name = f"{user.full_name}"
                if user.username:
                    topic_name += f" (@{user.username})"
                topic_name = topic_name[:40]
                
                topic = await bot.create_forum_topic(
                    chat_id=GROUP_ID,
                    name=topic_name
                )
                topic_id = topic.message_thread_id
                save_user_topic(user_id, topic_id)
                logging.info(f"✅ Тема {topic_id} сохранена для {user_id}")
                
                try:
                    await bot.send_message(
                        chat_id=GROUP_ID,
                        message_thread_id=topic_id,
                        text=f"👤 Новый пользователь: {user.full_name}\n🆔 ID: {user_id}"
                    )
                except TelegramRetryAfter as e:
                    logging.warning(f"⏳ Flood control: ждём {e.retry_after} сек")
                    await asyncio.sleep(e.retry_after)
                    await bot.send_message(
                        chat_id=GROUP_ID,
                        message_thread_id=topic_id,
                        text=f"👤 Новый пользователь: {user.full_name}\n🆔 ID: {user_id}"
                    )
        finally:
            release_lock(user_id)
    else:
        logging.info(f"📌 Использую существующую тему {topic_id} для {user_id}")
    
    # Пересылаем сообщение
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

# === ЗАПУСК С НОЧНЫМ РЕЖИМОМ ===
async def main():
    print(f"✅ Бот запущен! ID группы: {GROUP_ID}")
    
    while True:
        now_utc = datetime.datetime.now()
        now_msk = now_utc + datetime.timedelta(hours=3)
        current_time = now_msk.time()
        
        print(f"🕐 Текущее время (МСК): {now_msk.strftime('%H:%M')}")
        
        if datetime.time(0, 0) <= current_time <= datetime.time(7, 30):
            print("🌙 Ночной режим. Бот уходит в сон до 07:30 МСК...")
            
            wake_time_msk = now_msk.replace(hour=7, minute=30, second=0)
            wake_time_utc = wake_time_msk - datetime.timedelta(hours=3)
            sleep_seconds = (wake_time_utc - now_utc).total_seconds()
            
            if sleep_seconds < 0:
                wake_time_utc += datetime.timedelta(days=1)
                sleep_seconds = (wake_time_utc - now_utc).total_seconds()
            
            print(f"😴 Сон на {sleep_seconds / 3600:.2f} ч")
            await asyncio.sleep(sleep_seconds)
            print("🌞 Проснулись!")
        
        print("🤖 Бот работает...")
        await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
