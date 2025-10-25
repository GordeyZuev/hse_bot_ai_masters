# Используем официальный Python образ
FROM python:3.11-slim

# Устанавливаем системные зависимости
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && unset DEBIAN_FRONTEND

# Устанавливаем uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Создаем пользователя для приложения
RUN useradd --create-home --shell /bin/bash app

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы проекта
COPY pyproject.toml uv.lock* ./

# Устанавливаем Python зависимости через uv
RUN uv sync --frozen --no-dev

# Копируем код приложения
COPY . .

# Создаем директории для логов и данных
RUN mkdir -p logs && \
    chown -R app:app /app

# Переключаемся на пользователя app
USER app

# Открываем порт (если понадобится для webhook)
EXPOSE 8000

# Команда по умолчанию
CMD ["uv", "run", "python", "main.py", "full"]