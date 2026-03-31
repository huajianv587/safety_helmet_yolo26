from ultralytics import YOLO
import os

def yaml_build():
    # 注意：path 必须指向你刚才转换后的 D:/YOLO_Helmet_Data
    yaml_content = """
    path: D:/YOLO_Helmet_Data
    train: images/train
    val: images/val
    names:
      0: hat
      1: person
    """
    with open("shwd_data.yaml", "w", encoding="utf-8") as f:
        f.write(yaml_content.strip().replace("    ", ""))
    print("shwd_data.yaml 已指向转换后的数据集！")

def train_my_model():
    model = YOLO("yolov8n.pt")
    # CPU 训练非常慢，我们只跑 1 轮
    model.train(
        data="shwd_data.yaml",
        epochs=10,
        imgsz=320,      # 减小图片尺寸可以大幅提升 CPU 训练速度
        device='cpu',
        batch=8,
        project="helmet_project",
        name="cpu_test"
    )
    return "helmet_project/cpu_test/weights/best.pt"

def main():
    yaml_build()
    best_pt = train_my_model()
    print(f"训练完成，模型位置: {best_pt}")

if __name__ == "__main__":
    main()