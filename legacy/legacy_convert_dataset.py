import os
import xml.etree.ElementTree as ET
import shutil
from sklearn.model_selection import train_test_split

# --- 路径配置 (根据你的截图) ---
root_path = "C:/Users/Jhj/.cache/kagglehub/datasets/zxy000/shwd-dataset/versions/1/VOC2028"
img_dir = os.path.join(root_path, "JPEGImages")
xml_dir = os.path.join(root_path, "Annotations")
output_path = "D:/YOLO_Helmet_Data" # 转换后的数据存放地

classes = ["hat", "person"]

def convert(size, box):
    dw, dh = 1. / size[0], 1. / size[1]
    return ((box[0] + box[1]) / 2.0 * dw, (box[2] + box[3]) / 2.0 * dh,
            (box[1] - box[0]) * dw, (box[3] - box[2]) * dh)

def convert_annotation(xml_file, output_txt):
    tree = ET.parse(xml_file)
    root = tree.getroot()
    size = root.find('size')
    w, h = int(size.find('width').text), int(size.find('height').text)
    with open(output_txt, 'w') as f:
        for obj in root.iter('object'):
            cls = obj.find('name').text
            if cls not in classes: continue
            xmlbox = obj.find('bndbox')
            b = (float(xmlbox.find('xmin').text), float(xmlbox.find('xmax').text),
                 float(xmlbox.find('ymin').text), float(xmlbox.find('ymax').text))
            f.write(f"{classes.index(cls)} {' '.join([f'{a:.6f}' for a in convert((w, h), b)])}\n")

# 创建目录
for p in ["images/train", "images/val", "labels/train", "labels/val"]:
    os.makedirs(os.path.join(output_path, p), exist_ok=True)

image_files = [f for f in os.listdir(img_dir) if f.endswith('.jpg')]
# 为节省 CPU 训练时间，我们只取前 200 张图片演示
image_files = image_files[:200]
train_files, val_files = train_test_split(image_files, test_size=0.2, random_state=42)

def process_files(files, split):
    for f in files:
        shutil.copy(os.path.join(img_dir, f), os.path.join(output_path, f"images/{split}/{f}"))
        xml_file = os.path.join(xml_dir, f.replace('.jpg', '.xml'))
        if os.path.exists(xml_file):
            convert_annotation(xml_file, os.path.join(output_path, f"labels/{split}/{f.replace('.jpg', '.txt')}"))

process_files(train_files, "train")
process_files(val_files, "val")
print(f"数据转换完成！路径: {output_path}")