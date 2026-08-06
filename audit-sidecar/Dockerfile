FROM python:3.12-slim
WORKDIR /app

# tcpdump pulls in libpcap, which scapy uses for packet capture.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tcpdump \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sidecar.py challenges.py ./

EXPOSE 8000
CMD ["python3", "sidecar.py"]
