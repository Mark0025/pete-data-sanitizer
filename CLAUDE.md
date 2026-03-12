# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 🎯 Quick Start (30 Second Version)

**Pete DealMachine Cleaner** transforms DealMachine exports into Pete Properties Import-ready files.

```bash
# First time setup
make dev-setup

# Start application (choose one)
make start          # Docker (recommended)
./start.sh dev      # Native with hot reload

# Build pipeline (process data)
make build          # Standard build
make build-clean    # With randomized External IDs

# Run tests
make test
```

**Web UI**: http://localhost:8765/ui
**Version**: 0.0.6 | **Python**: 3.12+ | **Package Manager**: UV (never pip)

## 📚 Documentation Structure

This project uses **modular documentation** for maintainability. The docs are split by context:

| File | Purpose | When to Read |
|------|---------|--------------|
| **CLAUDE.md** (this file) | Quick reference + navigation | Always start here |
| **[.claude/backend.md](.claude/backend.md)** | Pipeline architecture, RunTracker, generators | Working on data processing |
| **[.claude/frontend.md](.claude/frontend.md)** | FastAPI server, Jinja2 UI, endpoints | Working on web UI |
| **[.claude/testing.md](.claude/testing.md)** | Test patterns, pytest config, fixtures | Writing/debugging tests |
| **[.claude/deployment.md](.claude/deployment.md)** | Docker, systemd, nginx, production | Deploying to production |
| **[lego.md](lego.md)** | Conceptual "factory" explanation | Understanding the big picture |
| **[README.md](README.md)** | User-facing documentation | End-user guide |
| **[STARTUP_GUIDE.md](STARTUP_GUIDE.md)** | Senior-level startup best practices | Production deployment |

## 🏗️ Architecture at a Glance

### Core Workflow
```
DealMachine CSV → Load → Normalize → Dedupe → Rank Sellers → Fill Template → Export
                              ↓
                        RunTracker records everything
                              ↓
                    JSON + MD + Logs + Diagrams
```

### Key Concepts

**RunTracker** - The "factory clipboard" that records what happens during each build
- One tracker per run (never create multiple)
- Use `set_tracker()` / `get_tracker()` context helpers
- See: [.claude/backend.md#runtracker-system](.claude/backend.md#runtracker-system)

**Template Inheritance** - Registry-based generator system
- Excel template defines the schema
- Generators fill columns with decorators
- See: [.claude/backend.md#template-inheritance](.claude/backend.md#template-inheritance)

**Client Scoping** - Multi-tenant workspace isolation
- UUID-backed company IDs (UI calls them "Clients")
- Separate dirs for inputs/outputs/runs per client
- See: [.claude/backend.md#client-scoping](.claude/backend.md#client-scoping)

## 🚀 Common Commands (Cheat Sheet)

### Development
```bash
# Setup
make dev-setup              # First-time setup (install + config)
make install                # Just install dependencies

# Run application
make start                  # Docker (production-like)
make dev                    # Native with hot reload
./start.sh dev              # Script with health checks

# Build pipeline
make build                  # Standard build
make build-clean           # With randomized External IDs
make build-contacts-only   # Contacts-only mode
make build-debug           # Deep debugging with tracing
uv run python -m pete_dm_clean menu  # Interactive menu

# Development utilities
make logs                   # View latest run logs
make health                 # Check health endpoint
make status                 # Docker + HTTP status
make version                # Show app version
```

### Testing
```bash
make test                   # Run all tests
make test-cov              # Tests with coverage
uv run pytest tests/test_template_inherit.py -v  # Single file
```
See: [.claude/testing.md](.claude/testing.md)

### Code Quality
```bash
make lint                   # Check code quality
make lint-fix              # Auto-fix issues
make format                # Format code
make check                 # All checks (lint + format + typecheck + test)
```

### Docker
```bash
make docker-up             # Start Docker
make docker-down           # Stop Docker
make docker-logs           # View logs (follow)
make docker-shell          # Shell into container
make docker-rebuild        # Rebuild from scratch
```
See: [.claude/deployment.md](.claude/deployment.md)

## 📂 Project Structure

```
app/
├── pete_dm_clean/              # Main package
│   ├── cli.py                  # ⚡ CLI entrypoint (Typer commands)
│   ├── server.py               # 🌐 FastAPI web UI
│   ├── runtime.py              # 📋 RunTracker system
│   ├── generators.py           # 🏭 Template generators
│   ├── template_inherit.py     # 🎨 Generator registry
│   ├── companies.py            # 👥 Client scoping
│   ├── diagrams.py             # 📊 Flow diagrams
│   ├── config.py               # ⚙️ YAML config
│   ├── app_config.py           # 📝 Pydantic models
│   ├── logging.py              # 📝 Loguru setup
│   ├── debug_report.py         # 🔍 Deep debugging
│   └── db/                     # 🗄️ Optional SQLite/Postgres
├── build_staging.py            # 🔧 Core pipeline (run_build)
├── loaders.py                  # 📥 CSV parsing
├── tests/                      # ✅ Pytest suite
├── uploads/                    # 📁 I/O directory
│   ├── templates/              # Excel templates
│   ├── runs/                   # Run records (JSON, MD, logs)
│   ├── flowcharts/             # Generated diagrams
│   └── companies/              # Client workspaces
├── .cursor/rules/              # 📜 Cursor AI rules
├── config.yaml                 # ⚙️ User config
├── Makefile                    # 🛠️ ~40 commands
├── start.sh                    # 🚀 Startup script
├── docker-compose.yml          # 🐳 Docker orchestration
└── .claude/                    # 📚 Modular docs (NEW!)
    ├── backend.md
    ├── frontend.md
    ├── testing.md
    └── deployment.md
```

## 🎨 Cursor Rules Summary

This project includes `.cursor/rules/` for AI coding assistants:

- **runtime-tracker.mdc**: One tracker per run, entrypoint creation, context helpers
- **pytestnosandbox.mdc**: Don't run pytest in sandboxes, ask user to run locally
- **pythonic.mdc**: Small testable functions, dataclasses, pathlib, type hints
- **pydantic.mdc**: FastAPI conventions, Pydantic models, predictable endpoints
- **mappingmanifest.mdc**: Template-driven mapping manifests for each run

**Key Rules to Remember:**
1. **One RunTracker per run** - Create at entrypoint, pass down via context
2. **Template drives schema** - Excel template is canonical, generators follow it
3. **Don't run pytest in tools** - Ask user to run locally and share results
4. **Keep code Pythonic** - Small functions, dataclasses, pathlib, clear errors

## 🔍 Entry Points (Where Things Start)

| Entry Point | Purpose | File |
|-------------|---------|------|
| **CLI** | Main command interface | `pete_dm_clean/cli.py` → `main()` |
| **Web Server** | FastAPI UI | `pete_dm_clean/server.py` → `app` |
| **Core Pipeline** | Build orchestration | `build_staging.py` → `run_build()` |
| **Tests** | Pytest suite | `tests/conftest.py` → fixtures |
| **Docker** | Container startup | `Dockerfile` → `CMD` |
| **Systemd** | Linux service | `pete-dm-clean.service` |

## 🧩 When to Read Which Doc

### Working on Backend / Data Pipeline?
→ Read [.claude/backend.md](.claude/backend.md)
- RunTracker system and context helpers
- Template inheritance and generator registry
- Client scoping and workspace isolation
- Loaders and CSV parsing
- Pipeline step-by-step breakdown

### Working on Frontend / Web UI?
→ Read [.claude/frontend.md](.claude/frontend.md)
- FastAPI server architecture
- Jinja2 templates and UI routes
- Upload handling and file serving
- Health endpoints and monitoring
- Client management interface

### Writing or Debugging Tests?
→ Read [.claude/testing.md](.claude/testing.md)
- Pytest configuration and fixtures
- Test patterns and conventions
- Running tests (local vs CI)
- Coverage and quality checks
- Test logs location

### Deploying to Production?
→ Read [.claude/deployment.md](.claude/deployment.md)
- Docker Compose setup
- Systemd service configuration
- Nginx reverse proxy
- Health checks and monitoring
- Environment variables
- Scaling considerations

## 🐛 Quick Troubleshooting

| Problem | Solution |
|---------|----------|
| **uv command not found** | `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Port 8765 in use** | `lsof -i :8765` then `kill -9 <PID>` or use `--port 9000` |
| **Import only loads some rows** | Use `make build-clean` (randomizes External IDs) |
| **Tests failing** | Ensure in repo root: `uv sync && uv run pytest -v` |
| **Server won't start** | Check `make health` and `make docker-logs` |
| **Wrong seller selected** | Review ranking logic in `build_staging.py::_rank_contacts()` |
| **Docker build fails** | Try `make docker-rebuild` |

See detailed troubleshooting in respective `.claude/*.md` files.

## 🎓 Design Principles

### 1. One Tracker Per Run
**Never** create multiple RunTrackers in a single pipeline execution. Create once at entrypoint, pass via context helpers.

### 2. Template-Driven Schema
The Excel template in `uploads/templates/` is the **canonical schema**. Generators must follow it exactly.

### 3. Build Is Independent of Server
- **Build**: Writes files directly to disk (no server needed)
- **Server**: Optional viewer for existing files

### 4. Learning Mode Off By Default
Call tracing is disabled by default (noisy, slower). Enable with `--trace-calls` only when debugging.

### 5. Client Scoping Is Optional
Default mode works without clients. Client scoping adds multi-tenant workspace isolation when needed.

## 📊 File Outputs After Build

```
uploads/
├── PETE.DM.FERNANDO.CLEAN.<date>.xlsx     # Main import file (upload this)
├── PETE.DM.FERNANDO.CLEAN.<date>.csv      # Optional CSV
├── PETE.DM.FERNANDO.CLEAN.<date>.seller_summary.csv  # Review sheet
├── staging_report.json                     # Summary stats
├── staging_report.md                       # Client-facing report
├── staging_report_addresses.csv            # Per-address stats
├── staging_report_global_phones.csv        # Phone collisions
├── staging_report_global_emails.csv        # Email collisions
├── runs/<run_id>.json                      # Machine-readable run record
├── runs/<run_id>.summary.md                # Human-readable summary
├── runs/<run_id>.log                       # Loguru log file
├── runs/<run_id>.mapping.json              # Template mapping
└── flowcharts/acki_run_<run_id>.flow.txt  # Runtime diagram
```

Also copies to: `~/Desktop/Downloads/fernando.dealmachine.clean.<date>/`

## 🔗 Quick Links

- **[Backend Architecture](.claude/backend.md)** - Pipeline, RunTracker, generators
- **[Frontend/Server](.claude/frontend.md)** - Web UI, FastAPI, endpoints
- **[Testing Guide](.claude/testing.md)** - Pytest patterns, fixtures, coverage
- **[Deployment](.claude/deployment.md)** - Docker, systemd, nginx, production
- **[Conceptual Guide](lego.md)** - "Lego factory" explanation
- **[User README](README.md)** - End-user documentation
- **[Startup Guide](STARTUP_GUIDE.md)** - Production best practices
- **[Changelog](CHANGELOG.md)** - Version history

## 🆘 Getting Help

1. **Quick question?** Check this file's cheat sheet above
2. **Backend/pipeline issue?** → [.claude/backend.md](.claude/backend.md)
3. **UI/server issue?** → [.claude/frontend.md](.claude/frontend.md)
4. **Test issue?** → [.claude/testing.md](.claude/testing.md)
5. **Deployment issue?** → [.claude/deployment.md](.claude/deployment.md)
6. **Conceptual confusion?** → [lego.md](lego.md)

## 💡 Pro Tips

- Use `make help` to see all available commands
- Use `./start.sh help` for startup script options
- Check `make status` for comprehensive health check
- Read `lego.md` to understand the "factory" mental model
- Enable debug tracing only when needed: `make build-debug`
- Run `make check` before committing (lint + format + typecheck + test)

---

**Last Updated**: 2026-02-05
**Version**: 0.0.6
**Repository Type**: Multi-tenant data processing pipeline with FastAPI web UI
**Primary Purpose**: Transform DealMachine exports into Pete Properties Import-ready files
