import cv2
import numpy as np
import socket

# 绑定本地端口，必须和眼镜端代码里设置的端口保持一致 (9999)
UDP_IP = "0.0.0.0"  # 监听所有网卡
UDP_PORT = 9999

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# 扩大接收缓冲区，防止高帧率下丢包
sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536 * 4)
sock.bind((UDP_IP, UDP_PORT))

print(f"[*] 正在监听端口 {UDP_PORT}，等待眼镜端画面中...")

try:
  while True:
    # 接收 UDP 数据包（单次最大接收 65535 字节）
    data, addr = sock.recvfrom(65535)

    if not data:
      continue

    # 将收到的字节流转换为 NumPy 数组
    nparr = np.frombuffer(data, np.uint8)

    # 用 OpenCV 将 JPEG 字节流解码为图像矩阵
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if img is not None:
      # 实时显示画面
      cv2.imshow("RayNeo Live Stream", img)

    # 按下键盘上的 'q' 键可以随时退出预览窗口
    if cv2.waitKey(1) & 0xFF == ord("q"):
      break

except Exception as e:
  print(f"[!] 发生错误: {e}")

finally:
  sock.close()
  cv2.destroyAllWindows()
  print("[*] 接收端已安全关闭")