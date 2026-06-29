FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["uvicorn", "app.mcp_server.http_app:app", "--host", "0.0.0.0", "--port", "8080"]
