"""Recover the wall plane from its grid of bolt holes, so distances can be measured on the wall instead of in the picture.

Assumptions, stated wherever a result is shown:
- the bolt holes form a square grid, straight or diagonal, on one flat face of the wall;
- pixels are square and the lens center is the middle of the picture;
- the fit describes the one face it was found on, and nothing off that plane.
The fit abstains when too few holes agree. It does not know the grid's real spacing, so it corrects relative
distances only; absolute size still comes from the climber or a marked scale line.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Sequence

import cv2
import numpy as np

GRID_VERSION = "bolt-grid-v2"
MIN_HOLE_CONTRAST = 14            # gray levels darker than the surrounding wall, for the relative settings below
# How much darker than the wall around it a dot must be, as a share of that wall's brightness. None is the original
# rule (an automatic threshold with an 18-level floor). Several settings are tried because the right one depends on
# how much wall texture the picture shows, which changes with exposure and with the video conversion.
DETECTION_SETTINGS: tuple[float | None, ...] = (None, 0.2, 0.25, 0.3)
MIN_INLIERS = 30
MAX_MEDIAN_RESIDUAL_PX = 2.0
RANSAC_PX = 3.0
STEP_TOLERANCE = 0.3              # a neighbor must lie within this share of a grid step of where it is expected
MIN_SPACING_PX, MAX_SPACING_PX = 8.0, 90.0
MAX_BASIS_DOTS = 500              # dots nearest the focus used to estimate the grid step
BASIS_BIN_PX = 2.0
NEAR_FACE_STEPS = 3                # how far past the fitted area a point still counts as on the same face


def detect_bolts(image_bgr: np.ndarray, relative: float | None = None) -> np.ndarray:
    """Centers of small dark round dots. Many are not bolt holes; the grid fit decides which belong.

    With `relative`, a dot must be darker than the wall around it by at least that share of the wall's brightness.
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    size = max(5, int(width * 0.012) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    dark = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)
    if relative is None:
        _, mask = cv2.threshold(dark, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        mask[dark < 18] = 0
    else:
        around = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel).astype(np.float32)
        mask = ((dark >= relative * np.maximum(around, 1.0)) & (dark >= MIN_HOLE_CONTRAST)).astype(np.uint8) * 255
    count, _, stats, centers = cv2.connectedComponentsWithStats(mask, connectivity=8)
    limit = (size * 0.9) ** 2
    keep = [i for i in range(1, count) if 2 <= stats[i, cv2.CC_STAT_AREA] <= limit
            and max(stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]) <= 2.2 * min(stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]) + 1]
    return centers[keep].astype(np.float64)


def fit_image(image_bgr: np.ndarray, width: int, height: int, focus: Sequence[float] | None = None) -> dict[str, Any]:
    """The bolt grid of a wall picture: the accepted fit with the most bolt holes over several detection settings.

    Every setting must pass the same acceptance rules in `fit_grid`, so trying several cannot loosen them.
    """
    best: dict[str, Any] | None = None
    for setting in DETECTION_SETTINGS:
        fit = fit_grid(detect_bolts(image_bgr, setting), width, height, focus)
        fit["detection"] = "automatic threshold" if setting is None else f"{setting:.2f} of the surrounding brightness"
        if best is None or (fit["status"] == "ok" and (best["status"] != "ok" or fit["inliers"] > best["inliers"])):
            best = fit
    return best


def _local_basis(points: np.ndarray, center: np.ndarray, radius: float) -> tuple[np.ndarray, np.ndarray] | None:
    """The two shortest well-supported, non-parallel steps between neighboring dots around `center`.

    Steps are counted in a 2 px histogram, so the cost stays small even where speckle produces thousands of dots.
    """
    distance = np.linalg.norm(points - center, axis=1)
    near = points[np.argsort(distance)[:MAX_BASIS_DOTS]]
    near = near[np.linalg.norm(near - center, axis=1) <= radius]
    if len(near) < 12:
        return None
    steps = (near[None, :, :] - near[:, None, :]).reshape(-1, 2)
    length = np.linalg.norm(steps, axis=1)
    steps = steps[(length >= MIN_SPACING_PX) & (length <= MAX_SPACING_PX)]
    steps = steps[(steps[:, 0] > 0) | ((steps[:, 0] == 0) & (steps[:, 1] > 0))]        # a step and its reverse are the same step
    if len(steps) < 20:
        return None
    bins = int(MAX_SPACING_PX // BASIS_BIN_PX) + 1
    histogram, _, _ = np.histogram2d(steps[:, 0], steps[:, 1], bins=(bins, 2 * bins), range=((0, bins * BASIS_BIN_PX), (-bins * BASIS_BIN_PX, bins * BASIS_BIN_PX)))
    support = cv2.blur(histogram.astype(np.float32), (3, 3), borderType=cv2.BORDER_CONSTANT) * 9
    threshold = max(4.0, 0.35 * float(support.max()))
    xs, ys = np.nonzero(support >= threshold)
    centers = np.column_stack([(xs + 0.5) * BASIS_BIN_PX, (ys + 0.5) * BASIS_BIN_PX - bins * BASIS_BIN_PX])
    if not len(centers):
        return None
    order = np.argsort(np.linalg.norm(centers, axis=1))

    def refine(v: np.ndarray) -> np.ndarray:
        members = steps[np.linalg.norm(steps - v, axis=1) <= 0.12 * np.linalg.norm(v) + 1.0]
        return members.mean(axis=0) if len(members) else v

    first = refine(centers[order[0]])
    for index in order[1:]:
        candidate = centers[index]
        if abs(float(first @ candidate)) / (np.linalg.norm(first) * np.linalg.norm(candidate)) < 0.75:
            return first, refine(candidate)
    return None


def _grow(points: np.ndarray, start: int, basis: tuple[np.ndarray, np.ndarray]) -> dict[int, tuple[int, int]]:
    """Give dots integer grid positions by stepping outward, letting the step size drift as perspective changes it."""
    assigned = {start: (0, 0)}
    taken = {(0, 0)}
    local = {start: basis}
    queue = deque([start])
    while queue:
        index = queue.popleft()
        i, j = assigned[index]
        b1, b2 = local[index]
        for step, (di, dj) in ((b1, (1, 0)), (-b1, (-1, 0)), (b2, (0, 1)), (-b2, (0, -1))):
            target = (i + di, j + dj)
            if target in taken:
                continue
            distance = np.linalg.norm(points - (points[index] + step), axis=1)
            nearest = int(np.argmin(distance))
            if nearest in assigned or distance[nearest] > STEP_TOLERANCE * np.linalg.norm(step):
                continue
            found = points[nearest] - points[index]
            assigned[nearest] = target
            taken.add(target)
            local[nearest] = (np.sign(di) * found if di else b1, np.sign(dj) * found if dj else b2)
            queue.append(nearest)
    return assigned


def fit_grid(points: np.ndarray, width: int, height: int, focus: Sequence[float] | None = None) -> dict[str, Any]:
    """Fit one grid to the dots, starting near `focus` (picture coordinates) or wherever dots are densest."""
    failed = lambda reason: {"status": "not_found", "reason": reason, "method": GRID_VERSION, "dots_detected": int(len(points))}
    if len(points) < MIN_INLIERS:
        return failed("Too few bolt holes were visible to fit a grid.")
    radius = 0.22 * max(width, height)
    has_focus = focus is not None
    if focus is None:
        sample = points[:: max(1, len(points) // 60)]
        focus = sample[int(np.argmax([np.sum(np.linalg.norm(points - p, axis=1) <= radius) for p in sample]))]
    center = np.asarray(focus, float)
    best: dict[str, Any] | None = None
    for attempt_radius in (radius * 0.5, radius, radius * 1.5):
        basis = _local_basis(points, center, attempt_radius)
        if basis is None:
            continue
        for start in np.argsort(np.linalg.norm(points - center, axis=1))[:6]:
            assigned = _grow(points, int(start), basis)
            if len(assigned) < MIN_INLIERS:
                continue
            index = np.array(list(assigned))
            lattice = np.array([assigned[i] for i in index], np.float64)
            matrix, inliers = cv2.findHomography(lattice, points[index], cv2.RANSAC, RANSAC_PX)
            if matrix is None:
                continue
            kept = inliers.ravel() == 1
            projected = cv2.perspectiveTransform(lattice[kept].reshape(-1, 1, 2), matrix).reshape(-1, 2)
            residual = float(np.median(np.linalg.norm(projected - points[index][kept], axis=1)))
            if has_focus:      # the grid must be the one on the wall face around the focus, not a neighboring face
                reach = cv2.pointPolygonTest(cv2.convexHull(points[index][kept].astype(np.float32)), (float(center[0]), float(center[1])), True)
                if reach < -2 * float(np.linalg.norm(basis[0])):
                    continue
            if kept.sum() >= MIN_INLIERS and residual <= MAX_MEDIAN_RESIDUAL_PX and (best is None or kept.sum() > best["inliers"]):
                best = {"matrix": matrix, "inliers": int(kept.sum()), "residual": residual, "points": points[index][kept], "lattice": lattice[kept]}
        if best:
            break
    if best is None:
        return failed("The dots found did not agree on one regular grid. The wall may have several faces here, or too few holes are visible.")
    # Drop agreeing dots that sit far from all the others, such as one on the floor, so they do not stretch the fitted area.
    kept_points = best["points"]
    gaps = np.array([np.sort(np.linalg.norm(kept_points - p, axis=1))[1] for p in kept_points])
    kept_points = kept_points[gaps <= 2.5 * np.median(gaps)]
    return {"status": "ok", "method": GRID_VERSION, "dots_detected": int(len(points)), "inliers": int(len(kept_points)), "median_residual_px": round(best["residual"], 2),
            "matrix": best["matrix"].tolist(), "grid_points": np.round(kept_points, 1).tolist(), "spacing_px": round(float(np.median(gaps)), 1),
            "dots": np.round(points, 1).tolist(), "hull": cv2.convexHull(kept_points.astype(np.float32)).reshape(-1, 2).round(1).tolist()}


class WallPlane:
    """Maps picture positions onto the wall plane, in grid steps. Only relative distances are meaningful."""

    def __init__(self, fit: dict[str, Any], width: int, height: int):
        self.width, self.height = width, height
        self.to_image = np.array(fit["matrix"], float)
        self.to_plane = np.linalg.inv(self.to_image)
        self.hull = np.array(fit["hull"], np.float32)
        self.spacing = float(fit["spacing_px"])
        self.dots = np.array(fit.get("dots", []), np.float64).reshape(-1, 2)
        # The fitted grid's own axes can point any way. Turn plane coordinates so that right and down in the picture are
        # right and down on the plane, because the planner reads "below", "left of", and "upright" from them.
        center = self.hull.reshape(-1, 2).mean(axis=0).astype(np.float64) if len(self.hull) else np.array([width / 2, height / 2])
        a, b, c = self._lattice([center, center + [1, 0], center + [0, 1]])
        u, _, vt = np.linalg.svd(np.column_stack([b - a, c - a]))
        self.turn = (u @ vt).T                      # nearest pure rotation or mirror; distances are unchanged

    def _lattice(self, points_px: Sequence[Sequence[float]]) -> np.ndarray:
        """Positions in the fitted grid's own steps and axes."""
        points = np.asarray(points_px, np.float64).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(points, self.to_plane).reshape(-1, 2)

    def plane(self, points_px: Sequence[Sequence[float]]) -> np.ndarray:
        """Positions on the wall plane in grid steps, turned to match the picture: x to the right, y downward."""
        return self._lattice(points_px) @ self.turn.T

    def image(self, points_plane: Sequence[Sequence[float]]) -> np.ndarray:
        """Picture pixels for positions given by `plane`."""
        points = (np.asarray(points_plane, np.float64).reshape(-1, 2) @ self.turn).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(points, self.to_image).reshape(-1, 2)

    def covers(self, point_px: Sequence[float]) -> bool:
        """Whether a picture point can be shown to lie on the wall face the grid was fitted to.

        True inside the fitted area or within a few grid steps of it. Farther out, true only if most bolt holes around
        the point follow the same grid. Without that evidence the answer is no: on real walls, texture on the holds
        produced stray dots, so a lack of agreement could not tell another face from the same face with hidden holes.
        """
        point = (float(point_px[0]), float(point_px[1]))
        if cv2.pointPolygonTest(self.hull, point, True) >= -NEAR_FACE_STEPS * self.spacing:
            return True
        near = self.dots[np.linalg.norm(self.dots - point, axis=1) <= 4 * self.spacing] if len(self.dots) else np.empty((0, 2))
        if len(near) < 8:
            return False
        lattice = self._lattice(near)
        return float(np.mean(np.linalg.norm(lattice - np.round(lattice), axis=1) <= 0.2)) >= 0.6

    def local_scale(self, point_px: Sequence[float]) -> float:
        """Grid steps per pixel around a point: how much the picture shrinks the wall there."""
        p = np.asarray(point_px, float)
        a, b, c = self.plane([p, p + [1, 0], p + [0, 1]])
        return float(np.sqrt(abs(np.linalg.det(np.array([b - a, c - a])))))

    def tilt(self) -> dict[str, Any]:
        """Angle between the wall and the camera's picture plane, from the grid's perspective. None when it cannot be told."""
        shift = np.array([[1, 0, -self.width / 2], [0, 1, -self.height / 2], [0, 0, 1]], float)
        h = shift @ self.to_image
        h1, h2 = h[:, 0], h[:, 1]
        estimates = []
        denominator = h1[2] * h2[2]
        if abs(denominator) > 1e-12:
            estimates.append(-(h1[0] * h2[0] + h1[1] * h2[1]) / denominator)
        denominator = h1[2] ** 2 - h2[2] ** 2
        if abs(denominator) > 1e-12:
            estimates.append((h2[0] ** 2 + h2[1] ** 2 - h1[0] ** 2 - h1[1] ** 2) / denominator)
        estimates = [e for e in estimates if e > 0]
        if not estimates:
            return {"status": "unknown", "reason": "The grid shows too little perspective to tell the wall's angle, which happens when the wall faces the camera squarely."}
        focal = float(np.sqrt(np.median(estimates)))
        if not 0.4 * max(self.width, self.height) <= focal <= 6 * max(self.width, self.height):
            return {"status": "unknown", "reason": "The grid's perspective did not give a believable lens estimate, so the wall's angle is not reported."}
        k_inverse = np.diag([1 / focal, 1 / focal, 1.0])
        r1, r2 = k_inverse @ h1, k_inverse @ h2
        normal = np.cross(r1 / np.linalg.norm(r1), r2 / np.linalg.norm(r2))
        normal /= np.linalg.norm(normal)
        if normal[2] > 0:
            normal = -normal                       # make the wall's normal point back toward the camera
        total = float(np.degrees(np.arccos(np.clip(-normal[2], -1, 1))))
        # Image y grows downward. A normal pointing down in the picture means the top of the wall leans toward the camera.
        vertical = float(np.degrees(np.arctan2(normal[1], -normal[2])))
        sideways = float(np.degrees(np.arctan2(normal[0], -normal[2])))
        return {"status": "ok", "angle_to_camera_deg": round(total, 1), "top_toward_camera_deg": round(vertical, 1), "turned_sideways_deg": round(sideways, 1),
                "focal_px": round(focal), "note": "Measured relative to the camera, not to gravity. It equals the wall's overhang only if the camera was held level and upright."}


MIN_COVERED_SHARE = 0.8


def correction_for(fit: dict[str, Any], holds: Sequence[dict[str, Any]], width: int, height: int) -> tuple[WallPlane | None, dict[str, Any]]:
    """The wall plane to measure on, if the grid fit can be trusted for these holds, and a summary to show the climber."""
    if fit["status"] != "ok":
        return None, {"applied": False, "reason": fit["reason"]}
    plane = WallPlane(fit, width, height)
    centers = [(h["x"] * width, h["y"] * height) for h in holds]
    covered = [plane.covers(c) for c in centers]
    summary = {"bolts_used": fit["inliers"], "median_residual_px": fit["median_residual_px"], "tilt": plane.tilt(), "holds_on_fitted_face": int(sum(covered)), "holds": len(holds),
               "assumption": "Assumes the bolt holes form a square grid on one flat wall face. Holds on volumes or on another face are not corrected properly."}
    if not centers or sum(covered) < MIN_COVERED_SHARE * len(centers):
        return None, {**summary, "applied": False,
                      "reason": f"Only {sum(covered)} of {len(centers)} holds lie on the wall face where the bolt grid was fitted, so distances were left as they appear in the picture."}
    scales = [plane.local_scale(c) for c, ok in zip(centers, covered) if ok]
    return plane, {**summary, "applied": True, "scale_change": round(max(scales) / min(scales), 3),
                   "detail": f"Distances are measured on the wall plane, fitted from {fit['inliers']} bolt holes. Across your holds, the picture shrinks the wall by up to "
                             f"{(max(scales) / min(scales) - 1) * 100:.0f}% in the farthest part compared with the nearest."}
