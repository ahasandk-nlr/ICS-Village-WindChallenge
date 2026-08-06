# master/Dockerfile
FROM python:3
WORKDIR /app
# Without this, Python fully buffers stdout when it isn't a TTY (true
# inside a container), so master.py's print() calls never show up in
# `docker logs` until the buffer fills - which in practice can mean never.
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY master.py .
CMD ["python3", "master.py"]
