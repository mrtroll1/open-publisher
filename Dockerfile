FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ common/
COPY backend/ backend/
COPY telegram_bot/ telegram_bot/
COPY templates/ templates/
COPY knowledge/ knowledge/

CMD ["python", "-m", "telegram_bot.main"]
