FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY museo/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY museo/ ./museo/
COPY fichas.json ./fichas.json
COPY guia-spec.md ./guia-spec.md

EXPOSE 8080

CMD ["uvicorn", "museo.app:app", "--host", "0.0.0.0", "--port", "8080"]
