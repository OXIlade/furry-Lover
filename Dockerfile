FROM python:3.11-slim

# Устанавливаем supervisor
RUN apt-get update && apt-get install -y supervisor && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install requests  # для пингера

COPY bot.py ping.py ./

# Конфиг supervisor для запуска двух процессов
RUN echo '[supervisord]\n\
nodaemon=true\n\
\n\
[program:bot]\n\
command=python bot.py\n\
directory=/app\n\
autostart=true\n\
autorestart=true\n\
\n\
[program:ping]\n\
command=python ping.py\n\
directory=/app\n\
autostart=true\n\
autorestart=true' > /etc/supervisor/conf.d/bot.conf

CMD ["supervisord", "-c", "/etc/supervisor/supervisord.conf"]
