import cv2
import numpy as np
import torch
import pandas as pd
import time
import os
import threading
from datetime import datetime

class GomokuBoardRecognizer:
    """
    两级联架构：OpenCV 粗定位提取棋盘 + YOLOv5 精细解析棋局 (CPU)
    【已集成：原图清晰度检测（抗模糊） + 双模型兼容 + 严格弃帧策略】
    """
    def __init__(
        self, 
        board_size=15, 
        warp_size=750, 
        weights_path=r"D:\SummerIntern\Code\AIGlasses_SDK\Rayneo\trained_networks\GO_PIECEX1.pt",
        save_dir=r"D:\SummerIntern\Data\OriginPic", 
        save_interval=0.0,
        sharpness_thresh=25.0  # 💡 清晰度阈值：画面本身若不清晰可设小一点（如 15~30），防止过度误杀
    ):
        self.board_size = board_size
        self.warp_size = warp_size
        self.sharpness_thresh = sharpness_thresh

        print(f"[*] 正在初始化 YOLO 视觉中枢 (CPU模式): {weights_path} ...")
        try:
            self.model = torch.hub.load('ultralytics/yolov5', 'custom', path=weights_path, device='cpu', force_reload=False)
            dummy = np.zeros((960, 960, 3), dtype=np.uint8)
            self.model(dummy, size=960)
            print("[*] YOLO 视觉中枢就绪！")
        except Exception as e:
            print(f"[!] YOLO 加载失败，请检查路径: {e}")
            self.model = None

        self.prev_M = None
        self.prev_bbox = None
        
        # 时序平滑机制
        self.stable_state = np.zeros((board_size, board_size), dtype=np.uint8)
        self.confidence_matrix = np.zeros((board_size, board_size), dtype=np.int32)

        # ---------------- 内置采集与性能监控变量 ----------------
        self.save_dir = save_dir
        self.save_interval = save_interval
        self.last_save_time = 0.0
        self.current_save_timestamp = None 
        
        if self.save_dir:
            os.makedirs(self.save_dir, exist_ok=True)
            print(f"[*] 🚀 数据集采集模式已就绪！\n[*] 存储路径: {self.save_dir}")

        # FPS 监控变量
        self.frame_count = 0
        self.fps_start_time = time.time()

    def _order_points(self, pts):
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        return rect

    # --------------- 阶段一：原图清晰度检测 + 粗定位裁剪 ---------------
    def extract_board(self, frame):
        self.frame_count += 1
        current_time = time.time()
        elapsed = current_time - self.fps_start_time
        if elapsed >= 1.0:
            fps = self.frame_count / elapsed
            print(f"[TCP+视觉] 接收与处理流水线帧率: {fps:.1f} FPS")
            self.frame_count = 0
            self.fps_start_time = current_time

        # 🔍 1. 刚进来的原图直接做清晰度检测（Laplacian 方差法）
        gray_raw = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sharpness_score = cv2.Laplacian(gray_raw, cv2.CV_64F).var()
        
        if sharpness_score < self.sharpness_thresh:
            # 运动模糊或晃动太剧烈，直接丢弃该帧！
            # print(f"[!] 画面模糊 (清晰度得分: {sharpness_score:.1f} < {self.sharpness_thresh})，主动丢弃")
            self.current_save_timestamp = None
            return None

        # 2. 传统 CV 粗定位
        blur = cv2.GaussianBlur(gray_raw, (5, 5), 0)
        edges = cv2.Canny(blur, 30, 100)
        kernel_dilate = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        edges = cv2.dilate(edges, kernel_dilate, iterations=1)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        cropped_bgr = None

        if not contours:
            cropped_bgr = self._use_prev_bbox(frame)
        else:
            largest_contour = max(contours, key=cv2.contourArea)
            total_area = frame.shape[0] * frame.shape[1]
            
            if cv2.contourArea(largest_contour) < total_area * 0.05:
                cropped_bgr = self._use_prev_bbox(frame)
            else:
                x, y, w, h = cv2.boundingRect(largest_contour)
                margin_x, margin_y = int(w * 0.03), int(h * 0.03)
                x1 = max(0, x - margin_x)
                y1 = max(0, y - margin_y)
                x2 = min(frame.shape[1], x + w + margin_x)
                y2 = min(frame.shape[0], y + h + margin_y)
                
                self.prev_bbox = (x1, y1, x2, y2)
                cropped_bgr = frame[y1:y2, x1:x2]

        # 同步保存原图与裁剪图
        if cropped_bgr is not None and self.save_dir:
            if current_time - self.last_save_time >= self.save_interval:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                cv2.imwrite(os.path.join(self.save_dir, f"raw_frame_{timestamp}.jpg"), frame)
                cv2.imwrite(os.path.join(self.save_dir, f"cropped_{timestamp}.jpg"), cropped_bgr)
                
                self.last_save_time = current_time
                self.current_save_timestamp = timestamp 
            else:
                self.current_save_timestamp = None
        else:
            self.current_save_timestamp = None

        return cropped_bgr

    def _use_prev_bbox(self, frame):
        if self.prev_bbox is not None:
            x1, y1, x2, y2 = self.prev_bbox
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
            return frame[y1:y2, x1:x2]
        return None

    # --------------- 阶段二：YOLO 精细解析（过滤 empty + 稳定平滑） ---------------
    def recognize_stones(self, warped_bgr):
        if self.model is None or warped_bgr is None:
            return self.stable_state.copy()

        img_rgb = cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2RGB)
        results = self.model(img_rgb, size=960)
        df = results.pandas().xyxy[0]

        corners = df[df['name'] == 'corner']
        
        # 角点不足 3 个直接丢弃
        if len(corners) < 3:
            self.current_save_timestamp = None 
            return self.stable_state.copy()

        centers = []
        for _, row in corners.iterrows():
            centers.append([(row['xmin'] + row['xmax']) / 2, (row['ymin'] + row['ymax']) / 2])
        centers = np.array(centers)
        min_x, max_x = np.min(centers[:, 0]), np.max(centers[:, 0])
        min_y, max_y = np.min(centers[:, 1]), np.max(centers[:, 1])

        cell_w = (max_x - min_x) / (self.board_size - 1)
        cell_h = (max_y - min_y) / (self.board_size - 1)

        cur_state = np.zeros((self.board_size, self.board_size), dtype=np.uint8)
        
        # 🎯 核心：过滤掉 corner 和干扰性的 empty 空位框
        pieces = df[~df['name'].isin(['corner', 'empty'])]

        for _, row in pieces.iterrows():
            name = str(row['name']).lower()
            cls_id = int(row['class']) if 'class' in row else -1
            
            cx = (row['xmin'] + row['xmax']) / 2
            cy = (row['ymin'] + row['ymax']) / 2

            j = int(round((cx - min_x) / cell_w))
            i = int(round((cy - min_y) / cell_h))

            if 0 <= i < self.board_size and 0 <= j < self.board_size:
                label = 0
                # 兼容不同模型的标签命名习惯
                if name == 'black' or name == '1' or cls_id == 1 or name == 'b':
                    label = 1  # 黑子
                elif name == 'white' or name == '2' or cls_id == 2 or name == 'w' or 'stone' in name:
                    label = 2  # 白子
                
                if label > 0:
                    cur_state[i, j] = label

        final_board_matrix = self._temporal_smooth(cur_state)

        if self.current_save_timestamp and self.save_dir:
            board_img_path = os.path.join(self.save_dir, f"board_reconstruct_{self.current_save_timestamp}.jpg")
            self._draw_virtual_board(final_board_matrix, board_img_path)
            self.current_save_timestamp = None 

        return final_board_matrix

    def _draw_virtual_board(self, matrix, save_path):
        canvas_size = 750
        board_img = np.ones((canvas_size, canvas_size, 3), dtype=np.uint8)
        board_img[:] = (210, 180, 140)

        margin = 60
        grid_span = (canvas_size - 2 * margin) / (self.board_size - 1)

        for i in range(self.board_size):
            start_pos = int(margin + i * grid_span)
            cv2.line(board_img, (margin, start_pos), (canvas_size - margin, start_pos), (50, 50, 50), 1)
            cv2.line(board_img, (start_pos, margin), (start_pos, canvas_size - margin), (50, 50, 50), 1)

        star_points = [3, 7, 11]
        for sx in star_points:
            for sy in star_points:
                sx_px = int(margin + sx * grid_span)
                sy_px = int(margin + sy * grid_span)
                cv2.circle(board_img, (sx_px, sy_px), 4, (50, 50, 50), -1)

        radius = int(grid_span * 0.42)
        for i in range(self.board_size):
            for j in range(self.board_size):
                piece = matrix[i, j]
                if piece == 0:
                    continue
                
                cx = int(margin + j * grid_span)
                cy = int(margin + i * grid_span)

                if piece == 1:
                    cv2.circle(board_img, (cx, cy), radius, (20, 20, 20), -1)
                    cv2.circle(board_img, (cx, cy), radius, (0, 0, 0), 1)
                elif piece == 2:
                    cv2.circle(board_img, (cx, cy), radius, (240, 240, 240), -1)
                    cv2.circle(board_img, (cx, cy), radius, (100, 100, 100), 1)

        cv2.imwrite(save_path, board_img)

    def _temporal_smooth(self, cur_state):
        max_confidence = 4
        for i in range(self.board_size):
            for j in range(self.board_size):
                obs_state = cur_state[i, j]
                curr_stable = self.stable_state[i, j]

                if obs_state == curr_stable:
                    self.confidence_matrix[i, j] = min(max_confidence, self.confidence_matrix[i, j] + 1)
                else:
                    self.confidence_matrix[i, j] = max(0, self.confidence_matrix[i, j] - 1)
                    if self.confidence_matrix[i, j] == 0:
                        self.stable_state[i, j] = obs_state
                        self.confidence_matrix[i, j] = 1

        return self.stable_state.copy()