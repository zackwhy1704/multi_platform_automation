FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Railway sets PORT env var; fall back to 8000 for local
CMD ["sh", "-c", "uvicorn gateway.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
