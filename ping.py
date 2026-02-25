import requests
import time
import os

# URL твоего бота на Render (вставишь позже)
BOT_URL = os.getenv("RENDER_URL", "https://твой-бот.onrender.com")

while True:
    try:
        # Пингуем бота
        response = requests.get(BOT_URL)
        print(f"Пинг отправлен в {time.ctime()}. Статус: {response.status_code}")
    except Exception as e:
        print(f"Ошибка пинга: {e}")
    
    # Ждём 10 минут
    time.sleep(600)
