FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY studio_one ./studio_one
COPY README.md ./README.md

RUN useradd --create-home --shell /usr/sbin/nologin studio_one
USER studio_one

EXPOSE 8080

CMD ["sh", "-c", "uvicorn studio_one.web.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
