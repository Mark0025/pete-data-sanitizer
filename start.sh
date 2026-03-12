#!/usr/bin/env bash

###############################################################################
# Pete DealMachine Cleaner - Production-Grade Startup Script
###############################################################################
#
# This script provides a robust way to start the application with:
# - Dependency checking
# - Environment validation
# - Graceful error handling
# - Health check verification
# - Multiple startup modes (native, Docker, development, production)
#
# Usage:
#   ./start.sh [mode]
#
# Modes:
#   dev      - Start native development server with hot reload (default)
#   prod     - Start native production server (no reload)
#   docker   - Start via Docker Compose (detached)
#   docker-dev - Start via Docker Compose (foreground with logs)
#   help     - Show this help message
#
###############################################################################

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Colors
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[0;33m'
readonly CYAN='\033[0;36m'
readonly RESET='\033[0m'

# Configuration
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly APP_NAME="Pete DealMachine Cleaner"
readonly DEFAULT_PORT="${PORT:-8765}"
readonly HEALTH_CHECK_URL="http://localhost:${DEFAULT_PORT}/health"
readonly HEALTH_CHECK_TIMEOUT=30
readonly HEALTH_CHECK_INTERVAL=2

###############################################################################
# Logging Functions
###############################################################################

log_info() {
    echo -e "${CYAN}[INFO]${RESET} $*"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${RESET} $*"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${RESET} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${RESET} $*" >&2
}

###############################################################################
# Dependency Checks
###############################################################################

check_command() {
    local cmd="$1"
    if ! command -v "$cmd" &> /dev/null; then
        log_error "Required command not found: $cmd"
        return 1
    fi
    return 0
}

check_dependencies() {
    log_info "Checking dependencies..."

    local missing_deps=()

    # Check for UV
    if ! check_command "uv"; then
        missing_deps+=("uv")
        log_warning "UV not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    fi

    # Check for Python
    if ! check_command "python3"; then
        missing_deps+=("python3")
    fi

    if [ ${#missing_deps[@]} -gt 0 ]; then
        log_error "Missing required dependencies: ${missing_deps[*]}"
        log_info "Please install missing dependencies and try again."
        exit 1
    fi

    log_success "All dependencies found"
}

check_docker_dependencies() {
    log_info "Checking Docker dependencies..."

    if ! check_command "docker"; then
        log_error "Docker not found. Install from: https://docs.docker.com/get-docker/"
        exit 1
    fi

    if ! check_command "docker-compose"; then
        log_error "Docker Compose not found. Install from: https://docs.docker.com/compose/install/"
        exit 1
    fi

    # Check if Docker daemon is running
    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running. Please start Docker and try again."
        exit 1
    fi

    log_success "Docker dependencies OK"
}

###############################################################################
# Environment Setup
###############################################################################

setup_environment() {
    log_info "Setting up environment..."

    cd "$SCRIPT_DIR"

    # Create .env if it doesn't exist
    if [ ! -f .env ]; then
        if [ -f .env.example ]; then
            log_warning ".env not found, copying from .env.example"
            cp .env.example .env
            log_success "Created .env file"
        else
            log_warning ".env and .env.example not found, creating minimal .env"
            cat > .env << 'EOF'
ENVIRONMENT=development
PORT=8765
LOG_LEVEL=INFO
UPLOADS_DIR=uploads
DB_ENABLED=0
EOF
            log_success "Created minimal .env file"
        fi
    fi

    # Source environment variables
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a

    # Create necessary directories
    mkdir -p uploads/{templates,runs,flowcharts,companies}

    log_success "Environment ready"
}

###############################################################################
# Dependency Installation
###############################################################################

install_dependencies() {
    log_info "Installing Python dependencies..."

    if ! uv sync; then
        log_error "Failed to install dependencies"
        exit 1
    fi

    log_success "Dependencies installed"
}

###############################################################################
# Health Check
###############################################################################

wait_for_health() {
    log_info "Waiting for application to become healthy..."

    local elapsed=0
    while [ $elapsed -lt $HEALTH_CHECK_TIMEOUT ]; do
        if curl -f -s "$HEALTH_CHECK_URL" > /dev/null 2>&1; then
            log_success "Application is healthy!"

            # Show health details
            log_info "Health check details:"
            curl -s "$HEALTH_CHECK_URL" | python3 -m json.tool 2>/dev/null || true

            return 0
        fi

        sleep $HEALTH_CHECK_INTERVAL
        elapsed=$((elapsed + HEALTH_CHECK_INTERVAL))
        echo -n "."
    done

    echo ""
    log_warning "Health check timed out after ${HEALTH_CHECK_TIMEOUT}s"
    log_info "Application may still be starting. Check manually: $HEALTH_CHECK_URL"
    return 1
}

###############################################################################
# Startup Modes
###############################################################################

start_dev() {
    log_info "Starting $APP_NAME in DEVELOPMENT mode..."

    check_dependencies
    setup_environment
    install_dependencies

    log_info "Starting server on http://localhost:${DEFAULT_PORT}"
    log_info "Press Ctrl+C to stop"
    echo ""

    # Start with reload enabled
    # Convert LOG_LEVEL to lowercase for uvicorn
    local log_level_lower="${LOG_LEVEL:-info}"
    log_level_lower="${log_level_lower,,}"

    exec uv run uvicorn pete_dm_clean.server:app \
        --host 0.0.0.0 \
        --port "${DEFAULT_PORT}" \
        --reload \
        --log-level "${log_level_lower}"
}

start_prod() {
    log_info "Starting $APP_NAME in PRODUCTION mode..."

    check_dependencies
    setup_environment
    install_dependencies

    log_info "Starting server on http://localhost:${DEFAULT_PORT}"
    log_info "Press Ctrl+C to stop"
    echo ""

    # Start without reload, optimized
    # Convert LOG_LEVEL to lowercase for uvicorn
    local log_level_lower="${LOG_LEVEL:-warning}"
    log_level_lower="${log_level_lower,,}"

    exec uv run uvicorn pete_dm_clean.server:app \
        --host 0.0.0.0 \
        --port "${DEFAULT_PORT}" \
        --workers 2 \
        --log-level "${log_level_lower}"
}

start_docker() {
    log_info "Starting $APP_NAME via Docker (detached)..."

    check_docker_dependencies
    setup_environment

    docker-compose up -d

    log_success "Docker containers started"
    log_info "Server: http://localhost:${DEFAULT_PORT}"
    log_info "View logs: docker-compose logs -f"
    log_info "Stop: docker-compose down"

    wait_for_health || true
}

start_docker_dev() {
    log_info "Starting $APP_NAME via Docker (foreground)..."

    check_docker_dependencies
    setup_environment

    log_info "Press Ctrl+C to stop"
    echo ""

    exec docker-compose up
}

###############################################################################
# Help Message
###############################################################################

show_help() {
    cat << EOF
${CYAN}$APP_NAME - Startup Script${RESET}

${GREEN}Usage:${RESET}
  ./start.sh [mode]

${GREEN}Modes:${RESET}
  dev         Start native development server with hot reload (default)
  prod        Start native production server (no reload, optimized)
  docker      Start via Docker Compose (detached, background)
  docker-dev  Start via Docker Compose (foreground with logs)
  help        Show this help message

${GREEN}Examples:${RESET}
  ./start.sh              # Start in dev mode (default)
  ./start.sh dev          # Same as above
  ./start.sh prod         # Production mode
  ./start.sh docker       # Docker detached
  PORT=9000 ./start.sh    # Custom port

${GREEN}Environment Variables:${RESET}
  PORT              Server port (default: 8765)
  ENVIRONMENT       development, staging, or production
  LOG_LEVEL         Logging level (DEBUG, INFO, WARNING, ERROR)
  UPLOADS_DIR       Directory for file storage

${GREEN}Configuration:${RESET}
  Edit .env for persistent settings
  Edit config.yaml for pipeline defaults

${GREEN}Common Tasks:${RESET}
  Build import files:    uv run python -m pete_dm_clean build
  Run tests:            uv run pytest
  View logs:            make logs
  Health check:         curl http://localhost:${DEFAULT_PORT}/health

${GREEN}More Commands:${RESET}
  See Makefile for additional commands: make help

EOF
}

###############################################################################
# Main
###############################################################################

main() {
    local mode="${1:-dev}"

    case "$mode" in
        dev)
            start_dev
            ;;
        prod)
            start_prod
            ;;
        docker)
            start_docker
            ;;
        docker-dev)
            start_docker_dev
            ;;
        help|--help|-h)
            show_help
            exit 0
            ;;
        *)
            log_error "Unknown mode: $mode"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

# Trap Ctrl+C for graceful shutdown
trap 'echo ""; log_info "Shutting down..."; exit 0' SIGINT SIGTERM

main "$@"
