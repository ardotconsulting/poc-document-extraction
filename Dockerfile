FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY app.py .
COPY samples/ samples/

EXPOSE 8000

CMD ["python3", "app.py"]
