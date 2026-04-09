FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV YOLO_CONFIG_DIR=/app/.ultralytics
ENV PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
ENV STREAMLIT_SERVER_HEADLESS=true
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements.identity.txt ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt -r requirements.identity.txt
COPY . .
EXPOSE 8501
EXPOSE 8765
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
