安全帽智能监测系统 - 部署手册 (v1.0)
1. 系统简介 本系统采用轻量化 YOLOv8 算法，支持实时监控画面中的安全帽佩戴情况。系统已通过 Docker 容器化封装，支持在各种 X86 架构的工控机（如 Ubuntu/Debian 系统）上快速迁移。

2. 快速部署 (三步走)

导入镜像：将 helmet_system_v1.tar 拷贝到工控机，运行命令： docker load -i helmet_system_v1.tar

启动容器： docker run -d --name helmet_monitor -p 8501:8501 --device=/dev/video0:/dev/video0 my_helmet_app:latest

访问系统：在局域网内任意电脑浏览器打开：http://[工控机IP]:8501

3. 常见问题 (FAQ)

画面延迟：若工控机性能较低，可将 Web 界面左侧的“置信度阈值”调高。

摄像头无法开启：请确认物理摄像头已连接至工控机的第一个 USB 端口（对应 /dev/video0）。