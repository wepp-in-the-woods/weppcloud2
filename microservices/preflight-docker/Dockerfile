FROM python:3.8-slim

WORKDIR /app

COPY requirements.txt .

RUN apt-get update && apt-get install -y curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install -r requirements.txt

COPY preflight_server.py .

CMD ["python", "preflight_server.py"]
