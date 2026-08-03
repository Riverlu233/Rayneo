import cv2
import numpy as np
import socket
import struct
import threading
from queue import Empty, Full, Queue


UDP_IP = "0.0.0.0"
TRANSFER_PORT = 9999
MAX_FRAME_SIZE = 8 * 1024 * 1024

frame_queue = Queue(maxsize=2)
stop_event = threading.Event()
open_sockets = []
open_sockets_lock = threading.Lock()


def register_socket(sock):
    """Register a socket so the main thread can close it during shutdown."""
    with open_sockets_lock:
        open_sockets.append(sock)


def close_open_sockets():
    """Close all registered sockets and unblock receiver threads."""
    with open_sockets_lock:
        sockets = list(open_sockets)
    for sock in sockets:
        try:
            sock.close()
        except OSError:
            pass


def enqueue_frame(protocol, data):
    """Queue a JPEG frame and drop the oldest frame when the queue is full."""
    try:
        frame_queue.put_nowait((protocol, data))
    except Full:
        try:
            frame_queue.get_nowait()
        except Empty:
            pass
        frame_queue.put_nowait((protocol, data))


def receive_exact(connection, size):
    """Read exactly size bytes from a TCP connection or return None on disconnect."""
    data = bytearray()
    while len(data) < size and not stop_event.is_set():
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


def receive_udp():
    """Receive complete JPEG datagrams from the Android UDP sender."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536 * 4)
    sock.settimeout(0.5)
    try:
        sock.bind((UDP_IP, TRANSFER_PORT))
        register_socket(sock)
        print(f"[*] UDP 正在监听端口 {TRANSFER_PORT}")
        while not stop_event.is_set():
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            if data:
                enqueue_frame("UDP", data)
    except OSError as exception:
        print(f"[!] UDP 接收端启动失败: {exception}")
    finally:
        sock.close()


def receive_tcp():
    """Accept TCP clients and receive length-prefixed JPEG frames."""
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.settimeout(0.5)
    try:
        server_socket.bind((UDP_IP, TRANSFER_PORT))
        server_socket.listen(1)
        register_socket(server_socket)
        print(f"[*] TCP 正在监听端口 {TRANSFER_PORT}")
        while not stop_event.is_set():
            try:
                connection, address = server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            print(f"[*] TCP 客户端已连接: {address}")
            with connection:
                connection.settimeout(0.5)
                while not stop_event.is_set():
                    length_data = receive_exact(connection, 4)
                    if length_data is None:
                        break

                    frame_length = struct.unpack("!I", length_data)[0]
                    if frame_length <= 0 or frame_length > MAX_FRAME_SIZE:
                        print(f"[!] TCP 图片长度无效: {frame_length}")
                        break

                    data = receive_exact(connection, frame_length)
                    if data is None:
                        break
                    enqueue_frame("TCP", data)

            print("[*] TCP 客户端已断开，等待重新连接...")
    except OSError as exception:
        print(f"[!] TCP 接收端启动失败: {exception}")
    finally:
        server_socket.close()


def display_frames():
    """Decode queued JPEG frames and display them in the OpenCV window."""
    window_title = "RayNeo Live Stream"
    while not stop_event.is_set():
        try:
            protocol, data = frame_queue.get(timeout=0.1)
        except Empty:
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                stop_event.set()
            continue

        nparr = np.frombuffer(data, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if image is not None:
            cv2.imshow(window_title, image)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            stop_event.set()


def main():
    """Start UDP and TCP receivers, then display incoming color frames."""
    receiver_threads = [
        threading.Thread(target=receive_udp, daemon=True),
        threading.Thread(target=receive_tcp, daemon=True),
    ]
    for receiver_thread in receiver_threads:
        receiver_thread.start()

    print("[*] 同时支持 UDP/TCP，按 q 退出")
    try:
        display_frames()
    finally:
        stop_event.set()
        close_open_sockets()
        cv2.destroyAllWindows()
        print("[*] 接收端已安全关闭")


if __name__ == "__main__":
    main()
