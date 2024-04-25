FROM python:3.8-slim

WORKDIR /app

COPY requirements.txt .

RUN apt-get update && apt-get install -y curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install -r requirements.txt

COPY status_server.py .

CMD ["python", "status_server.py"]
