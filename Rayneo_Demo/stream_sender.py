import socket
import json
import struct

class GomokuServerSender:
    def __init__(self, host="0.0.0.0", port=9988):
        self.host = host
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(1)
        self.client_connection = None
        print(f"[*] Gomoku 指令服务端已启动，等待眼镜端连接端口 {self.port}...")

    def accept_client(self):
        """阻塞等待眼镜端连入（或者可以改写为非阻塞多线程）"""
        conn, addr = self.server_socket.accept()
        self.client_connection = conn
        print(f"[*] 智能眼镜已连入指令通道: {addr}")

    def send_game_state(self, board_state, next_move):
        """
        将棋盘二维数组和 AI 推荐落子点打包成 JSON 并通过 TCP 发送给眼镜
        """
        if not self.client_connection:
            return False

        # 1. 构造要发送的数据字典
        data = {
            "status": "success",
            "ai_move": {
                "row": int(next_move[0]) if next_move else -1,
                "col": int(next_move[1]) if next_move else -1
            },
            # 将 numpy 数组转成标准的 Python 嵌套列表
            "board_matrix": board_state.tolist() 
        }

        try:
            # 2. 序列化为 JSON 字符串，并转成 utf-8 字节
            json_str = json.dumps(data)
            json_bytes = json_str.encode('utf-8')
            
            # 3. 仿照你的图传协议：先发 4 个字节的长度标头，再发具体内容（防止粘包）
            length_header = struct.pack("!I", len(json_bytes))
            
            self.client_connection.sendall(length_header + json_bytes)
            return True
        except (socket.error, BrokenPipeError):
            print("[!] 眼镜端断开连接...")
            self.client_connection = None
            return False

    def close(self):
        if self.client_connection:
            self.client_connection.close()
        self.server_socket.close()