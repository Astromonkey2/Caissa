FROM python:3.11-slim

# Install stockfish (used for chess move analysis)
RUN apt-get update && apt-get install -y stockfish && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

ENV STOCKFISH_PATH=/usr/bin/stockfish
ENV ANALYSIS_DEPTH=8

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
