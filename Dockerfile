FROM python:3.11-slim

# Install stockfish — binary lands at /usr/games/stockfish on Debian
RUN apt-get update && apt-get install -y stockfish && \
    ln -sf "$(find /usr -name stockfish -type f 2>/dev/null | head -1)" /usr/local/bin/stockfish && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

# /usr/local/bin is guaranteed in PATH; symlink above points there
ENV STOCKFISH_PATH=/usr/local/bin/stockfish
ENV ANALYSIS_DEPTH=8
ENV CREWAI_DISABLE_TELEMETRY=true

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
