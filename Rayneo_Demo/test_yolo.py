import torch
import time
import cv2
import numpy as np

def draw_virtual_board(matrix, board_size=15):
    """根据 15x15 矩阵绘制干净的虚拟棋盘"""
    canvas_size = 750
    board_img = np.ones((canvas_size, canvas_size, 3), dtype=np.uint8) * 210
    board_img[:] = (210, 180, 140) # 经典的木色背景 (BGR)

    margin = 60
    grid_span = (canvas_size - 2 * margin) / (board_size - 1)

    # 1. 画 15x15 网格线
    for i in range(board_size):
        pos = int(margin + i * grid_span)
        cv2.line(board_img, (margin, pos), (canvas_size - margin, pos), (50, 50, 50), 1)
        cv2.line(board_img, (pos, margin), (pos, canvas_size - margin), (50, 50, 50), 1)

    # 2. 画星位
    star_points = [3, 7, 11]
    for sx in star_points:
        for sy in star_points:
            sx_px = int(margin + sx * grid_span)
            sy_px = int(margin + sy * grid_span)
            cv2.circle(board_img, (sx_px, sy_px), 4, (50, 50, 50), -1)

    # 3. 绘制棋子 (1: 黑子, 2: 白子)
    radius = int(grid_span * 0.42)
    for i in range(board_size):
        for j in range(board_size):
            piece = matrix[i, j]
            if piece == 0:
                continue
            cx = int(margin + j * grid_span)
            cy = int(margin + i * grid_span)

            if piece == 1: # 黑子
                cv2.circle(board_img, (cx, cy), radius, (20, 20, 20), -1)
                cv2.circle(board_img, (cx, cy), radius, (0, 0, 0), 1)
            elif piece == 2: # 白子
                cv2.circle(board_img, (cx, cy), radius, (240, 240, 240), -1)
                cv2.circle(board_img, (cx, cy), radius, (100, 100, 100), 1)

    return board_img

def test_single_image(weights_path, image_path):
    print(f"[*] 正在加载模型: {weights_path} ...")
    
    try:
        model = torch.hub.load('ultralytics/yolov5', 'custom', path=weights_path, force_reload=False)
    except Exception as e:
        print(f"[!] 模型加载失败: {e}")
        return

    print("[*] 模型预热中...")
    dummy_img = np.zeros((810, 810, 3), dtype=np.uint8)
    model(dummy_img, size=810)

    print(f"[*] 正在读取测试图片: {image_path}")
    img = cv2.imread(image_path)
    if img is None:
        print("[!] 找不到图片！请检查 TEST_IMG 路径是否正确。")
        return
        
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    start_time = time.time()
    results = model(img_rgb, size=810)
    end_time = time.time()
    latency = (end_time - start_time) * 1000  
    
    print(f"\n✅ 推理完成！")
    print(f"⏱️ 单张图片推断延迟: {latency:.2f} ms")
    
    df = results.pandas().xyxy[0]
    print("\n📊 原始 YOLO 检测结果 DataFrame:")
    print(df)
    print("当前检测到的所有类别名称:", df['name'].unique())

    # --- 🔍 生成仅保留角点的调试原图（内存中展示，不落盘存储） ---
    debug_corners_img = img.copy()
    corners_df = df[df['name'] == 'corner']
    print(f"\n🎯 成功检测到的角点数量: {len(corners_df)}")
    
    for _, row in corners_df.iterrows():
        xmin, ymin, xmax, ymax = int(row['xmin']), int(row['ymin']), int(row['xmax']), int(row['ymax'])
        conf = row['confidence']
        cv2.rectangle(debug_corners_img, (xmin, ymin), (xmax, ymax), (0, 255, 0), 3)
        cv2.putText(debug_corners_img, f"corner {conf:.2f}", (xmin, max(0, ymin - 10)), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    # --- 🔄 将 YOLO 目标解析并映射为 15x15 矩阵 ---
    board_size = 15
    cur_state = np.zeros((board_size, board_size), dtype=np.uint8)

    if len(corners_df) >= 3:
        centers = []
        for _, row in corners_df.iterrows():
            centers.append([(row['xmin'] + row['xmax']) / 2, (row['ymin'] + row['ymax']) / 2])
        centers = np.array(centers)
        min_x, max_x = np.min(centers[:, 0]), np.max(centers[:, 0])
        min_y, max_y = np.min(centers[:, 1]), np.max(centers[:, 1])
    else:
        h_img, w_img, _ = img.shape
        margin = int(w_img * 0.1)
        min_x, max_x = margin, w_img - margin
        min_y, max_y = margin, h_img - margin

    cell_w = (max_x - min_x) / (board_size - 1)
    cell_h = (max_y - min_y) / (board_size - 1)

    # 严格过滤掉 corner，只处理棋子类别
    pieces = df[df['name'] != 'corner']
    for _, row in pieces.iterrows():
        name = str(row['name']).lower()
        cx = (row['xmin'] + row['xmax']) / 2
        cy = (row['ymin'] + row['ymax']) / 2

        j = int(round((cx - min_x) / cell_w))
        i = int(round((cy - min_y) / cell_h))

        if 0 <= i < board_size and 0 <= j < board_size:
            # 兼容不同模型的标签命名习惯，同时把带红点的特殊白子等情况也稳稳包容进来
            if 'black' in name or name == '0' or name == 'b':
                cur_state[i, j] = 1  # 黑子
            elif 'white' in name or name == '2' or name == 'w' or 'stone' in name:
                cur_state[i, j] = 2  # 白子

    # 渲染虚拟棋盘
    virtual_board_img = draw_virtual_board(cur_state, board_size)

    # 直接弹窗实时显示，取消所有 cv2.imwrite 本地落盘逻辑
    cv2.imshow("Debug Corners Only", debug_corners_img)
    cv2.imshow("Reconstructed Virtual Board", virtual_board_img)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    WEIGHTS = r"D:\SummerIntern\Code\AIGlasses_SDK\Rayneo\trained_networks\GO_PIECEX1.pt" 
    TEST_IMG = r"D:\SummerIntern\File\Gomoku_Test.jpg"
    
    test_single_image(WEIGHTS, TEST_IMG)