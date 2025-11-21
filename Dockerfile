# Используем официальный Python образ
FROM python:3.11-slim

# Устанавливаем системные зависимости
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && unset DEBIAN_FRONTEND

# Устанавливаем uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Создаем пользователя для приложения
RUN useradd --create-home --shell /bin/bash app

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем права пользователю app на рабочую директорию
RUN chown -R app:app /app

# Копируем файлы, необходимые для установки зависимостей и сборки пакета
# README.md нужен для сборки пакета (указан в pyproject.toml как readme)
COPY --chown=app:app pyproject.toml uv.lock* README.md ./

# Переключаемся на пользователя app
USER app

# Устанавливаем Python зависимости через uv
# Этот слой будет кэшироваться, пока не изменятся pyproject.toml или uv.lock
RUN uv sync --frozen --no-dev

# Возвращаемся к root для копирования кода
USER root

COPY --chown=app:app . .

# Создаем директории для логов перед переключением пользователя
RUN mkdir -p logs && chown -R app:app logs

USER app

# Команда по умолчанию - uv run автоматически активирует .venv
CMD ["uv", "run", "python", "main.py", "full"]