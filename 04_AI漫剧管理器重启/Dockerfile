FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    MANGA_DATA_DIR=/app/data

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir -e .

COPY config.toml ./
COPY docs ./docs

EXPOSE 8000

CMD ["uvicorn", "manga_manager.api:app", "--host", "0.0.0.0", "--port", "8000"]
