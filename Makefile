.PHONY: help install-uv install install-dev setup run lint lint-fix format format-check test check sync-dry clean logs deploy update migrate clean-docker clean-space db grant-db

help: ## Show help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install-uv: ## Install uv package manager
	@if ! command -v uv >/dev/null 2>&1; then \
		echo "Installing uv..."; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
		echo "uv installed successfully!"; \
		echo "Run 'source $$HOME/.cargo/env' or restart terminal to use uv"; \
	else \
		echo "uv is already installed"; \
	fi

install: ## Install dependencies
	@if ! command -v uv >/dev/null 2>&1; then \
		echo "uv is not installed. Run 'make install-uv' first"; \
		exit 1; \
	fi
	uv sync

install-dev: ## Install dev dependencies
	@if ! command -v uv >/dev/null 2>&1; then \
		echo "uv is not installed. Run 'make install-uv' first"; \
		exit 1; \
	fi
	uv sync --group dev

setup: install-uv install ## Complete setup: install uv and dependencies
	@echo "Setup complete! You can now run 'make run' to start the bot."

run: ## Run bot with sync and notifications
	uv run python main.py full

lint: ## Check code with ruff
	uv run ruff check .

lint-fix: ## Auto-fix linting issues
	uv run ruff check . --fix --unsafe-fixes

format: ## Format code
	uv run ruff format .

format-check: ## Check code formatting without changing files
	uv run ruff format --check .

test: ## Run tests
	uv run pytest

check: lint format-check test ## Run local quality gate
	uv run alembic upgrade head --sql >/dev/null

sync-dry: ## Validate Google Sheets without changing the database
	uv run python main.py sync --dry-run

clean: ## Clean temp files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true

logs: ## View the current application log
	tail -f $$(ls -t logs/app_[0-9]*.log | head -1)

deploy: ## Build and deploy the current checkout (no git pull)
	@./scripts/deploy.sh

update: ## Pull the latest commit, then build and deploy it
	@./scripts/deploy.sh --pull

migrate: ## Back up and migrate DB; requires the app to be stopped
	@./scripts/deploy.sh --migrate-only

clean-docker: ## Clean unused Docker images, containers, and build cache
	@echo "Cleaning unused Docker data..."
	docker builder prune -a -f
	docker image prune -a -f
	docker container prune -f
	@echo "Docker cleanup complete! Run 'docker system df' to see freed space."

clean-space: ## Clean old unused containers, images and free up disk space (preserves volumes)
	@echo "🧹 Очистка старых неиспользуемых Docker ресурсов..."
	@echo "📊 Использование места до очистки:"
	@docker system df
	@echo ""
	@echo "🗑️  Удаление остановленных контейнеров..."
	@docker container prune -f
	@echo "🗑️  Удаление неиспользуемых образов..."
	@docker image prune -a -f
	@echo "🗑️  Удаление build cache..."
	@docker builder prune -a -f
	@echo ""
	@echo "📊 Использование места после очистки:"
	@docker system df
	@echo ""
	@echo "✅ Очистка завершена!"

db: ## Connect to PostgreSQL database
	docker compose --env-file src/config/.env exec db sh -c 'exec psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

grant-db: ## Grant privileges to user on all tables (run once if migrations fail)
	@./scripts/grant-privileges.sh
