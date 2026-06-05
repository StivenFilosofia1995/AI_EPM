FROM python:3.11-slim

WORKDIR /app

# bust stale Railway BuildKit cache
ARG CACHEBUST=2

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app/ ./app/
COPY backend/static/ ./static/

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
