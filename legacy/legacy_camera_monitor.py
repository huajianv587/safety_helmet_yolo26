import cv2
from ultralytics import YOLO

# 1. 加载模型
model_path = r"D:\软件\Pycharm\YOLOv8n_detecte\helmet_project/cpu_test/weights/best.pt"
model = YOLO(model_path)

# 【可选优化】针对你的 Intel CPU，导出为 OpenVINO 格式（仅需执行一次）
# 执行后会生成一个 best_openvino_model 文件夹，推理速度飞快
# model.export(format="openvino")
# model = YOLO(r"D:\Pycharm\YOLOv8n_detecte\helmet_project\cpu_test\weights\best_openvino_model")

cap = cv2.VideoCapture(0)

# 业务逻辑
no_helmet_counter = 0
alert_threshold = 90  # 降低一点阈值，反应更快

while cap.isOpened():
    success, frame = cap.read()
    if not success: break

    # 2. 预测 (imgsz 保持和训练时一致的 320，速度更快)
    results = model.predict(frame, imgsz=320, conf=0.5, device='cpu')[0]

    detected_person = False

    # 3. 解析结果
    # 截图显示：Class 0 是 hat，Class 1 是 person
    for box in results.boxes:
        cls = int(box.cls[0])
        conf = float(box.conf[0])
        x1, y1, x2, y2 = map(int, box.xyxy[0])

        if cls == 1:  # 检测到未戴安全帽的人 (person)
            detected_person = True
            color = (0, 0, 255) # 红色警告
            label = f"NO HELMET {conf:.2f}"
        else:
            color = (0, 255, 0) # 绿色安全
            label = f"HELMET {conf:.2f}"

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    # 4. 报警逻辑
    if detected_person:
        no_helmet_counter += 1
    else:
        no_helmet_counter = max(0, no_helmet_counter - 1)

    if no_helmet_counter >= alert_threshold:
        cv2.putText(frame, "!!! WARNING !!!", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)

    cv2.imshow("Safety Helmet Monitor", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()