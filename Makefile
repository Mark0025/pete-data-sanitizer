.PHONY: help install dev build serve test lint format clean docker-up docker-down docker-logs docker-rebuild health status

# Default target
.DEFAULT_GOAL := help

# Colors for output
CYAN := \033[0;36m
GREEN := \033[0;32m
RED := \033[0;31m
RESET := \033[0m

help: ## Show this help message
	@echo "$(CYAN)Pete DealMachine Cleaner - Available Commands:$(RESET)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(RESET) %s\n", $$1, $$2}'
	@echo ""

# ============================================================================
# Development Setup
# ============================================================================

install: ## Install dependencies via UV
	@echo "$(CYAN)Installing dependencies...$(RESET)"
	uv sync
	@echo "$(GREEN)✓ Dependencies installed$(RESET)"

dev-setup: install ## Full development setup (install + create config)
	@echo "$(CYAN)Setting up development environment...$(RESET)"
	@if [ ! -f config.yaml ]; then \
		cp config.example.yaml config.yaml; \
		echo "$(GREEN)✓ Created config.yaml from example$(RESET)"; \
	else \
		echo "$(GREEN)✓ config.yaml already exists$(RESET)"; \
	fi
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "$(GREEN)✓ Created .env from example$(RESET)"; \
	else \
		echo "$(GREEN)✓ .env already exists$(RESET)"; \
	fi
	@mkdir -p uploads/templates uploads/runs uploads/flowcharts
	@echo "$(GREEN)✓ Development environment ready!$(RESET)"

# ============================================================================
# Application Commands
# ============================================================================

dev: ## Start development server (native, with hot reload)
	@echo "$(CYAN)Starting development server...$(RESET)"
	@echo "$(CYAN)Server will be available at: http://localhost:8765$(RESET)"
	uv run python -m pete_dm_clean serve --reload

serve: dev ## Alias for 'dev'

build: ## Run the build pipeline (CLI)
	@echo "$(CYAN)Running build pipeline...$(RESET)"
	uv run python -m pete_dm_clean build

build-clean: ## Run build with randomized External IDs
	@echo "$(CYAN)Running build with randomized External IDs...$(RESET)"
	uv run python -m pete_dm_clean build --randomize-external-ids

build-contacts-only: ## Run build in contacts-only mode
	@echo "$(CYAN)Running build (contacts-only mode)...$(RESET)"
	uv run python -m pete_dm_clean build --contacts-only

build-debug: ## Run build with full debugging enabled
	@echo "$(CYAN)Running build with debug tracing...$(RESET)"
	uv run python -m pete_dm_clean build --trace-calls --debug-report --trace-max-events 500

menu: ## Launch interactive CLI menu
	uv run python -m pete_dm_clean menu

# ============================================================================
# Testing & Quality
# ============================================================================

test: ## Run test suite
	@echo "$(CYAN)Running tests...$(RESET)"
	uv run pytest -v

test-cov: ## Run tests with coverage report
	@echo "$(CYAN)Running tests with coverage...$(RESET)"
	uv run pytest --cov=pete_dm_clean --cov-report=term-missing --cov-report=html

test-watch: ## Run tests in watch mode
	@echo "$(CYAN)Running tests in watch mode...$(RESET)"
	uv run pytest-watch

lint: ## Run linting (Ruff)
	@echo "$(CYAN)Running linter...$(RESET)"
	uv run ruff check .

lint-fix: ## Run linting with auto-fix
	@echo "$(CYAN)Running linter with auto-fix...$(RESET)"
	uv run ruff check --fix .

format: ## Format code with Ruff
	@echo "$(CYAN)Formatting code...$(RESET)"
	uv run ruff format .

format-check: ## Check code formatting without changes
	@echo "$(CYAN)Checking code format...$(RESET)"
	uv run ruff format --check .

typecheck: ## Run type checking (Pyright)
	@echo "$(CYAN)Running type checker...$(RESET)"
	uv run pyright

check: lint format-check typecheck test ## Run all checks (lint, format, typecheck, test)

# ============================================================================
# Docker Commands
# ============================================================================

docker-build: ## Build Docker image
	@echo "$(CYAN)Building Docker image...$(RESET)"
	docker-compose build

docker-up: ## Start application in Docker (detached)
	@echo "$(CYAN)Starting application in Docker...$(RESET)"
	docker-compose up -d
	@echo "$(GREEN)✓ Application started$(RESET)"
	@echo "$(CYAN)Server available at: http://localhost:8765$(RESET)"
	@echo "$(CYAN)View logs: make docker-logs$(RESET)"

docker-up-dev: ## Start application in Docker with logs (foreground)
	@echo "$(CYAN)Starting application in Docker (foreground)...$(RESET)"
	docker-compose up

docker-down: ## Stop Docker containers
	@echo "$(CYAN)Stopping Docker containers...$(RESET)"
	docker-compose down
	@echo "$(GREEN)✓ Containers stopped$(RESET)"

docker-restart: docker-down docker-up ## Restart Docker containers

docker-rebuild: ## Rebuild and restart Docker containers
	@echo "$(CYAN)Rebuilding Docker containers...$(RESET)"
	docker-compose down
	docker-compose build --no-cache
	docker-compose up -d
	@echo "$(GREEN)✓ Containers rebuilt and started$(RESET)"

docker-logs: ## View Docker logs (follow)
	docker-compose logs -f

docker-shell: ## Open shell in running container
	docker-compose exec app /bin/bash

docker-clean: ## Remove Docker containers, volumes, and images
	@echo "$(RED)Cleaning Docker resources...$(RESET)"
	docker-compose down -v
	docker rmi pete-fernando-app_app 2>/dev/null || true
	@echo "$(GREEN)✓ Docker resources cleaned$(RESET)"

# ============================================================================
# Health & Status
# ============================================================================

health: ## Check application health
	@echo "$(CYAN)Checking application health...$(RESET)"
	@curl -f http://localhost:8765/health 2>/dev/null && echo "$(GREEN)✓ Application is healthy$(RESET)" || echo "$(RED)✗ Application is not responding$(RESET)"

status: ## Show application status
	@echo "$(CYAN)Application Status:$(RESET)"
	@echo ""
	@if docker-compose ps | grep -q "Up"; then \
		echo "$(GREEN)✓ Docker: Running$(RESET)"; \
		docker-compose ps; \
	else \
		echo "$(RED)✗ Docker: Not running$(RESET)"; \
	fi
	@echo ""
	@echo "$(CYAN)Checking HTTP endpoint...$(RESET)"
	@curl -f http://localhost:8765/health 2>/dev/null && echo "$(GREEN)✓ HTTP: Responding$(RESET)" || echo "$(RED)✗ HTTP: Not responding$(RESET)"

# ============================================================================
# Utility Commands
# ============================================================================

clean: ## Clean generated files and caches
	@echo "$(CYAN)Cleaning generated files...$(RESET)"
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .coverage htmlcov/ 2>/dev/null || true
	@echo "$(GREEN)✓ Cleaned$(RESET)"

clean-uploads: ## Clean uploads directory (DANGEROUS - backs up first)
	@echo "$(RED)WARNING: This will archive and clean uploads/$(RESET)"
	@read -p "Continue? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		tar -czf uploads-backup-$$(date +%Y%m%d-%H%M%S).tar.gz uploads/; \
		rm -rf uploads/*; \
		mkdir -p uploads/templates uploads/runs uploads/flowcharts; \
		echo "$(GREEN)✓ Uploads archived and cleaned$(RESET)"; \
	else \
		echo "$(CYAN)Cancelled$(RESET)"; \
	fi

logs: ## View latest run logs
	@echo "$(CYAN)Latest run logs:$(RESET)"
	@ls -t uploads/runs/*.log 2>/dev/null | head -1 | xargs cat || echo "$(RED)No logs found$(RESET)"

diagram: ## Generate pipeline diagram
	@echo "$(CYAN)Generating pipeline diagram...$(RESET)"
	uv run python -m pete_dm_clean diagram

version: ## Show application version
	@uv run python -c "from pete_dm_clean import __version__; print(f'Pete DealMachine Cleaner v{__version__}')"

# ============================================================================
# Production Commands
# ============================================================================

prod-up: ## Start in production mode (no reload, optimized)
	@echo "$(CYAN)Starting in production mode...$(RESET)"
	ENVIRONMENT=production docker-compose up -d
	@echo "$(GREEN)✓ Production server started$(RESET)"

prod-logs: ## View production logs
	docker-compose logs -f --tail=100

# ============================================================================
# Quick Start Commands
# ============================================================================

start: docker-up ## Quick start (Docker, detached)

stop: docker-down ## Quick stop

restart: docker-restart ## Quick restart

# ============================================================================
# Documentation
# ============================================================================

docs: ## Open documentation in browser
	@echo "$(CYAN)Opening documentation...$(RESET)"
	@if command -v open >/dev/null 2>&1; then \
		open README.md; \
	elif command -v xdg-open >/dev/null 2>&1; then \
		xdg-open README.md; \
	else \
		echo "$(CYAN)See README.md for documentation$(RESET)"; \
	fi
