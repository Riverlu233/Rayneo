"""Generate four printable ArUco markers for the Gomoku-board demo.

Default layout IDs are::

    0 -------- 1
    |  board   |
    3 -------- 2

Print each ``tag_<id>.png`` without scaling distortion.  The black square
should be 6--8 cm wide, with the surrounding white margin preserved.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


TAG_IDS = (0, 1, 2, 3)
A4_WIDTH_PX = 2480   # A4 width at 300 DPI
A4_HEIGHT_PX = 3508  # A4 height at 300 DPI


def marker_image(dictionary, marker_id: int, side_pixels: int) -> np.ndarray:
    """Support both current and older OpenCV ArUco APIs."""
    if hasattr(cv2.aruco, "generateImageMarker"):
        return cv2.aruco.generateImageMarker(dictionary, marker_id, side_pixels)
    image = np.zeros((side_pixels, side_pixels), dtype=np.uint8)
    cv2.aruco.drawMarker(dictionary, marker_id, side_pixels, image, 1)
    return image


def printable_page(marker: np.ndarray, marker_id: int, margin_pixels: int) -> np.ndarray:
    page = cv2.copyMakeBorder(
        marker,
        margin_pixels,
        margin_pixels,
        margin_pixels,
        margin_pixels,
        cv2.BORDER_CONSTANT,
        value=255,
    )
    page = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    cv2.putText(
        page,
        f"ArUco 4x4_50 / ID {marker_id}",
        (margin_pixels, page.shape[0] - max(12, margin_pixels // 3)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 0, 0),
        2,
        cv2.LINE_AA,
    )
    return page


def a4_print_page(dictionary, marker_id: int, tag_side_mm: float) -> np.ndarray:
    """Create a whole A4 PNG, so no printer-side sizing option is needed."""
    pixels_per_mm = 300 / 25.4
    tag_side_px = round(tag_side_mm * pixels_per_mm)
    marker = marker_image(dictionary, marker_id, tag_side_px)
    page = np.full((A4_HEIGHT_PX, A4_WIDTH_PX), 255, dtype=np.uint8)
    top = (A4_HEIGHT_PX - tag_side_px) // 2 - 120
    left = (A4_WIDTH_PX - tag_side_px) // 2
    page[top:top + tag_side_px, left:left + tag_side_px] = marker
    page = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    cv2.putText(
        page,
        f"ArUco DICT_4X4_50  |  ID {marker_id}  |  black square: {tag_side_mm:.0f} mm",
        (max(60, left - 120), top + tag_side_px + 180),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.05,
        (0, 0, 0),
        3,
        cv2.LINE_AA,
    )
    return page


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("aruco_tags"))
    parser.add_argument(
        "--marker-pixels",
        type=int,
        default=1200,
        help="black marker width in pixels before printing (default: 1200)",
    )
    parser.add_argument(
        "--margin-pixels",
        type=int,
        default=300,
        help="white border width in pixels (default: 300)",
    )
    parser.add_argument(
        "--tag-side-mm",
        type=float,
        default=60.0,
        help="black Tag width on the ready-to-print A4 pages (default: 60 mm)",
    )
    args = parser.parse_args()
    if args.marker_pixels < 200 or args.margin_pixels < 50:
        raise ValueError("Use at least 200 marker pixels and 50 margin pixels.")

    args.output.mkdir(parents=True, exist_ok=True)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)

    pages = []
    for marker_id in TAG_IDS:
        page = printable_page(
            marker_image(dictionary, marker_id, args.marker_pixels),
            marker_id,
            args.margin_pixels,
        )
        output_path = args.output / f"tag_{marker_id}.png"
        cv2.imwrite(str(output_path), page)
        a4_path = args.output / f"A4_tag_{marker_id}_{round(args.tag_side_mm)}mm.png"
        cv2.imwrite(str(a4_path), a4_print_page(dictionary, marker_id, args.tag_side_mm))
        pages.append(page)
        print(f"Wrote {output_path}")
        print(f"Wrote {a4_path}")

    preview = np.vstack((np.hstack((pages[0], pages[1])), np.hstack((pages[3], pages[2]))))
    preview_path = args.output / "layout_preview_0_1_3_2.png"
    cv2.imwrite(str(preview_path), preview)
    print(f"Wrote {preview_path}")
    print("Board-corner layout: top-left=0, top-right=1, bottom-right=2, bottom-left=3")


if __name__ == "__main__":
    main()
