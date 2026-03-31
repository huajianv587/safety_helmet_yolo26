import streamlit as st
import cv2
from ultralytics import YOLO
import numpy as np

# 1. 页面配置
st.set_page_config(page_title="安全帽智能检测系统", layout="wide")
st.title("👷 安全帽佩戴实时监测系统")

# 2. 加载模型 (建议使用相对路径)
MODEL_PATH = "helmet_project/cpu_test/weights/best.pt"
model = YOLO(MODEL_PATH)

# 3. 侧边栏配置
st.sidebar.header("检测设置")
conf_threshold = st.sidebar.slider("置信度阈值", 0.0, 1.0, 0.5)

# 4. 视频流处理
run_button = st.button("开启摄像头检测")
stop_button = st.button("停止")
FRAME_WINDOW = st.image([])  # 预留显示窗口

camera = cv2.VideoCapture(0)

if run_button:
    while True:
        ret, frame = camera.read()
        if not ret:
            st.error("无法获取摄像头画面")
            break

        # 模型推理
        results = model.predict(frame, conf=conf_threshold, device='cpu', imgsz=320)[0]

        # 绘制结果
        for box in results.boxes:
            cls = int(box.cls[0])
            label = "HELMET" if cls == 0 else "NO HELMET"
            color = (0, 255, 0) if cls == 0 else (0, 0, 255)

            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        # 转换 BGR 为 RGB 供 Streamlit 显示
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        FRAME_WINDOW.image(frame_rgb)

        if stop_button:
            break

camera.release()