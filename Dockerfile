# Builder stage
FROM python:3.11-slim as builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies required for building
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libmariadb-dev-compat \
    libmariadb-dev \
    pkg-config \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt && \
    pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels gunicorn

# Final stage
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=run.py

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    netcat-openbsd \
    libmariadb3 \
    dos2unix \
    logrotate \
    mariadb-client \
    && (apt-get install -y libmagic1 || apt-get install -y libmagic1t64) \
    && rm -rf /var/lib/apt/lists/*

# Copy wheels from builder
COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .

# Install dependencies from wheels
RUN pip install --no-cache /wheels/*

# Copy project
COPY . .

# Build documentation
# We run mkdocs build to create the static 'site' directory
RUN mkdocs build

# Make entrypoint executable
COPY docker-entrypoint.sh /usr/local/bin/
RUN dos2unix /usr/local/bin/docker-entrypoint.sh && chmod +x /usr/local/bin/docker-entrypoint.sh

# Create a non-root user and switch to it
RUN useradd -m appuser && \
    mkdir -p /app/instance && \
    chown -R appuser:appuser /app /app/instance
USER appuser

# Expose the port
EXPOSE 5000

# Perform Migrations
ENV RUN_MIGRATIONS=true

# Set entrypoint
ENTRYPOINT ["docker-entrypoint.sh"]

# Default command
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "3", "run:app"]
