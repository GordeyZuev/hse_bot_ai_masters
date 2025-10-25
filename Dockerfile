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

# Копируем все файлы проекта (от root)
COPY --chown=app:app pyproject.toml uv.lock* README.md ./

# Переключаемся на пользователя app
USER app

# Устанавливаем Python зависимости через uv
RUN uv sync --frozen --no-dev

# Возвращаемся к root для копирования кода
USER root

# Копируем весь код приложения
COPY --chown=app:app . .

# Переключаемся обратно на пользователя app
USER app

# Создаем директории для логов
RUN mkdir -p logs

# Открываем порт (если понадобится для webhook)
EXPOSE 8000

# Команда по умолчанию - uv run автоматически активирует .venv
CMD ["uv", "run", "python", "main.py", "full"]