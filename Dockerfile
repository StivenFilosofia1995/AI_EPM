FROM python:3.11-slim

# Security: run as non-root
RUN useradd --no-log-init -m -u 1000 appuser

WORKDIR /app

# Install dependencies first (layer caching)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/app/ ./app/
COPY backend/static/ ./static/

# Switch to non-root user
USER appuser

EXPOSE 8000

# $PORT is injected by Railway; default to 8000 locally
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
