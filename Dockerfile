# Dockerfile raiz: lo usa el boton "Run on Google Cloud" (deploy.cloud.run),
# que construye desde la raiz del repo. Equivale a app/Dockerfile.
FROM python:3.12-slim
WORKDIR /srv
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
