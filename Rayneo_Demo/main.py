import cv2
import numpy as np
import time
from stream_receiver import StreamReceiver
from gomoku_agent import GomokuAgent
from stream_sender import GomokuServerSender  # 引入刚才编写的 TCP 发送模块

def main():
    # 1. 初始化接收器、AI Agent 和 TCP 指令服务端
    receiver = StreamReceiver(port=9999)
    agent = GomokuAgent(board_size=15)
    sender = GomokuServerSender(port=9988)
    
    receiver.start()
    
    print("[*] 等待智能眼镜端连接指令通道...")
    sender.accept_client()
    
    # 💡 核心修改 1：窗口初始化和大小设置必须放在 while 循环外面！
    # 加上 cv2.WINDOW_KEEPRATIO 锁定宽高比，防止被暴力拉伸
    cv2.namedWindow("AR Gomoku View", cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
    cv2.resizeWindow("AR Gomoku View", 960, 540)  # 16:9 的标准横屏尺寸（或 1280, 720）
    
    print("[*] 系统已就绪，开始运行云端 AI 决策循环...")
    
    try:
        while True:
            frame = receiver.get_frame(timeout=0.1)
            
            if frame is not None:
                # This is deliberately measured after get_frame(): queue wait
                # and JPEG decode are already reported by StreamReceiver.
                t_pc_process_start = time.perf_counter()
                # 修复 3:4 竖置传感器的方向问题（旋转后变为 16:9 横屏）
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                
                # --- CV 核心处理 ---
                warped_board = agent._extract_board(frame)
                agent.recognizer.draw_debug_overlay(frame)
                
                if warped_board is not None:
                    board_state = agent._recognize_stones(warped_board)
                    next_move = agent._calculate_next_move(board_state) if hasattr(agent, '_calculate_next_move') else None
                    sender.send_game_state(board_state, next_move)
                    
                    # 显示正方形的 AI 棋盘
                    cv2.imshow("AI Vision Board", warped_board)
                else:
                    cv2.putText(frame, "Board not found!", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                
                # Per-frame resolution logging is intentionally disabled; it
                # adds terminal noise without helping the latency benchmark.
                # print(f"🤓 眼镜原始画面尺寸 (高, 宽, 通道): {frame.shape}")

                # 💡 核心修改 2：循环内部只负责用 imshow 刷新画面，绝不重复调用 namedWindow 和 resizeWindow！
                cv2.imshow("AR Gomoku View", frame)
                print(
                    "  └─ [PC pipeline] "
                    f"process_after_decode: {(time.perf_counter() - t_pc_process_start) * 1000:.1f}ms"
                )
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
                
    finally:
        sender.close()
        receiver.stop()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
