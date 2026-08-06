import cv2
import numpy as np
import mss
import time  # 【新增】导入时间模块
from gomoku_agent import GomokuAgent


def main():
    agent = GomokuAgent(board_size=15)
    sct = mss.mss()
    
    # ================= 【新增】倒计时切换窗口逻辑 =================
    print("[*] 脚本已启动！请立刻切换到你的五子棋网页/游戏界面。")
    for i in range(3, 0, -1):
        print(f"[*] 倒计时 {i} 秒抓取屏幕...")
        time.sleep(1)
    print("[*] 咔嚓！屏幕已抓取。")
    # ==============================================================

    # 1. 截取此时的主显示器全屏画面（这个时候你应该已经在看五子棋了）
    monitor_full = sct.monitors[1]
    full_screen_img = np.array(sct.grab(monitor_full))
    full_screen_img = cv2.cvtColor(full_screen_img, cv2.COLOR_BGRA2BGR)
    
    # 2. 交互式框选
    print("[*] 请在弹出的画面中，用鼠标框选出五子棋盘。")
    print("[*] 框好之后，按 SPACE(空格) 或 ENTER(回车) 确认！")
    
    cv2.namedWindow("Select Chessboard Region", cv2.WINDOW_NORMAL)
    cv2.setWindowProperty("Select Chessboard Region", cv2.WND_PROP_TOPMOST, 1)
    
    # 弹出刚才抓取到的网页画面供你框选
    roi = cv2.selectROI("Select Chessboard Region", full_screen_img, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow("Select Chessboard Region")
    
    x, y, w, h = roi
    if w == 0 or h == 0:
        print("[!] 你没有框选任何有效区域，测试已退出。")
        return
        
    print(f"[*] 框选成功！已锁定坐标: 左上({x}, {y}), 宽{w}, 高{h}")
    
    monitor_roi = {
        "top": monitor_full["top"] + y,
        "left": monitor_full["left"] + x,
        "width": w,
        "height": h
    }
    
    print("[*] 正在对锁定区域进行实时 AI 识别... (按 'q' 键退出)")
    window_title = "AI Local Test"

    # 3. 实时循环
    while True:
        sct_img = sct.grab(monitor_roi)
        frame = np.array(sct_img)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        
        processed_frame = agent.process_frame(frame)
        cv2.imshow(window_title, processed_frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()