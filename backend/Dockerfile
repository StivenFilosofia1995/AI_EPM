FROM python:3.11-slim

# No escribir .pyc y no almacenar la salida en búfer: los registros de Railway
# aparecen en el momento, no en bloques.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Las dependencias van en su propia capa: solo se reinstalan cuando cambia
# requirements.txt, no en cada cambio de código.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Se copia el contexto completo en lugar de directorio por directorio.
# Con COPY app/ ./app/ y COPY static/ ./static/, si un directorio no llegaba al
# contexto el build fallaba con "failed to compute cache key: not found", que
# es un mensaje que no dice cuál es el problema real. Lo que NO debe entrar a
# la imagen está declarado en backend/.dockerignore.
COPY . .

EXPOSE 8000

# Railway inyecta PORT. En local se usa 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
