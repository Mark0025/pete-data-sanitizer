# Senior-Level Startup Guide
## Pete DealMachine Cleaner - Production-Ready Application Startup

This guide explains the **professional, production-ready** ways to start and manage this application.

---

## 🎯 Quick Answer

**Best way to start everything:**

```bash
# First time only
make dev-setup

# Then start the app
make start
```

That's it! The application will:
- ✅ Start in Docker with health checks
- ✅ Run on http://localhost:8765
- ✅ Persist data in uploads/
- ✅ Auto-restart on failure
- ✅ Monitor health every 30s

---

## 📋 Table of Contents

1. [Development Workflow](#development-workflow)
2. [Production Deployment](#production-deployment)
3. [All Startup Methods](#all-startup-methods)
4. [Health Monitoring](#health-monitoring)
5. [Best Practices](#best-practices)

---

## 🔧 Development Workflow

### First-Time Setup

```bash
# Complete development setup (one command)
make dev-setup
```

This will:
1. Install UV dependencies (`uv sync`)
2. Create `config.yaml` from example
3. Create `.env` from example
4. Create necessary directories

### Daily Development

**Option 1: Docker (Recommended - Closest to Production)**
```bash
make start           # Start in background
make docker-logs     # View logs
make health          # Check health
make stop            # Stop when done
```

**Option 2: Native with Hot Reload (Fastest Iteration)**
```bash
./start.sh dev       # Bash script with error handling
# or
make dev             # Quick Makefile command
```

Hot reload means code changes apply immediately - no restart needed.

### Common Dev Commands

```bash
# Build pipeline (process DealMachine data)
make build                    # Standard build
make build-clean             # With randomized External IDs
make build-contacts-only     # Contacts-only mode

# Testing
make test                    # Run tests
make test-cov               # Tests with coverage
make lint                   # Check code quality
make format                 # Format code
make check                  # All checks at once

# Utilities
make logs                   # View latest run logs
make clean                  # Clean caches
make version                # Show app version
```

---

## 🚀 Production Deployment

### Method 1: Docker Compose (Recommended)

**Setup:**
```bash
# 1. Configure environment
cp .env.example .env
vim .env  # Edit ENVIRONMENT=production, LOG_LEVEL=WARNING, etc.

# 2. Build and start
make docker-build
make prod-up

# 3. Check health
make health
make status
```

**Management:**
```bash
make prod-logs      # View logs
make restart        # Restart
make stop           # Stop
```

### Method 2: Systemd Service (Linux Servers)

**Setup:**
```bash
# 1. Copy and configure service file
sudo cp pete-dm-clean.service /etc/systemd/system/
sudo vim /etc/systemd/system/pete-dm-clean.service  # Edit paths, user, etc.

# 2. Enable and start
sudo systemctl daemon-reload
sudo systemctl enable pete-dm-clean
sudo systemctl start pete-dm-clean

# 3. Verify
sudo systemctl status pete-dm-clean
curl http://localhost:8765/health
```

**Management:**
```bash
# View logs
sudo journalctl -u pete-dm-clean -f

# Restart
sudo systemctl restart pete-dm-clean

# Stop
sudo systemctl stop pete-dm-clean
```

### Method 3: Nginx Reverse Proxy (Optional)

For production with SSL/TLS and load balancing:

```bash
# 1. Configure nginx
sudo cp nginx.conf.example /etc/nginx/sites-available/pete-dm-clean
sudo vim /etc/nginx/sites-available/pete-dm-clean  # Edit server_name, etc.

# 2. Enable site
sudo ln -s /etc/nginx/sites-available/pete-dm-clean /etc/nginx/sites-enabled/

# 3. Test and reload
sudo nginx -t
sudo systemctl reload nginx

# 4. Optional: SSL with Let's Encrypt
sudo certbot --nginx -d pete.yourdomain.com
```

---

## 🔀 All Startup Methods

### 1. Startup Script (./start.sh)

**Features:**
- ✅ Dependency checking (UV, Python, Docker)
- ✅ Environment setup
- ✅ Health check verification
- ✅ Graceful shutdown
- ✅ Color-coded logging

**Usage:**
```bash
./start.sh dev          # Development (hot reload)
./start.sh prod         # Production (multi-worker)
./start.sh docker       # Docker (detached)
./start.sh docker-dev   # Docker (foreground with logs)
./start.sh help         # Show help
```

**When to use:** First time setup, automated deployments, when you want robust error handling.

### 2. Makefile

**Features:**
- ✅ ~40 pre-defined commands
- ✅ Color-coded output
- ✅ Grouped by purpose
- ✅ Tab completion-friendly

**Usage:**
```bash
make help               # Show all commands
make start              # Quick start (Docker)
make dev                # Development mode
make test               # Run tests
make clean              # Clean artifacts
```

**When to use:** Daily development, CI/CD, when you want speed.

### 3. Docker Compose

**Features:**
- ✅ Container isolation
- ✅ Automatic health checks
- ✅ Volume persistence
- ✅ Environment management
- ✅ Network isolation

**Usage:**
```bash
docker-compose up -d            # Start
docker-compose logs -f          # View logs
docker-compose ps               # Status
docker-compose down             # Stop
docker-compose restart          # Restart
```

**When to use:** Production, when you want consistency across environments.

### 4. Direct Commands

**Features:**
- ✅ Maximum control
- ✅ CI/CD friendly
- ✅ No abstraction layer

**Usage:**
```bash
# Development
uv run uvicorn pete_dm_clean.server:app --reload

# Production
uv run uvicorn pete_dm_clean.server:app --host 0.0.0.0 --port 8765 --workers 4
```

**When to use:** CI/CD pipelines, debugging, custom configurations.

### 5. Systemd Service

**Features:**
- ✅ Boot-time startup
- ✅ Auto-restart on failure
- ✅ Resource limits
- ✅ Security hardening
- ✅ Systemd logging integration

**When to use:** Production Linux servers, when you want OS-level process management.

### 6. Nginx Reverse Proxy

**Features:**
- ✅ SSL/TLS termination
- ✅ Load balancing
- ✅ Static file serving
- ✅ Rate limiting
- ✅ Security headers

**When to use:** Production with HTTPS, high-traffic scenarios, when you need a reverse proxy.

---

## 🏥 Health Monitoring

### Health Endpoints

**Simple check:**
```bash
curl http://localhost:8765/healthz
# Returns: ok
```

**Detailed check:**
```bash
curl http://localhost:8765/health | jq
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-01-20T12:34:56Z",
  "version": "0.0.6",
  "python_version": "3.12.0",
  "uploads_dir": "uploads",
  "checks": {
    "directories": {
      "status": "ok",
      "missing": null
    },
    "latest_run": {
      "run_id": "2026-01-20_12-30-00",
      "exists": true
    }
  }
}
```

### Automated Health Checks

**Docker Compose:**
- Checks `/health` every 30s
- 3 retries before marking unhealthy
- 40s startup grace period

**Check health:**
```bash
make health         # Manual curl check
make status         # Docker + HTTP status
docker-compose ps   # Shows health column
```

### Monitoring Integration

The `/health` endpoint returns:
- **200** if healthy
- **503** if unhealthy (missing dirs, errors)

Perfect for:
- Kubernetes liveness/readiness probes
- Load balancer health checks
- Uptime monitoring services
- CI/CD smoke tests

---

## 🎓 Best Practices

### Development

1. **Use hot reload** for fast iteration: `./start.sh dev` or `make dev`
2. **Check health after changes** to catch errors early: `make health`
3. **Run tests before committing**: `make check` (lint, format, typecheck, test)
4. **Use Docker occasionally** to catch environment-specific issues: `make start`
5. **Check logs for warnings**: `make logs` or `docker-compose logs -f`

### Production

1. **Use Docker Compose** for consistency: `make prod-up`
2. **Set resource limits** in docker-compose.yml or systemd service
3. **Enable health checks** for automatic recovery
4. **Use environment variables** for secrets (never commit .env)
5. **Set up monitoring** using `/health` endpoint
6. **Use Nginx** for SSL/TLS and load balancing
7. **Enable logging** to disk or external service
8. **Test deployments** in staging first
9. **Use systemd** for OS-level process management
10. **Implement backups** for uploads/ directory

### Security

1. **Never commit .env** (already in .gitignore)
2. **Use strong passwords** for database
3. **Enable HTTPS** in production
4. **Set up firewall** rules
5. **Run as non-root** user (systemd service template included)
6. **Enable security headers** (nginx config template included)
7. **Keep dependencies updated**: `uv sync`

### Scaling

1. **Increase workers** in production: `--workers 4` (adjust per CPU cores)
2. **Use external database** (PostgreSQL) for metadata: Set `DB_URL` in .env
3. **Add load balancing** via Nginx for multiple instances
4. **Mount shared storage** for uploads/ if running multiple containers
5. **Use Redis** for session storage (if needed in future)
6. **Monitor resource usage**: `docker stats` or systemd cgroups

---

## 🔍 Comparison Matrix

| Method | Dev Speed | Production Ready | Complexity | Isolation | Health Checks |
|--------|-----------|------------------|------------|-----------|---------------|
| `./start.sh dev` | ⚡⚡⚡ Fast | ✅ Yes | 🟢 Low | ⚠️ No | ✅ Yes |
| `make dev` | ⚡⚡⚡ Fast | ✅ Yes | 🟢 Low | ⚠️ No | ✅ Yes |
| `make start` (Docker) | ⚡⚡ Medium | ✅✅ Excellent | 🟢 Low | ✅✅ Full | ✅✅ Auto |
| Direct commands | ⚡⚡⚡ Fast | ✅ Yes | 🟡 Medium | ⚠️ No | ⚠️ Manual |
| Systemd service | ⚡ Slow | ✅✅ Excellent | 🔴 High | ⚠️ No | ✅✅ Auto |
| Nginx + systemd | ⚡ Slow | ✅✅✅ Best | 🔴 High | ⚠️ No | ✅✅ Auto |

**Recommendations:**
- **Development:** `./start.sh dev` or `make dev`
- **Production (simple):** `make start` (Docker)
- **Production (advanced):** Systemd + Nginx
- **CI/CD:** Direct commands or Docker

---

## 🆘 Troubleshooting

### Application Won't Start

**Check dependencies:**
```bash
./start.sh dev  # Will check and report missing dependencies
```

**Check port availability:**
```bash
lsof -i :8765
kill -9 <PID>  # If port is occupied
```

**Check Docker:**
```bash
docker info  # Is Docker running?
make docker-rebuild  # Rebuild from scratch
```

### Health Check Failing

**Check application logs:**
```bash
make docker-logs  # Docker
sudo journalctl -u pete-dm-clean -f  # Systemd
```

**Check critical directories:**
```bash
ls -la uploads/{runs,flowcharts,templates}
```

**Manual health check:**
```bash
curl -v http://localhost:8765/health
```

### Slow Startup

**Increase health check start period:**

Edit `docker-compose.yml`:
```yaml
healthcheck:
  start_period: 60s  # Increase from 40s
```

### Permission Errors

**Fix uploads directory permissions:**
```bash
sudo chown -R $(whoami):$(whoami) uploads/
chmod -R 755 uploads/
```

**Fix Docker permissions:**
```bash
sudo usermod -aG docker $USER
# Then log out and back in
```

---

## 📚 Additional Resources

- **CLAUDE.md**: Complete technical documentation
- **README.md**: User guide and feature overview
- **lego.md**: Conceptual "factory" guide for understanding the pipeline
- **CHANGELOG.md**: Version history
- **Makefile**: Run `make help` to see all commands
- **./start.sh help**: Script usage guide

---

## 🎉 Summary

**For the senior-level best practice:**

```bash
# Development
./start.sh dev                    # Robust script with checks
make dev                          # Quick Makefile command

# Production
make prod-up                      # Docker production mode
# or
systemd + nginx                   # Full production stack
```

All methods include:
- ✅ Health checks
- ✅ Graceful shutdown
- ✅ Logging
- ✅ Environment management
- ✅ Error handling

The choice depends on your deployment environment and operational requirements.

---

**Last Updated:** 2026-01-20
**Version:** 0.0.6
