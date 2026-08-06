# slave/Dockerfile
FROM python:3.9-slim
WORKDIR /app
# Without this, Python fully buffers stdout when it isn't a TTY (true
# inside a container), so slave.py's print() calls (shutdown_coil(), etc.)
# may not show up in `docker logs` in any reasonable timeframe.
ENV PYTHONUNBUFFERED=1

# gcc + python3-dev are needed to build RPi.GPIO's C extension. It builds
# fine on any Linux/architecture (confirmed on x86_64 here) - it only
# raises RuntimeError at import time on non-Pi hardware, which slave.py
# already catches and falls back to a mock for.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY slave.py helper.py ./
# Preserve the mqtt-certs/ subdirectory - `COPY mqtt-certs .` (the
# previous version of this line) copies that directory's *contents*
# directly into /app instead, which silently broke slave.py's
# mqtt-certs/ca.pem path.
COPY mqtt-certs ./mqtt-certs

CMD ["python3", "slave.py"]
