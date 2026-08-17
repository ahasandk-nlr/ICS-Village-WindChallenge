FROM python:3.9-slim
WORKDIR /app
# Without this, Python fully buffers stdout when it isn't a TTY (true
# inside a container), so this script's print() calls may not show up in
# `docker logs` in any reasonable timeframe.
ENV PYTHONUNBUFFERED=1

# gcc + python3-dev are needed to build RPi.GPIO's C extension. It builds
# fine on any Linux/architecture - it only raises RuntimeError at import
# time on non-Pi hardware, which MQTTHelper.py already catches and falls
# back to a mock for.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY ./mqtt-certs ./mqtt-certs
COPY ./MQTTHelper.py ./MQTTHelper.py

CMD ["python3", "MQTTHelper.py"]
