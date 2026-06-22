FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy uv binary from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency definition files
COPY pyproject.toml uv.lock ./

# Sync dependencies into the virtual environment
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy the rest of the application
COPY . .

# Place the virtual environment on the PATH so python and installed tools (uvicorn, celery) run from it
ENV PATH="/app/.venv/bin:$PATH"

# Expose FastAPI's standard port
EXPOSE 8000

# Command to run FastAPI server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
