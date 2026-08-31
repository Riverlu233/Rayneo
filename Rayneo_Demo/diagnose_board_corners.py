"""Offline corner-localization comparison for real-board photos.

This script does not affect the live receiver.  It writes annotated candidate
quadrilaterals and their perspective warps, so a method can be chosen from
actual glasses/phone samples before it is put in board_recognition.py.
"""

from pathlib import Path
import argparse

import cv2
import numpy as np


def order_points(points: np.ndarray) -> np.ndarray:
    points = points.astype(np.float32)
    ordered = np.zeros((4, 2), dtype=np.float32)
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1).ravel()
    ordered[0] = points[np.argmin(sums)]
    ordered[2] = points[np.argmax(sums)]
    ordered[1] = points[np.argmin(diffs)]
    ordered[3] = points[np.argmax(diffs)]
    return ordered


def valid_quad(points: np.ndarray, image_shape: tuple[int, int, int]) -> bool:
    area = abs(cv2.contourArea(points.reshape(-1, 1, 2).astype(np.float32)))
    return area >= image_shape[0] * image_shape[1] * 0.08


def contour_quads(mask: np.ndarray, image_shape: tuple[int, int, int]):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:20]:
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            quad = order_points(approx.reshape(4, 2))
            if valid_quad(quad, image_shape):
                candidates.append(quad)
    return candidates


def yellow_mask(frame: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # Broad wood/yellow board range.  Closing connects grid-line gaps without
    # using a crop; unrelated yellow regions remain separate contours.
    mask = cv2.inRange(hsv, (12, 45, 70), (48, 255, 255))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)


def edge_mask(frame: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 35, 110)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    return cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)


def draw_and_warp(frame: np.ndarray, quad: np.ndarray, label: str, output_dir: Path):
    annotated = frame.copy()
    polygon = quad.astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(annotated, [polygon], True, (0, 0, 255), 4)
    for index, point in enumerate(quad.astype(np.int32), start=1):
        cv2.circle(annotated, tuple(point), 10, (0, 0, 255), -1)
        cv2.putText(annotated, str(index), tuple(point + np.array([12, -12])),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 255), 2)
    target = np.float32([[0, 0], [959, 0], [959, 959], [0, 959]])
    matrix = cv2.getPerspectiveTransform(quad, target)
    warp = cv2.warpPerspective(frame, matrix, (960, 960))
    cv2.imwrite(str(output_dir / f"{label}_corners.png"), annotated)
    cv2.imwrite(str(output_dir / f"{label}_warp.png"), warp)


def process(image_path: Path, output_dir: Path):
    frame = cv2.imread(str(image_path))
    if frame is None:
        raise FileNotFoundError(image_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    methods = {"yellow": yellow_mask(frame), "edges": edge_mask(frame)}
    for name, mask in methods.items():
        cv2.imwrite(str(output_dir / f"{name}_mask.png"), mask)
        candidates = contour_quads(mask, frame.shape)
        if not candidates:
            print(f"{image_path.name}: {name}: no valid quadrilateral")
            continue
        quad = candidates[0]
        print(f"{image_path.name}: {name}: {quad.round(1).tolist()}")
        draw_and_warp(frame, quad, name, output_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path("corner_diagnostics"))
    args = parser.parse_args()
    for image in args.images:
        process(image, args.output / image.stem)
