FROM python:3.12-slim

# Install system dependencies including rsync
RUN apt-get update && \
    apt-get install -y --no-install-recommends rsync ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Ensure data directory exists
RUN mkdir -p /app/data

EXPOSE 6060

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "synctohdd.main", "server", "--host", "0.0.0.0", "--port", "6060"]
