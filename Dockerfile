FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install UV package manager
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Set working directory
WORKDIR /app

# Copy dependency files (README.md needed by hatchling build backend)
COPY pyproject.toml uv.lock README.md ./
COPY .python-version ./

# Install Python dependencies
RUN uv sync --frozen

# Copy application code
COPY . .

# Create uploads directory
RUN mkdir -p uploads/runs uploads/flowcharts uploads/templates uploads/companies

# Expose port
EXPOSE 8765

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8765/health || exit 1

# Default command (can be overridden in docker-compose)
CMD ["uv", "run", "uvicorn", "pete_dm_clean.server:app", "--host", "0.0.0.0", "--port", "8765"]
