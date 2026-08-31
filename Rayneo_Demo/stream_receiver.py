import socket
import struct
import threading
import cv2
import numpy as np
from queue import Empty, Full, Queue
import time

class StreamReceiver:
    def __init__(self, ip="0.0.0.0", port=9999, max_frame_size=8 * 1024 * 1024):
        self.ip = ip
        self.port = port
        self.max_frame_size = max_frame_size
        
        # 💡 核心改动 1：把队列最大长度设为 1，追求极致的“只要最新”
        self.frame_queue = Queue(maxsize=1)
        self.stop_event = threading.Event()
        self.open_sockets = []
        self.open_sockets_lock = threading.Lock()
        self.threads = []

    def start(self):
        """启动 UDP 和 TCP 接收线程"""
        self.threads = [
            threading.Thread(target=self._receive_udp, daemon=True),
            threading.Thread(target=self._receive_tcp, daemon=True)
        ]
        for t in self.threads:
            t.start()
        print(f"[*] Receiver 正在监听 {self.ip}:{self.port} (UDP/TCP)")

    def stop(self):
        """安全关闭所有连接和线程"""
        self.stop_event.set()
        self._close_open_sockets()
        print("[*] Receiver 已安全关闭")

    def get_frame(self, timeout=0.1):
        """获取最新一帧解码后的图像。附带延迟探针输出"""
        try:
            # 1. 从队列拿到数据，并获取该帧到达 PC 的时间戳
            protocol, data, t_arrival = self.frame_queue.get(timeout=timeout)
            
            t_decode_start = time.time() * 1000
            nparr = np.frombuffer(data, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            t_decode_end = time.time() * 1000
            
            # 计算并打印 PC 端基础耗时
            queue_wait_cost = t_decode_start - t_arrival
            decode_cost = t_decode_end - t_decode_start
            
            print(f"👉 [PC底层] 队列积压等待: {queue_wait_cost:.1f}ms | JPEG解码: {decode_cost:.1f}ms")
            
            return image
        except Empty:
            return None

    # ================= 内部私有方法 =================

    def _register_socket(self, sock):
        with self.open_sockets_lock:
            self.open_sockets.append(sock)

    def _close_open_sockets(self):
        with self.open_sockets_lock:
            sockets = list(self.open_sockets)
        for sock in sockets:
            try:
                sock.close()
            except OSError:
                pass

    def _enqueue_frame(self, protocol, data, t_arrival):
        """极致策略：永远只要最新的一帧，队列满时强行丢弃旧帧"""
        try:
            # 尝试直接放入
            self.frame_queue.put_nowait((protocol, data, t_arrival))
        except Full:
            try:
                # 如果队列满了，立刻把里面积压的旧帧强行拿出来扔掉
                self.frame_queue.get_nowait()
            except Empty:
                pass
            # 再次尝试把最新的一帧放进去
            try:
                self.frame_queue.put_nowait((protocol, data, t_arrival))
            except Full:
                pass

    def _receive_exact(self, connection, size):
        data = bytearray()
        while len(data) < size and not self.stop_event.is_set():
            try:
                chunk = connection.recv(size - len(data))
            except socket.timeout:
                continue
            except OSError:
                return None
            if not chunk:
                return None
            data.extend(chunk)
        return bytes(data) if len(data) == size else None

    def _receive_udp(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536 * 4)
        sock.settimeout(0.5)
        try:
            sock.bind((self.ip, self.port))
            self._register_socket(sock)
            while not self.stop_event.is_set():
                try:
                    data, _ = sock.recvfrom(65535)
                    if data:
                        self._enqueue_frame("UDP", data)
                except socket.timeout:
                    continue
                except OSError:
                    break
        finally:
            sock.close()

    def _receive_tcp(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.settimeout(0.5)
        try:
            server_socket.bind((self.ip, self.port))
            server_socket.listen(1)
            self._register_socket(server_socket)
            while not self.stop_event.is_set():
                try:
                    # 这里就是刚才不小心被省略号替换掉的关键代码
                    connection, address = server_socket.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                
                print(f"[*] TCP 客户端已连接: {address}")
                with connection:
                    connection.settimeout(0.5)
                    while not self.stop_event.is_set():
                        length_data = self._receive_exact(connection, 4)
                        if length_data is None: break
                        frame_length = struct.unpack("!I", length_data)[0]
                        if frame_length <= 0 or frame_length > self.max_frame_size: break
                        
                        data = self._receive_exact(connection, frame_length)
                        if data is None: break
                        
                        # 【核心探针】：记录完整一帧数据到达 PC 内存的确切时间
                        t_arrival = time.time() * 1000 
                        self._enqueue_frame("TCP", data, t_arrival)
                        
                print("[*] TCP 客户端已断开，等待重连...")
        finally:
            server_socket.close()