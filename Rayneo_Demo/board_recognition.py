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
        warp_size=960,
        weights_path=r"D:\SummerIntern\Code\AIGlasses_SDK\Rayneo\trained_networks\GO_PIECEX1.pt",
        corner_weights_path=r"D:\SummerIntern\Code\AIGlasses_SDK\Rayneo\trained_networks\corner_detection.pt",
        pair_weights_path=r"D:\SummerIntern\Code\AIGlasses_SDK\Rayneo\trained_networks\GO_PIECEX2.pt",
        # Disk capture is disabled by default so latency measurements reflect
        # the live pipeline rather than synchronous JPEG writes.
        save_dir=None,
        save_interval=0.0,
        sharpness_thresh=15.0  # 💡 清晰度阈值：画面本身若不清晰可设小一点（如 15~30），防止过度误杀
    ):
        self.board_size = board_size
        self.warp_size = warp_size
        self.sharpness_thresh = sharpness_thresh
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"

        print(f"[*] 正在初始化 YOLO 视觉中枢 ({self.device}): {weights_path} ...")
        try:
            self.model = torch.hub.load(
                'ultralytics/yolov5',
                'custom',
                path=weights_path,
                device=self.device,
                force_reload=False,
            )
            dummy = np.zeros((960, 960, 3), dtype=np.uint8)
            self.model(dummy, size=960)
            if self.device.startswith("cuda"):
                torch.cuda.synchronize()
            self.corner_model = torch.hub.load('ultralytics/yolov5', 'custom', path=corner_weights_path, device=self.device, force_reload=False)
            self.pair_model = torch.hub.load('ultralytics/yolov5', 'custom', path=pair_weights_path, device=self.device, force_reload=False)
            self.corner_model(dummy, size=640)
            self.pair_model(dummy, size=960)
            if self.device.startswith("cuda"):
                torch.cuda.synchronize()
            print("[*] YOLO 视觉中枢就绪！")
        except Exception as e:
            print(f"[!] YOLO 加载失败，请检查路径: {e}")
            self.model = None
            self.corner_model = None
            self.pair_model = None

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

    def _paper_preprocess(self, bgr):
        """Match the paper's grayscale and histogram-equalization stage.

        YOLO still receives three channels, but all three contain the same
        equalized grayscale signal, as when a grayscale image is reloaded by
        the original YOLOv5 data loader.
        """
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        equalized = cv2.equalizeHist(gray)
        return cv2.cvtColor(equalized, cv2.COLOR_GRAY2BGR)

    def _detect_and_warp_board(self, frame):
        """Paper stage 1: detect four board corners, then rectify the source frame."""
        if self.corner_model is None:
            return None
        result = self.corner_model(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), size=640)
        if self.device.startswith("cuda"):
            torch.cuda.synchronize()
        corners = result.pandas().xyxy[0]
        corners = corners[corners["name"] == "corner"].copy()
        # Pandas 3 may expose YOLO's confidence column as object dtype.
        # Convert explicitly before ranking detections by confidence.
        corners["confidence"] = pd.to_numeric(corners["confidence"], errors="coerce")
        corners = corners.dropna(subset=["confidence"]).sort_values(
            "confidence", ascending=False
        ).head(4)
        if len(corners) != 4:
            return None
        points = np.array([
            [(row.xmin + row.xmax) / 2, (row.ymin + row.ymax) / 2]
            for row in corners.itertuples()
        ], dtype=np.float32)
        ordered = self._order_points(points)
        if abs(cv2.contourArea(ordered.reshape(-1, 1, 2))) < frame.shape[0] * frame.shape[1] * 0.02:
            return None
        side = self.warp_size - 1
        target = np.array([[0, 0], [side, 0], [side, side], [0, side]], dtype=np.float32)
        self.prev_M = cv2.getPerspectiveTransform(ordered, target)
        return cv2.warpPerspective(frame, self.prev_M, (self.warp_size, self.warp_size))

    # --------------- 阶段一：原图清晰度检测 + 粗定位裁剪 ---------------
    def extract_board(self, frame):
        t_start = time.time() * 1000 # 探针：预处理开始

        self.frame_count += 1
        current_time = time.time()
        elapsed = current_time - self.fps_start_time
        if elapsed >= 1.0:
            fps = self.frame_count / elapsed
            print(f"\n[TCP+视觉] 接收与处理流水线帧率: {fps:.1f} FPS")
            self.frame_count = 0
            self.fps_start_time = current_time

        # 🔍 1. 清晰度检测
        gray_raw = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sharpness_score = cv2.Laplacian(gray_raw, cv2.CV_64F).var()
        
        t_sharp = time.time() * 1000 # 探针：清晰度检测完成

        if sharpness_score < self.sharpness_thresh:
            self.current_save_timestamp = None
            return None

        paper_frame = self._paper_preprocess(frame)
        warped = self._detect_and_warp_board(paper_frame)
        if warped is not None:
            print("  ├─ [Paper pipeline] corner detection + perspective warp: enabled")
            return warped

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

        t_cv = time.time() * 1000 # 探针：CV提取完成

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

        t_io = time.time() * 1000 # 探针：存图IO完成
        
        print(f"  ├─ [CV提取] 清晰度: {t_sharp-t_start:.1f}ms | 轮廓裁剪: {t_cv-t_sharp:.1f}ms | 存图IO阻塞: {t_io-t_cv:.1f}ms")

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

        # Keep the timing boundaries explicit.  ``model_call`` is the online
        # cost of the YOLOv5 wrapper (resize, inference and NMS); dataframe is
        # measured separately because it is Python-side post-processing.
        t_start = time.perf_counter()
        warped_bgr = self._paper_preprocess(warped_bgr)
        img_rgb = cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2RGB)
        t_preprocess = time.perf_counter()

        results = self.model(img_rgb, size=960)
        if self.device.startswith("cuda"):
            # CUDA calls are asynchronous.  Synchronize before recording the
            # timestamp so model_call is actual wall-clock latency.
            torch.cuda.synchronize()
        t_model = time.perf_counter()
        df = results.pandas().xyxy[0]
        t_dataframe = time.perf_counter()

        pair_results = self.pair_model(img_rgb, size=self.warp_size)
        if self.device.startswith("cuda"):
            torch.cuda.synchronize()
        pair_df = pair_results.pandas().xyxy[0]
        t_pair = time.perf_counter()

        print(
            "  ├─ [YOLO benchmark] "
            f"preprocess: {(t_preprocess - t_start) * 1000:.1f}ms | "
            f"model_call: {(t_model - t_preprocess) * 1000:.1f}ms | "
            f"dataframe: {(t_dataframe - t_model) * 1000:.1f}ms | "
            f"X2_pair: {(t_pair - t_dataframe) * 1000:.1f}ms"
        )

        corners = df[df['name'] == 'corner']
        if len(corners) >= 3:
            centers = []
            for _, row in corners.iterrows():
                centers.append([(row['xmin'] + row['xmax']) / 2, (row['ymin'] + row['ymax']) / 2])
            centers = np.array(centers)
            min_x, max_x = np.min(centers[:, 0]), np.max(centers[:, 0])
            min_y, max_y = np.min(centers[:, 1]), np.max(centers[:, 1])
        else:
            # The corner model has already rectified this board.  Do not
            # discard a valid frame merely because X1 omits its corner class.
            height, width = warped_bgr.shape[:2]
            min_x, max_x = 0.0, float(width - 1)
            min_y, max_y = 0.0, float(height - 1)

        cell_w = (max_x - min_x) / (self.board_size - 1)
        cell_h = (max_y - min_y) / (self.board_size - 1)

        cur_state = np.zeros((self.board_size, self.board_size), dtype=np.uint8)
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
                if name == 'black' or name == '1' or cls_id == 1 or name == 'b':
                    label = 1 
                elif name == 'white' or name == '2' or cls_id == 2 or name == 'w' or 'stone' in name:
                    label = 2 
                if label > 0:
                    cur_state[i, j] = label

        # Paper stage 3: X2 boxes cover two horizontal intersections.  Use
        # them to fill X1 omissions; X1 remains preferred on disagreement
        # until a trained stacking fusion model is available for this dataset.
        paper_to_board = {"0": 0, "1": 2, "2": 1}
        pair_rows = pair_df[pair_df["name"].astype(str).str.fullmatch(r"[012]{2}")]
        for _, row in pair_rows.iterrows():
            label = str(row["name"])
            cx = (row["xmin"] + row["xmax"]) / 2
            cy = (row["ymin"] + row["ymax"]) / 2
            i = int(round((cy - min_y) / cell_h))
            left_j = int(round((cx - cell_w / 2 - min_x) / cell_w))
            for offset, state_char in enumerate(label):
                j = left_j + offset
                if 0 <= i < self.board_size and 0 <= j < self.board_size and cur_state[i, j] == 0:
                    cur_state[i, j] = paper_to_board[state_char]

        final_board_matrix = self._temporal_smooth(cur_state)
        
        t_logic = time.perf_counter()

        if self.current_save_timestamp and self.save_dir:
            board_img_path = os.path.join(self.save_dir, f"board_reconstruct_{self.current_save_timestamp}.jpg")
            self._draw_virtual_board(final_board_matrix, board_img_path)
            self.current_save_timestamp = None 

        t_io = time.perf_counter()
        
        print(
            "  ├─ [AI解析] "
            f"X1+X2: {(t_pair - t_start) * 1000:.1f}ms | "
            f"coordinate_mapping: {(t_logic - t_pair) * 1000:.1f}ms | "
            f"render_write: {(t_io - t_logic) * 1000:.1f}ms"
        )

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
