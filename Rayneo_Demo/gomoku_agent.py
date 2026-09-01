import cv2
import numpy as np
from aruco_board_recognition import GomokuBoardRecognizer


class GomokuAgent:
    def __init__(self, board_size=15):
        self.board_size = board_size
        # 定义棋子状态：0为空，1为黑（玩家），2为白（AI）
        self.EMPTY = 0
        self.BLACK = 1
        self.WHITE = 2
        self.recognizer = GomokuBoardRecognizer(board_size=board_size)

    def process_frame(self, frame):
        """
        处理传入的视频帧：识别棋盘、提取棋子、计算下一步，并绘制结果
        """
        # 1. 寻找棋盘并进行透视变换拉平
        warped_board = self.recognizer.extract_board(frame)
        if warped_board is None:
            cv2.putText(frame, "Board not found!", (50, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            return frame

        # 2. 识别棋局状态 (返回 15x15 的二维数组)
        board_state = self.recognizer.recognize_stones(warped_board)

        # 3. AI 计算下一步
        next_move = self._calculate_next_move(board_state)

        # 4. 在原图上绘制推荐落子点
        if next_move:
            frame = self._draw_move_on_frame(
                frame, next_move, self.recognizer.last_transform, warped_board.shape
            )

        return frame

    def _extract_board(self, frame):
        """兼容旧接口：透视矫正棋盘"""
        return self.recognizer.extract_board(frame)

    def _recognize_stones(self, warped_board):
        """兼容旧接口：识别棋子状态"""
        return self.recognizer.recognize_stones(warped_board)

    def _board_to_string(self, board_state):
        """将 15x15 矩阵翻译成带有坐标系的字符画，喂给 LLM"""
        char_map = {self.EMPTY: "+", self.BLACK: "X", self.WHITE: "O"}
        col_header = "   " + " ".join([f"{c:2}" for c in range(self.board_size)]) + "\n"
        board_str = col_header
        for r in range(self.board_size):
            row_chars = [char_map[board_state[r][c]] for c in range(self.board_size)]
            board_str += f"{r:2}  " + "  ".join(row_chars) + "\n"
        return board_str



    def _calculate_next_move(self, board_state):
        """候选点生成 + 启发式评估"""
        ai_color = self.WHITE
        player_color = self.BLACK

        candidates = self._get_candidates(board_state)
        if not candidates:
            return (7, 7) if board_state[7][7] == self.EMPTY else (7, 8)

        best_score = -float("inf")
        best_move = None
        for (r, c) in candidates:
            attack_score = self._evaluate_direction(board_state, r, c, ai_color)
            defense_score = self._evaluate_direction(board_state, r, c, player_color)
            total_score = attack_score + defense_score * 1.2
            if total_score > best_score:
                best_score = total_score
                best_move = (r, c)
        return best_move

    def _get_candidates(self, board_state):
        candidates = set()
        radius = 2
        for r in range(self.board_size):
            for c in range(self.board_size):
                if board_state[r][c] != self.EMPTY:
                    for dr in range(-radius, radius + 1):
                        for dc in range(-radius, radius + 1):
                            nr, nc = r + dr, c + dc
                            if 0 <= nr < self.board_size and 0 <= nc < self.board_size:
                                if board_state[nr][nc] == self.EMPTY:
                                    candidates.add((nr, nc))
        return list(candidates)

    def _evaluate_direction(self, board_state, r, c, color):
        directions = [(0, 1), (1, 0), (1, 1), (1, -1)]
        total_score = 0
        for dr, dc in directions:
            count = 1
            left_blocked = False
            right_blocked = False

            i, j = r + dr, c + dc
            while 0 <= i < self.board_size and 0 <= j < self.board_size:
                if board_state[i][j] == color:
                    count += 1
                elif board_state[i][j] == self.EMPTY:
                    break
                else:
                    right_blocked = True
                    break
                i += dr
                j += dc
            if i < 0 or i >= self.board_size or j < 0 or j >= self.board_size:
                right_blocked = True

            i, j = r - dr, c - dc
            while 0 <= i < self.board_size and 0 <= j < self.board_size:
                if board_state[i][j] == color:
                    count += 1
                elif board_state[i][j] == self.EMPTY:
                    break
                else:
                    left_blocked = True
                    break
                i -= dr
                j -= dc
            if i < 0 or i >= self.board_size or j < 0 or j >= self.board_size:
                left_blocked = True

            blocks = int(left_blocked) + int(right_blocked)
            if count >= 5:
                total_score += 1_000_000
            elif count == 4:
                total_score += 100_000 if blocks == 0 else 10_000
            elif count == 3:
                total_score += 10_000 if blocks == 0 else 1_000
            elif count == 2:
                total_score += 100 if blocks == 0 else 10

        return total_score

    def _draw_move_on_frame(self, frame, next_move, transform_matrix, warped_shape):
        row, col = next_move
        size = warped_shape[0]
        # A Gomoku stone lies on a grid intersection, including both
        # endpoints, rather than at the centre of a grid cell.
        cell_size = (size - 1) / (self.board_size - 1)
        warped_x = col * cell_size
        warped_y = row * cell_size

        M_inv = np.linalg.inv(transform_matrix)
        point = np.array([[[warped_x, warped_y]]], dtype=np.float32)
        original_point = cv2.perspectiveTransform(point, M_inv)
        center = (int(original_point[0][0][0]), int(original_point[0][0][1]))

        cv2.circle(frame, center, 20, (0, 0, 255), 3)
        cv2.putText(frame, "AI Suggestion", (center[0] - 50, center[1] - 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        return frame
