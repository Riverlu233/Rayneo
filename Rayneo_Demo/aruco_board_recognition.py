"""Fast board recognition for the tagged physical Gomoku-board demo.

The four ArUco markers replace the unreliable corner-detector model only for
this demo setup.  Their inner corners define the four outer grid
intersections, allowing a deterministic perspective rectification.  The
existing X1 YOLO model then recognises stones on a *pure grayscale* warped
board at the model's native 640-pixel inference size.
"""

from pathlib import Path
import time

import cv2
import numpy as np
import torch


class GomokuBoardRecognizer:
    """ArUco rectification + X1 stone recognition, API-compatible with legacy."""

    REQUIRED_IDS = (0, 1, 2, 3)  # top-left, top-right, bottom-right, bottom-left

    def __init__(
        self,
        board_size=15,
        warp_size=960,
        weights_path=None,
        marker_dictionary=cv2.aruco.DICT_4X4_50,
        sharpness_thresh=8.0,
    ):
        self.board_size = board_size
        self.warp_size = warp_size
        self.sharpness_thresh = sharpness_thresh
        self.last_transform = None
        self.last_board_corners = None
        self.last_tag_corners = {}
        # A short white-stone hold removes single-frame YOLO flicker without
        # permanently retaining a bad detection when the board is changed.
        self._white_hold = np.zeros((board_size, board_size), dtype=np.uint8)
        self._last_status_log = 0.0
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"

        dictionary = cv2.aruco.getPredefinedDictionary(marker_dictionary)
        parameters = cv2.aruco.DetectorParameters()
        self.detector = cv2.aruco.ArucoDetector(dictionary, parameters)

        if weights_path is None:
            weights_path = Path(__file__).resolve().parents[1] / "trained_networks" / "GO_PIECEX1.pt"
        self.weights_path = str(weights_path)
        self.model = None
        print(f"[*] Initializing ArUco + X1 recognizer ({self.device}): {self.weights_path}")
        try:
            self.model = torch.hub.load(
                "ultralytics/yolov5", "custom", path=self.weights_path,
                device=self.device, force_reload=False,
            )
            self.model.conf = 0.25
            self.model.iou = 0.45
            dummy = np.zeros((self.warp_size, self.warp_size, 3), dtype=np.uint8)
            self.model(dummy, size=640)
            if self.device.startswith("cuda"):
                torch.cuda.synchronize()
            print("[*] ArUco + X1 recognizer ready (X1 inference size: 640).")
        except Exception as exc:
            print(f"[!] X1 model load failed: {exc}")

    def _status(self, message):
        now = time.monotonic()
        if now - self._last_status_log >= 1.0:
            print(message)
            self._last_status_log = now

    def _detect_board_corners(self, frame):
        """Return the four grid intersections in TL, TR, BR, BL order.

        For every tag we use the code corner closest to the mean of all tag
        centres.  It is rotation-invariant and is the marker corner physically
        aligned to the corresponding board-grid corner.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        tag_quads, ids, _ = self.detector.detectMarkers(gray)
        self.last_tag_corners = {}
        if ids is None:
            self._status("  ├─ [ArUco] no markers detected (need IDs 0,1,2,3)")
            return None

        for quad, marker_id in zip(tag_quads, ids.flatten()):
            marker_id = int(marker_id)
            if marker_id in self.REQUIRED_IDS:
                self.last_tag_corners[marker_id] = quad.reshape(4, 2).astype(np.float32)

        missing = [str(marker_id) for marker_id in self.REQUIRED_IDS if marker_id not in self.last_tag_corners]
        if missing:
            self._status(f"  ├─ [ArUco] missing IDs: {', '.join(missing)}")
            return None

        centres = np.array([quad.mean(axis=0) for quad in self.last_tag_corners.values()])
        board_centre = centres.mean(axis=0)
        corners = np.array([
            quad[np.argmin(np.sum((quad - board_centre) ** 2, axis=1))]
            for marker_id in self.REQUIRED_IDS
            for quad in [self.last_tag_corners[marker_id]]
        ], dtype=np.float32)

        if not cv2.isContourConvex(corners.reshape(-1, 1, 2)):
            self._status("  ├─ [ArUco] invalid marker geometry; check IDs/placement")
            return None
        if abs(cv2.contourArea(corners.reshape(-1, 1, 2))) < frame.shape[0] * frame.shape[1] * 0.01:
            self._status("  ├─ [ArUco] board area is too small")
            return None
        return corners

    def extract_board(self, frame):
        start = time.perf_counter()
        if cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var() < self.sharpness_thresh:
            self._status("  ├─ [ArUco] frame too blurred; skipped")
            return None

        corners = self._detect_board_corners(frame)
        if corners is None:
            self.last_transform = None
            self.last_board_corners = None
            return None

        side = self.warp_size - 1
        target = np.array([[0, 0], [side, 0], [side, side], [0, side]], dtype=np.float32)
        self.last_transform = cv2.getPerspectiveTransform(corners, target)
        self.last_board_corners = corners
        warped = cv2.warpPerspective(frame, self.last_transform, (self.warp_size, self.warp_size))
        print(f"  ├─ [ArUco] 4 tags + perspective warp: {(time.perf_counter() - start) * 1000:.1f}ms")
        return warped

    @staticmethod
    def _grayscale_bgr(image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    def recognize_stones(self, warped_bgr):
        if self.model is None or warped_bgr is None:
            return np.zeros((self.board_size, self.board_size), dtype=np.uint8)

        start = time.perf_counter()
        gray_bgr = self._grayscale_bgr(warped_bgr)
        model_input = cv2.cvtColor(gray_bgr, cv2.COLOR_BGR2RGB)
        prepared = time.perf_counter()
        results = self.model(model_input, size=640)
        if self.device.startswith("cuda"):
            torch.cuda.synchronize()
        inferred = time.perf_counter()
        detections = results.pandas().xyxy[0]
        parsed = time.perf_counter()

        board = np.zeros((self.board_size, self.board_size), dtype=np.uint8)
        best_confidence = np.full((self.board_size, self.board_size), -np.inf, dtype=np.float32)
        spacing = (self.warp_size - 1) / (self.board_size - 1)
        for row in detections.itertuples():
            name = str(row.name).lower()
            if name not in ("black", "white"):
                continue
            x = (float(row.xmin) + float(row.xmax)) / 2.0
            y = (float(row.ymin) + float(row.ymax)) / 2.0
            col = int(round(x / spacing))
            grid_row = int(round(y / spacing))
            confidence = float(row.confidence)
            if 0 <= grid_row < self.board_size and 0 <= col < self.board_size and confidence > best_confidence[grid_row, col]:
                board[grid_row, col] = 1 if name == "black" else 2
                best_confidence[grid_row, col] = confidence

        # X1 was trained mainly on Go-board imagery.  On this yellow physical
        # board its black class is the weak one: neighbouring dark stones and
        # grid lines often suppress one another in YOLO NMS.  The ArUco warp
        # gives us known intersections, so use a conservative local-darkness
        # probe only to restore *missing* black stones.  Existing YOLO white
        # and black decisions always take priority.
        black_added, dark_scores = self._fill_missing_black_stones(warped_bgr, board)
        white_held = self._hold_white_stones(board)

        print(
            "  ├─ [YOLO X1] "
            f"grayscale: {(prepared - start) * 1000:.1f}ms | "
            f"model@640: {(inferred - prepared) * 1000:.1f}ms | "
            f"dataframe: {(parsed - inferred) * 1000:.1f}ms | "
            f"mapping: {(time.perf_counter() - parsed) * 1000:.1f}ms | "
            f"black={int((board == 1).sum())} (+CV {black_added}), "
            f"white={int((board == 2).sum())} (held {white_held}) | "
            f"dark-score range={min(dark_scores):.2f}-{max(dark_scores):.2f}"
        )
        return board

    def _hold_white_stones(self, board, hold_frames=2):
        """Keep a confirmed white stone through a brief one-frame dropout."""
        held = 0
        for row in range(self.board_size):
            for col in range(self.board_size):
                if board[row, col] == 2:
                    self._white_hold[row, col] = hold_frames
                elif self._white_hold[row, col] > 0:
                    # A held white has priority over a momentary black false
                    # positive from the black fallback.
                    board[row, col] = 2
                    self._white_hold[row, col] -= 1
                    held += 1
        return held

    def _fill_missing_black_stones(self, warped_bgr, board):
        """Conservatively fill black-YOLO omissions using intersection patches.

        Empty intersections contain only two thin grid lines, whereas a black
        stone fills most of a small central disk with dark pixels.  The
        threshold is derived from the current board image rather than a fixed
        camera exposure.  It intentionally does not attempt to recognise
        white stones, since X1 is already reliable for that class.
        """
        gray = cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2GRAY)
        spacing = (self.warp_size - 1) / (self.board_size - 1)
        radius = max(4, int(round(spacing * 0.23)))
        # Otsu separates the dark-stone/line population from the wooden board
        # under the current illumination.  Keeping it below 145 avoids making
        # a low-contrast wood grain look like a stone.
        otsu_threshold, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        dark_threshold = min(145, max(45, float(otsu_threshold)))
        yy, xx = np.ogrid[-radius:radius + 1, -radius:radius + 1]
        disk = (xx * xx + yy * yy) <= radius * radius

        added = 0
        scores = []
        for grid_row in range(self.board_size):
            for col in range(self.board_size):
                x = int(round(col * spacing))
                y = int(round(grid_row * spacing))
                patch = gray[max(0, y - radius):y + radius + 1, max(0, x - radius):x + radius + 1]
                mask = disk[
                    max(0, radius - y):radius + 1 + min(radius, gray.shape[0] - 1 - y),
                    max(0, radius - x):radius + 1 + min(radius, gray.shape[1] - 1 - x),
                ]
                dark_fraction = float(np.mean(patch[mask] < dark_threshold)) if patch.size else 0.0
                scores.append(dark_fraction)
                # At an empty crossing this is normally below 0.20; a black
                # stone is typically above 0.75.  0.62 leaves a safety margin.
                if board[grid_row, col] == 0 and dark_fraction >= 0.62:
                    board[grid_row, col] = 1
                    added += 1
        return added, scores

    def draw_debug_overlay(self, frame):
        """Draw marker and inferred-board geometry in-place for live debugging."""
        for marker_id, quad in self.last_tag_corners.items():
            cv2.polylines(frame, [quad.astype(np.int32)], True, (0, 255, 255), 2)
            centre = tuple(np.mean(quad, axis=0).astype(int))
            cv2.putText(frame, f"Tag {marker_id}", centre, cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        if self.last_board_corners is not None:
            cv2.polylines(frame, [self.last_board_corners.astype(np.int32)], True, (0, 255, 0), 2)
            cv2.putText(frame, "ArUco board locked", (35, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        else:
            cv2.putText(frame, "Need ArUco tags: 0, 1, 2, 3", (35, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        return frame
