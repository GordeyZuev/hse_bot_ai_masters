.PHONY: help install run lint lint-fix format clean logs update

help: ## Show help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies
	uv sync

install-dev: ## Install dev dependencies
	uv sync --group dev

run: ## Run bot with sync and notifications
	uv run python main.py full

lint: ## Check code with ruff
	uv run ruff check .

lint-fix: ## Auto-fix linting issues
	uv run ruff check . --fix --unsafe-fixes

format: ## Format code
	uv run ruff format .

clean: ## Clean temp files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true

logs: ## View today's logs
	tail -f logs/app_$(shell date +%Y-%m-%d).log

update: ## Stop containers, git pull, restart containers
	@echo "Stopping containers..."
	docker-compose down
	@echo "Pulling latest changes..."
	git pull
	@echo "Rebuilding containers..."
	docker-compose build --no-cache
	@echo "Starting containers..."
	docker-compose up -d
	@echo "Done! Check logs with: make logs"
