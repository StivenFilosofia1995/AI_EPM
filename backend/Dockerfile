# El contexto de build es la RAÍZ del repositorio, no backend/.
#
# Por eso todas las rutas de COPY llevan el prefijo `backend/`. Railway no
# aplica el `buildContext` de railway.toml en su builder, así que se eliminó
# esa opción y el contexto quedó explícitamente en la raíz. docker-compose.yml
# usa el mismo contexto, para que local y despliegue se comporten igual.
#
# Si algún día se cambia el contexto a backend/, hay que quitar el prefijo de
# todas las líneas COPY y mover .dockerignore a backend/.

FROM python:3.11-slim

# Sin .pyc y sin búfer: los registros de Railway aparecen en el momento.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Las dependencias van en su propia capa: solo se reinstalan cuando cambia
# requirements.txt, no en cada cambio de código.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Se copia todo backend/ de una vez. Copiar directorio por directorio hacía
# que la ausencia de uno fallara con "failed to compute cache key: not found",
# un mensaje que no dice cuál es el problema real. Lo que no debe entrar a la
# imagen está declarado en el .dockerignore de la raíz.
COPY backend/ .

EXPOSE 8000

# Railway inyecta PORT. En local se usa 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
