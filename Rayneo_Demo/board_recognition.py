import cv2
import numpy as np

class GomokuBoardRecognizer:
    """
    负责：棋盘定位、透视矫正、网格交点定位、棋子识别、时序平滑
    """
    def __init__(
        self,
        board_size=15,
        warp_size=720,
        sample_radius_ratio=0.28,
        smooth_alpha=0.6,
        use_hough=True,
    ):
        self.board_size = board_size
        self.warp_size = warp_size
        self.sample_radius_ratio = sample_radius_ratio
        self.smooth_alpha = smooth_alpha
        self.use_hough = use_hough

        self.prev_state = None
        self.prev_conf = None
        self.prev_M = None

    # --------------- 棋盘提取与透视 ---------------
    def extract_board(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 50, 150)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return self._use_prev_m(frame)

        largest_contour = max(contours, key=cv2.contourArea)
        epsilon = 0.02 * cv2.arcLength(largest_contour, True)
        approx = cv2.approxPolyDP(largest_contour, epsilon, True)

        if len(approx) != 4:
            return self._use_prev_m(frame)

        pts = approx.reshape(4, 2).astype(np.float32)
        rect = self._order_points(pts)
        size = self.warp_size
        dst = np.array(
            [[0, 0], [size - 1, 0], [size - 1, size - 1], [0, size - 1]], dtype="float32"
        )

        M = cv2.getPerspectiveTransform(rect, dst)
        self.prev_M = M
        warped = cv2.warpPerspective(frame, M, (size, size))
        return warped, M

    def _use_prev_m(self, frame):
        """如果当前帧没找到边缘，复用上一帧的透视矩阵防止闪烁"""
        if self.prev_M is not None:
            warped = cv2.warpPerspective(frame, self.prev_M, (self.warp_size, self.warp_size))
            return warped, self.prev_M
        return None, None

    @staticmethod
    def _order_points(pts):
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        return rect

    # --------------- 网格交点定位 ---------------
    def _detect_intersections(self, gray):
        if not self.use_hough:
            return None
            
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        edges = cv2.Canny(blur, 40, 120)
        lines = cv2.HoughLinesP(
            edges, 1, np.pi / 180, threshold=100, minLineLength=80, maxLineGap=20
        )
        if lines is None or len(lines) == 0:
            return None

        lines = np.squeeze(lines)
        if lines.ndim == 1 and lines.size == 4:
            lines = lines.reshape(1, 4)
        if lines.ndim != 2 or lines.shape[1] != 4:
            return None

        horizontal, vertical = [], []
        for x1, y1, x2, y2 in lines:
            if abs(y2 - y1) > abs(x2 - x1):
                vertical.append((x1, y1, x2, y2))
            else:
                horizontal.append((x1, y1, x2, y2))

        def cluster_lines(lines_list, count):
            if not lines_list: return None
            coords = np.array([[(x1 + x2) / 2.0, (y1 + y2) / 2.0] for x1, y1, x2, y2 in lines_list])
            axis = 0 if abs(lines_list[0][0] - lines_list[0][2]) < abs(lines_list[0][1] - lines_list[0][3]) else 1
            vals = coords[:, axis]
            vals_sorted = np.sort(vals)
            
            clusters = []
            if len(vals_sorted) < count:
                clusters = np.linspace(vals_sorted.min(), vals_sorted.max(), count)
            else:
                step = len(vals_sorted) // count
                for i in range(count):
                    segment = vals_sorted[i * step : (i + 1) * step]
                    clusters.append(np.median(segment))
            clusters = np.array(clusters)
            clusters.sort()
            return clusters

        horiz_lines = cluster_lines(horizontal, self.board_size)
        vert_lines = cluster_lines(vertical, self.board_size)
        if horiz_lines is None or vert_lines is None:
            return None

        intersections = np.zeros((self.board_size, self.board_size, 2), dtype=np.float32)
        for i, y in enumerate(horiz_lines):
            for j, x in enumerate(vert_lines):
                intersections[i, j] = [x, y]
        return intersections

    # --------------- 棋子识别 ---------------
    def recognize_stones(self, warped_bgr):
        state = np.zeros((self.board_size, self.board_size), dtype=np.uint8)
        conf = np.zeros_like(state, dtype=np.float32)

        gray = cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2GRAY)
        
        # 💡 优化 1：计算全局平均亮度，用于动态阈值判断
        board_mean = float(np.mean(gray))
        
        intersections = self._detect_intersections(gray)
        
        # 💡 优化 2：降级保护。如果霍夫直线失败，退回均匀网格切分，防止丢失画面
        if intersections is None:
            intersections = np.zeros((self.board_size, self.board_size, 2), dtype=np.float32)
            cell_size = self.warp_size / self.board_size
            for i in range(self.board_size):
                for j in range(self.board_size):
                    intersections[i, j] = [j * cell_size + cell_size / 2, i * cell_size + cell_size / 2]

        r = int(self.sample_radius_ratio * self.warp_size / self.board_size)
        r = max(r, 2)

        for i in range(self.board_size):
            for j in range(self.board_size):
                # 💡 BUG 修复：原来写的是 cy, cx = ... 导致了 XY 轴翻转！
                cx, cy = intersections[i, j]
                cy, cx = int(cy), int(cx)
                
                y0, y1 = max(0, cy - r), min(gray.shape[0], cy + r)
                x0, x1 = max(0, cx - r), min(gray.shape[1], cx + r)
                roi = gray[y0:y1, x0:x1]
                if roi.size == 0: continue

                mask = np.zeros_like(roi, dtype=np.uint8)
                cv2.circle(mask, (roi.shape[1] // 2, roi.shape[0] // 2), min(r, roi.shape[0] // 2, roi.shape[1] // 2), 255, -1)
                masked = cv2.bitwise_and(roi, roi, mask=mask)

                mean = float(masked[mask == 255].mean())
                std = float(masked[mask == 255].std())

                # 💡 优化 3：动态相对阈值（抵抗反光和暗光）
                if mean < board_mean * 0.65:       # 比平均亮度暗 35% 以上，是黑棋
                    state[i, j] = 1
                    conf[i, j] = 0.8 + np.clip(std / 100.0, 0, 0.2)
                elif mean > board_mean * 1.35:     # 比平均亮度亮 35% 以上，是白棋
                    state[i, j] = 2
                    conf[i, j] = 0.8 + np.clip(std / 100.0, 0, 0.2)
                else:                              # 否则是空位
                    state[i, j] = 0
                    conf[i, j] = 0.9

        # 时序平滑
        if self.prev_state is not None and self.prev_conf is not None:
            state, conf = self._temporal_smooth(state, conf, self.prev_state, self.prev_conf)

        self.prev_state = state.copy()
        self.prev_conf = conf.copy()
        return state

    def _temporal_smooth(self, cur_state, cur_conf, prev_state, prev_conf):
        fused_state = cur_state.copy()
        fused_conf = cur_conf.copy()

        # 置信度平滑滤波
        mask_mid = (cur_conf < 0.6) & (cur_conf >= 0.3)
        fused_state[mask_mid] = cur_state[mask_mid]
        fused_conf[mask_mid] = (self.smooth_alpha * cur_conf[mask_mid] + (1 - self.smooth_alpha) * prev_conf[mask_mid])

        mask_weak = cur_conf < 0.3
        fused_state[mask_weak] = prev_state[mask_weak]
        fused_conf[mask_weak] = prev_conf[mask_weak]
        
        # 💡 优化 4：五子棋“死锁”物理法则。历史上有棋子的地方，绝对不能变回空位！
        mask_has_piece = (prev_state != 0)
        fused_state[mask_has_piece] = prev_state[mask_has_piece]

        return fused_state, fused_conf