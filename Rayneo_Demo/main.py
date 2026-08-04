import cv2
import numpy as np
from stream_receiver import StreamReceiver
from gomoku_agent import GomokuAgent
from stream_sender import GomokuServerSender  # 引入刚才编写的 TCP 发送模块

def main():
    # 1. 初始化接收器、AI Agent 和 TCP 指令服务端
    receiver = StreamReceiver(port=9999)
    agent = GomokuAgent(board_size=15)
    sender = GomokuServerSender(port=9988) # 眼镜端将连接此端口接收 JSON
    
    # 2. 启动后台视频接收线程
    receiver.start()
    
    # 3. 等待智能眼镜端连入指令通道
    print("[*] 等待智能眼镜端连接指令通道...")
    sender.accept_client()
    
    window_title = "PC Debug - Raw Stream"
    print("[*] 系统已就绪，开始运行云端 AI 决策循环...")
    
    try:
        # 4. 主循环
        while True:
            # 向 Receiver 索取最新一帧图像
            frame = receiver.get_frame(timeout=0.1)
            
            if frame is not None:
                # 修复 3:4 竖置传感器的方向问题
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                
                # --- CV 核心处理：提取棋盘与网格识别 ---
                warped_board, _ = agent._extract_board(frame)
                
                if warped_board is not None:
                    # 1. 识别 15x15 棋盘矩阵状态 (0:空, 1:黑, 2:白)
                    board_state = agent._recognize_stones(warped_board)
                    
                    # 2. AI 计算下一步最优解
                    next_move = agent._calculate_next_move(board_state) if hasattr(agent, '_calculate_next_move') else None
                    
                    # 3. 通过 TCP 将棋盘矩阵和决策打包成 JSON 发送给眼镜
                    sender.send_game_state(board_state, next_move)
                    
                    # 4. 本地弹窗显示 AI 眼中的正方形棋盘（用于实时监控 CV 识别准确度）
                    cv2.imshow("AI Vision Board", warped_board)
                else:
                    cv2.putText(frame, "Board not found!", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                
                # 显示 PC 端接收到的眼镜原始图传画面
                cv2.imshow(window_title, frame)
            
            # 按 'q' 键退出
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
                
    finally:
        # 5. 安全打扫战场
        sender.close()
        receiver.stop()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()