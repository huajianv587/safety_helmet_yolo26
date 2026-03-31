FROM python:3.10-slim
WORKDIR /app
RUN apt-get update && apt-get install -y ffmpeg libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
COPY . .
ENV PYTHONPATH=/app/src
EXPOSE 8501
CMD streamlit run app.py --server.port=8501 --server.address=0.0.0.0
