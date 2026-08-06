FROM python:3.13-rc
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY vizhelper.py .
COPY mqtt-certs ./mqtt-certs
CMD ["python3", "vizhelper.py"]
