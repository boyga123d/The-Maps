from __future__ import annotations

import json
import math
import os
import re
import sys
import ctypes
import threading
import time
import traceback
import tkinter as tk
import webbrowser
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import messagebox, ttk
from ctypes import wintypes

import pystray
import requests
from PIL import Image, ImageTk, ImageDraw
import customtkinter as ctk

import islepilot
import localtelemetry

# --- HỆ THỐNG MÀU SẮC & GIAO DIỆN TACTICAL HUD ---
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

HUD_BG = "#0c1015"
HUD_BORDER = "#1a2530"
HUD_BORDER_ACTIVE = "#00d2d3"
CARD_BG = "#131b24"
CARD_BORDER = "#212e3d"
ACCENT_CYAN = "#00d2d3"
ACCENT_GREEN = "#10ac84"
ACCENT_ORANGE = "#ff9f43"
ACCENT_RED = "#ee5253"
ACCENT_YELLOW = "#feca57"
TEXT_MUTED = "#8395a7"

RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
DATA_ROOT = (
    Path(os.environ.get("APPDATA", Path.home())) / "The-Maps"
    if getattr(sys, "frozen", False)
    else RESOURCE_ROOT
)
MAPS_DIR = RESOURCE_ROOT / "maps"
CONFIG_PATH = DATA_ROOT / "config.json"
CONFIG_SV_PATH = DATA_ROOT / "configsv.json"
LOCAL_JSON_PATH = RESOURCE_ROOT / "extracted_foods.json"
LOCAL_JSON_FALLBACK = DATA_ROOT / "extracted_foods.json"

# --- ADD-ONLY: extra Gateway POI overlay (does not replace/modify existing layers) ---
GATEWAY_POI_JSON_PATH = RESOURCE_ROOT / "gateway_pois.json"
GATEWAY_POI_JSON_FALLBACK = DATA_ROOT / "gateway_pois.json"
POI_RADIUS_WORLD_SCALE = 1000.0

APP_ICON_ICO = RESOURCE_ROOT / "assets" / "the_maps.ico"
APP_ICON_PNG = RESOURCE_ROOT / "assets" / "the_maps.png"
YOUTUBE_URL = "https://www.youtube.com/@GlobalDailyHighlights"
DISCORD_URL = "https://discord.gg/XpkRPpDhPU"
APP_VERSION = "2.4.1"

RELEASE_TAG = "2.4.1"
GITHUB_RELEASE_API = "https://api.github.com/repos/boyga123d/The-Maps/releases/latest"
GITHUB_RELEASE_PAGE = "https://github.com/boyga123d/The-Maps/releases/latest"
UPDATE_CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000

HOTKEYS = {
    "Tab": 0x09, "~ (Tilde)": 0xC0, "M": 0x4D,
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
    "Caps Lock": 0x14, "Left Shift": 0xA0, "Left Ctrl": 0xA2, "Left Alt": 0xA4
}

MIN_ZOOM = 1.0
MAX_ZOOM = 10.0
ZOOM_STEP = 1.15
HQ_REDRAW_DELAY_MS = 120
MAX_HISTORY_POINTS = 100

ZONE_LAYERS: tuple[tuple[str, str, str, str], ...] = (
    # ("migrations", "Migration", "zone_migration.png", "#ff9800"),
    ("Nước", "Nước ngọt", "gateway_water.webp", "#09a5e2"),
    ("Khu tuần tra", "Khu tuần tra", "zone_patrol.png", "#ab47bc"),
    ("400OV", "400 Ô", "number.png", "#1674f0"),
    ("600OV", "600 Ô", "number2.png", "#eef106"),
)
POI_COLORS = {
    "sanctuaries": "#2ecc71",
    "migrations": "#ff9800",
    "patrol_zones": "#ab47bc",
    "salt_licks": "#f1da0a",
}
# ADD-ONLY: các POI JSON có toggle riêng trên map, không đụng key/layer ảnh cũ.
POI_ZONE_LAYERS: tuple[tuple[str, str, str, str], ...] = (
    ("poi_sanctuaries", "Sanctuary", "", POI_COLORS["sanctuaries"]),
    ("poi_migrations", "Migration", "", POI_COLORS["migrations"]),
    ("poi_patrol_zones", "Patrol", "", POI_COLORS["patrol_zones"]),
    ("poi_salt", "Salt", "", POI_COLORS["salt_licks"]),
)

MAP_TOGGLE_LAYERS = ZONE_LAYERS + POI_ZONE_LAYERS

@dataclass(frozen=True)
class Position:
    x: float
    y: float
    z: float

TEXT_OFFSET_X = 0
TEXT_OFFSET_Y = 0

MAP_LABELS = [
    ("Delta", Position(70411.0, 206414.0, 0.0), "#f1c40f", 10),
    ("East\nCoast", Position(-142334.0, 680270.0, 0.0), "#f1c40f", 10),
    ("Eastern\nJungle", Position(-104428.0, 406995.0, 0.0), "#f1c40f", 10),
    ("Forks\nPlains", Position(-127526.0, 286377.0, 0.0), "#f1c40f", 10),
    ("Highland", Position(-127032.0, -128740.0, 0.0), "#f1c40f", 10),
    ("Central\nJungle", Position(-41147.0, 65738.0, 0.0), "#f1c40f", 10),
    ("Lagoon", Position(342088.0, -100716.0, 0.0), "#f1c40f", 10),
    ("Mudflats", Position(143953.0, -300658.0, 0.0), "#f1c40f", 10),
    ("North\nPlains", Position(-336052.0, 350033.0, 0.0), "#f1c40f", 10),
    ("Northern\nJungle", Position(-306804.0, 175317.0, 0.0), "#f1c40f", 10),
    ("Ridges", Position(-206100.0, -209682.0, 0.0), "#f1c40f", 10),
    ("South Plains", Position(258432.0, -259458.0, 0.0), "#f1c40f", 10),
    ("Swamps", Position(306567.0, 63270.0, 0.0), "#f1c40f", 10),
    ("The Pit", Position(335671.0, -406837.0, 0.0), "#f1c40f", 10),
    ("West Rail", Position(25004.0, -255705.0, 0.0), "#f1c40f", 10),
    ("Water\nAccess", Position(-204161.0, 84988.0, 0.0), "#f1c40f", 10),
]

@dataclass(frozen=True)
class MapProfile:
    profile_id: str
    name: str
    image_path: Path | None
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    swap_axes: bool = False
    invert_x: bool = False
    invert_y: bool = False
    heading_offset_deg: float = 0.0
    zone_image_paths: dict[str, Path] = field(default_factory=dict)

    def to_normalized(self, position: Position) -> tuple[float, float]:
        if self.swap_axes:
            nx = (position.y - self.min_y) / (self.max_y - self.min_y)
            ny = (position.x - self.min_x) / (self.max_x - self.min_x)
        else:
            nx = (position.x - self.min_x) / (self.max_x - self.min_x)
            ny = (position.y - self.min_y) / (self.max_y - self.min_y)
        if self.invert_x: nx = 1.0 - nx
        if self.invert_y: ny = 1.0 - ny
        return nx, ny

    def from_normalized(self, nx: float, ny: float) -> tuple[float, float]:
        if self.invert_x: nx = 1.0 - nx
        if self.invert_y: ny = 1.0 - ny
        if self.swap_axes:
            px = ny * (self.max_x - self.min_x) + self.min_x
            py = nx * (self.max_y - self.min_y) + self.min_y
        else:
            px = nx * (self.max_x - self.min_x) + self.min_x
            py = ny * (self.max_y - self.min_y) + self.min_y
        return px, py

    def transform_yaw(self, yaw_degrees: float) -> float:
        yaw_rad = math.radians(-yaw_degrees)
        world_dx, world_dy = math.cos(yaw_rad), math.sin(yaw_rad)
        if self.swap_axes: screen_dx, screen_dy = world_dy, world_dx
        else: screen_dx, screen_dy = world_dx, world_dy
        if self.invert_x: screen_dx = -screen_dx
        if self.invert_y: screen_dy = -screen_dy
        heading = math.degrees(math.atan2(screen_dx, -screen_dy)) + self.heading_offset_deg
        return heading % 360.0

NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
EVRIMA_PATTERN = re.compile(rf"^\s*({NUMBER})\s*,\s*({NUMBER})\s*,\s*({NUMBER})\s*$")
LEGACY_PATTERN = re.compile(rf"Lat\s*:\s*({NUMBER}).*?Long\s*:\s*({NUMBER}).*?Alt\s*:\s*({NUMBER})", re.IGNORECASE | re.DOTALL)

def parse_coordinate(text: str) -> Position | None:
    match = EVRIMA_PATTERN.match(text.strip()) or LEGACY_PATTERN.search(text)
    if not match: return None
    try: values = [float(value.replace(",", "")) for value in match.groups()]
    except ValueError: return None
    if not all(math.isfinite(value) for value in values): return None
    return Position(*values)

def load_profiles() -> list[MapProfile]:
    profiles: list[MapProfile] = []
    for manifest in sorted(MAPS_DIR.glob("*/map.json")):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            bounds = data["world_bounds"]
            image = manifest.parent / data["image"] if data.get("image") else None
            zone_image_paths = {}
            for key, _label, filename, _color in ZONE_LAYERS:
                zone_file = manifest.parent / filename
                if zone_file.exists(): zone_image_paths[key] = zone_file
            profiles.append(
                MapProfile(
                    profile_id=data["id"], name=data["name"],
                    image_path=image if image and image.exists() else None,
                    min_x=float(bounds["min_x"]), max_x=float(bounds["max_x"]),
                    min_y=float(bounds["min_y"]), max_y=float(bounds["max_y"]),
                    swap_axes=bool(data.get("swap_axes", False)), invert_x=bool(data.get("invert_x", False)),
                    invert_y=bool(data.get("invert_y", False)), heading_offset_deg=float(data.get("heading_offset_deg", 0.0)),
                    zone_image_paths=zone_image_paths,
                )
            )
        except (KeyError, ValueError, TypeError, json.JSONDecodeError): continue
    if not profiles: raise RuntimeError("Không tìm thấy map profile hợp lệ trong thư mục maps.")
    return profiles

def _heading_polygon_points(cx: float, cy: float, heading_deg: float, size: float) -> list[float]:
    theta = math.radians(heading_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    def rotate(local_x: float, local_y: float) -> tuple[float, float]:
        return (cx + cos_t * local_x - sin_t * local_y, cy + sin_t * local_x + cos_t * local_y)
    return [*rotate(0.0, -size), *rotate(-size * 0.62, size * 0.75), *rotate(0.0, size * 0.28), *rotate(size * 0.62, size * 0.75)]

def _draw_heading_polygon(canvas: tk.Canvas, cx: float, cy: float, heading_deg: float, size: float, color: str) -> None:
    canvas.create_polygon(_heading_polygon_points(cx, cy, heading_deg, size), fill=color, outline="#ffffff", width=1.5, joinstyle="round")

def _draw_text_with_outline(canvas: tk.Canvas, x: float, y: float, text: str, font_size: int, fill_color: str, outline_color: str = "#0b0f14") -> None:
    font_spec = ("Segoe UI", font_size, "bold")
    for dx, dy in ((-1,-1), (1,-1), (-1,1), (1,1)):
        canvas.create_text(x+dx, y+dy, text=text, fill=outline_color, font=font_spec, justify="center")
    canvas.create_text(x, y, text=text, fill=fill_color, font=font_spec, justify="center")


def _estimate_text_half_size(text: str, font_size: int) -> tuple[float, float]:
    """Approximate half-width/half-height for centered Segoe UI bold labels."""
    lines = str(text).splitlines() or [""]
    longest = max((len(line) for line in lines), default=1)
    # Slightly conservative dimensions so outlined text stays inside the map.
    half_w = max(4.0, longest * font_size * 0.34 + 3.0)
    half_h = max(4.0, len(lines) * font_size * 0.62 + 3.0)
    return half_w, half_h


def _clamp_text_to_rect(
    x: float,
    y: float,
    text: str,
    font_size: int,
    left: float,
    top: float,
    right: float,
    bottom: float,
    padding: float = 3.0,
) -> tuple[float, float]:
    """Keep the whole centered text label inside a rectangular map viewport."""
    half_w, half_h = _estimate_text_half_size(text, font_size)

    min_x = left + padding + half_w
    max_x = right - padding - half_w
    min_y = top + padding + half_h
    max_y = bottom - padding - half_h

    # Tiny view fallback.
    if min_x > max_x:
        x = (left + right) / 2.0
    else:
        x = max(min_x, min(max_x, x))

    if min_y > max_y:
        y = (top + bottom) / 2.0
    else:
        y = max(min_y, min(max_y, y))

    return x, y


def _clamp_text_to_circle(
    x: float,
    y: float,
    text: str,
    font_size: int,
    cx: float,
    cy: float,
    radius: float,
    padding: float = 4.0,
) -> tuple[float, float]:
    """Keep the whole centered text label within a circular minimap."""
    half_w, half_h = _estimate_text_half_size(text, font_size)

    safe_rx = max(1.0, radius - padding - half_w)
    safe_ry = max(1.0, radius - padding - half_h)

    dx = x - cx
    dy = y - cy
    norm = (dx / safe_rx) ** 2 + (dy / safe_ry) ** 2

    if norm > 1.0:
        scale = 1.0 / math.sqrt(norm)
        dx *= scale
        dy *= scale

    return cx + dx, cy + dy


def _point_in_rect(x, y, rect, margin=0.0):
    left, top, right, bottom = rect
    return left + margin <= x <= right - margin and top + margin <= y <= bottom - margin


def _point_in_circle(x, y, circle, margin=0.0):
    cx, cy, radius = circle
    radius = max(0.0, radius - margin)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2


def _clip_segment_rect(x1, y1, x2, y2, rect):
    left, top, right, bottom = rect
    dx, dy = x2 - x1, y2 - y1
    p = (-dx, dx, -dy, dy)
    q = (x1 - left, right - x1, y1 - top, bottom - y1)
    u1, u2 = 0.0, 1.0

    for pi, qi in zip(p, q):
        if abs(pi) < 1e-12:
            if qi < 0:
                return None
            continue
        t = qi / pi
        if pi < 0:
            if t > u2:
                return None
            u1 = max(u1, t)
        else:
            if t < u1:
                return None
            u2 = min(u2, t)

    return (
        x1 + u1 * dx, y1 + u1 * dy,
        x1 + u2 * dx, y1 + u2 * dy,
    )


def _clip_segment_circle(x1, y1, x2, y2, circle):
    cx, cy, radius = circle
    dx, dy = x2 - x1, y2 - y1
    fx, fy = x1 - cx, y1 - cy
    a = dx * dx + dy * dy

    if a <= 1e-12:
        return (x1, y1, x2, y2) if _point_in_circle(x1, y1, circle) else None

    b = 2.0 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - radius * radius
    disc = b * b - 4.0 * a * c

    ts = [0.0, 1.0]
    if disc >= 0:
        root = math.sqrt(max(0.0, disc))
        for t in ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a)):
            if 0.0 < t < 1.0:
                ts.append(t)

    ts = sorted(set(ts))
    inside = []
    for ta, tb in zip(ts, ts[1:]):
        tm = (ta + tb) / 2.0
        mx, my = x1 + tm * dx, y1 + tm * dy
        if _point_in_circle(mx, my, circle):
            inside.append((ta, tb))

    if not inside:
        return None

    ta, tb = inside[0][0], inside[-1][1]
    return (
        x1 + ta * dx, y1 + ta * dy,
        x1 + tb * dx, y1 + tb * dy,
    )


def _draw_clipped_polyline(canvas, points, *, fill, width, clip_rect=None, clip_circle=None, dash=None):
    if len(points) < 2:
        return

    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        segment = (x1, y1, x2, y2)

        if clip_rect is not None:
            segment = _clip_segment_rect(*segment, clip_rect)
            if segment is None:
                continue

        if clip_circle is not None:
            segment = _clip_segment_circle(*segment, clip_circle)
            if segment is None:
                continue

        canvas.create_line(
            *segment,
            fill=fill,
            width=width,
            capstyle="round",
            joinstyle="round",
            dash=dash,
        )


def _draw_gateway_pois(canvas: tk.Canvas, profile: MapProfile, poi_data: dict, world_to_screen, *, hud: bool = False, visible: dict[str, bool] | None = None, clip_rect=None, clip_circle=None) -> None:
    """Draw ONLY the extra JSON POIs; existing map/layers remain untouched."""
    if not poi_data:
        return

    visible = visible or {}
    show_sanctuaries = visible.get("poi_sanctuaries", True)
    show_migrations = visible.get("poi_migrations", True)
    show_patrol_zones = visible.get("poi_patrol_zones", True)
    show_salt = visible.get("poi_salt", True)

    def pt(x: float, y: float) -> tuple[float, float]:
        return world_to_screen(Position(float(x), float(y), 0.0))

    def point_visible(sx, sy, margin=0.0):
        if clip_rect is not None and not _point_in_rect(sx, sy, clip_rect, margin):
            return False
        if clip_circle is not None and not _point_in_circle(sx, sy, clip_circle, margin):
            return False
        return True

    # Sanctuary: same diamond icon style as Salt, but with its own color.
    if show_sanctuaries:
        sanctuary_color = POI_COLORS["sanctuaries"]
        sanctuary_size = 4 if hud else 6
        for item in poi_data.get("sanctuaries", []):
            sx, sy = pt(item.get("x", 0.0), item.get("y", 0.0))
            if not point_visible(sx, sy, sanctuary_size + 1):
                continue
            canvas.create_polygon(
                sx, sy-sanctuary_size, sx+sanctuary_size, sy,
                sx, sy+sanctuary_size, sx-sanctuary_size, sy,
                fill=sanctuary_color, outline="#2f3640", width=1
            )

    # Migrations: preserve line/path/circle geometry from JSON and obey toggle.
    if show_migrations:
        for item in poi_data.get("migrations", []):
            color = POI_COLORS["migrations"]
            kind = str(item.get("kind", "")).lower()
            polyline = item.get("polyline") or []
            if polyline and kind in {"path", "line"}:
                screen_points = []
                for pair in polyline:
                    if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                        screen_points.append(pt(pair[0], pair[1]))
                _draw_clipped_polyline(
                    canvas, screen_points,
                    fill=color,
                    width=2.4 if not hud else 1.7,
                    clip_rect=clip_rect,
                    clip_circle=clip_circle,
                )
            else:
                radii = item.get("radii") or {}
                rx = float(radii.get("rx", 8.0)) * POI_RADIUS_WORLD_SCALE
                ry = float(radii.get("ry", radii.get("rx", 8.0))) * POI_RADIUS_WORLD_SCALE
                rot = math.radians(float(radii.get("rot", 0.0)))
                cx, cy = float(item.get("x", 0.0)), float(item.get("y", 0.0))
                screen_points = []
                for i in range(49):
                    a = (i / 48.0) * math.tau
                    lx, ly = math.cos(a) * rx, math.sin(a) * ry
                    wx = cx + lx * math.cos(rot) - ly * math.sin(rot)
                    wy = cy + lx * math.sin(rot) + ly * math.cos(rot)
                    screen_points.append(pt(wx, wy))
                _draw_clipped_polyline(
                    canvas, screen_points,
                    fill=color,
                    width=2.4 if not hud else 1.7,
                    clip_rect=clip_rect,
                    clip_circle=clip_circle,
                )

    # Patrol Zones: some JSON entries contain several closed sub-paths in one
    # polyline.  Never join the end of one closed patrol shape to the next one.
    def split_patrol_polyline(polyline):
        """Split Vulnona patrol polylines into independent open/closed shapes.

        Some entries (notably Delta) are encoded as:
          open points..., A, ..., A, B, ..., B
        where each repeated vertex closes only the loop that started at its
        first occurrence.  The points before A are a separate open segment and
        must NOT be connected into that loop.
        """
        points = []
        for pair in polyline:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                points.append((float(pair[0]), float(pair[1])))

        if len(points) < 2:
            return []

        segments = []
        cursor = 0
        n = len(points)

        while cursor < n:
            # Find the earliest repeated vertex at/after cursor.  Its first
            # occurrence marks the true start of a closed sub-shape.
            first_index = {}
            closure_start = closure_end = None
            for i in range(cursor, n):
                p = points[i]
                if p in first_index:
                    closure_start = first_index[p]
                    closure_end = i
                    break
                first_index[p] = i

            if closure_start is None:
                # Remaining points form one ordinary open polyline.
                if n - cursor >= 2:
                    segments.append(points[cursor:])
                break

            # Preserve any leading open section as its own shape.
            if closure_start - cursor >= 2:
                segments.append(points[cursor:closure_start])

            # Closed loop, including the repeated closing vertex.
            if closure_end - closure_start + 1 >= 3:
                segments.append(points[closure_start:closure_end + 1])

            cursor = closure_end + 1

        return segments

    if show_patrol_zones:
        for item in poi_data.get("patrol_zones", []):
            color = POI_COLORS["patrol_zones"]
            kind = str(item.get("kind", "")).lower()
            polyline = item.get("polyline") or []
            if polyline and kind in {"path", "line"}:
                for segment in split_patrol_polyline(polyline):
                    screen_points = [pt(wx, wy) for wx, wy in segment]
                    _draw_clipped_polyline(
                        canvas, screen_points,
                        fill=color,
                        width=2.2 if not hud else 1.6,
                        clip_rect=clip_rect,
                        clip_circle=clip_circle,
                    )
            else:
                radii = item.get("radii") or {}
                rx = float(radii.get("rx", 8.0)) * POI_RADIUS_WORLD_SCALE
                ry = float(radii.get("ry", radii.get("rx", 8.0))) * POI_RADIUS_WORLD_SCALE
                rot = math.radians(float(radii.get("rot", 0.0)))
                cx, cy = float(item.get("x", 0.0)), float(item.get("y", 0.0))
                screen_points = []
                for i in range(49):
                    a = (i / 48.0) * math.tau
                    lx, ly = math.cos(a) * rx, math.sin(a) * ry
                    wx = cx + lx * math.cos(rot) - ly * math.sin(rot)
                    wy = cy + lx * math.sin(rot) + ly * math.cos(rot)
                    screen_points.append(pt(wx, wy))
                _draw_clipped_polyline(
                    canvas, screen_points,
                    fill=color,
                    width=2.2 if not hud else 1.6,
                    clip_rect=clip_rect,
                    clip_circle=clip_circle,
                )

    # Salt: small diamond markers and obey toggle.
    if show_salt:
        salt_color = POI_COLORS["salt_licks"]
        salt_size = 4 if hud else 6
        for item in poi_data.get("salt_licks", []):
            sx, sy = pt(item.get("x", 0.0), item.get("y", 0.0))
            if not point_visible(sx, sy, salt_size + 1):
                continue
            canvas.create_polygon(
                sx, sy-salt_size, sx+salt_size, sy,
                sx, sy+salt_size, sx-salt_size, sy,
                fill=salt_color, outline="#2f3640", width=1
            )


def _format_stat(value: float) -> str:
    if abs(value) < 10: return f"{value:.1f}"
    return str(int(round(value)))

HUD_MARGIN = 14
MINI_MAP_SIZE = 220
MINI_MAP_CROP_FRACTION = 0.16
QUEST_PANEL_WIDTH = 270

# ==================== VITALS PANEL (HUD CHI TIẾT) ====================
class VitalsPanel:
    def __init__(self, root: tk.Tk, opacity: float = 1.0):
        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", opacity)
        self.window.configure(bg="#000001")
        self.window.attributes("-transparentcolor", "#000001")
        self.window.geometry(f"+{HUD_MARGIN}+{HUD_MARGIN + MINI_MAP_SIZE + 14}")
        self.is_movable = False
        self._drag_start_x = 0
        self._drag_start_y = 0
        
        self.canvas = tk.Canvas(self.window, width=240, height=130, background="#000001", highlightthickness=0)
        self.canvas.pack()
        
        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_motion)
        self.window.update_idletasks()
        self._set_clickthrough(True)
        self.hide()

    def _set_clickthrough(self, clickthrough: bool) -> None:
        try:
            self.window.update_idletasks()
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.window.winfo_id())
            if not hwnd: hwnd = self.window.winfo_id()
            style = user32.GetWindowLongW(hwnd, -20)
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            WS_EX_NOACTIVATE = 0x08000000
            if clickthrough: style |= (WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE)
            else:
                style &= ~WS_EX_TRANSPARENT
                style |= (WS_EX_LAYERED | WS_EX_NOACTIVATE)
            user32.SetWindowLongW(hwnd, -20, style)
        except Exception: pass

    def set_opacity(self, alpha: float) -> None:
        self.window.attributes("-alpha", alpha)
        
    def toggle_move_mode(self) -> None:
        self.is_movable = not self.is_movable
        self._set_clickthrough(not self.is_movable)

    def _on_drag_start(self, event) -> None:
        if self.is_movable:
            self._drag_start_x = event.x_root - self.window.winfo_x()
            self._drag_start_y = event.y_root - self.window.winfo_y()

    def _on_drag_motion(self, event) -> None:
        if self.is_movable:
            x = event.x_root - self._drag_start_x
            y = event.y_root - self._drag_start_y
            self.window.geometry(f"+{x}+{y}")

    def show(self) -> None: self.window.deiconify()
    def hide(self) -> None: self.window.withdraw()
    
    def update(self, status: "islepilot.IslePilotStatus") -> None:
        self.canvas.delete("all")
        raw_growth = getattr(status, 'growth', 0)
        growth_val = raw_growth * 100 if raw_growth <= 1.0 else raw_growth

        border_col = ACCENT_RED if self.is_movable else HUD_BORDER
        self.canvas.create_rectangle(2, 2, 238, 128, fill=HUD_BG, outline=border_col, width=1.5)
        self.canvas.create_line(2, 2, 14, 2, fill=ACCENT_CYAN, width=2)
        self.canvas.create_line(2, 2, 2, 14, fill=ACCENT_CYAN, width=2)

        # Đổi nhãn chữ sang Icon
        stats = [
            ("✚", getattr(status, 'health', 0), getattr(status, 'max_health', 1), ACCENT_RED),
            ("⚡", getattr(status, 'stamina', 0), getattr(status, 'max_stamina', 1), ACCENT_YELLOW),
            ("💧", getattr(status, 'thirst', 0), getattr(status, 'max_thirst', 1), "#0984e3"),
            ("🍖", getattr(status, 'hunger', 0), getattr(status, 'max_hunger', 1), ACCENT_ORANGE),
            ("🌱", growth_val, 100, ACCENT_GREEN)
        ]
        
        y = 10
        for icon, current, maximum, color in stats:
            # Ô badge chứa Icon
            self.canvas.create_rectangle(8, y, 38, y + 18, fill="#16222f", outline="#223244")
            self.canvas.create_text(
                23, y + 9, 
                text=icon, 
                fill=color, 
                font=("Segoe UI Emoji", 10, "bold")
            )
            
            # Thanh đo (Progress bar)
            bar_x = 44
            bar_w = 144
            bar_h = 18
            self.canvas.create_rectangle(bar_x, y, bar_x + bar_w, y + bar_h, fill="#121820", outline="#1e2936")
            
            if current is not None and maximum:
                fraction = max(0.0, min(1.0, current / maximum))
                if fraction > 0:
                    self.canvas.create_rectangle(
                        bar_x + 1, y + 1, 
                        bar_x + (bar_w * fraction) - 1, y + bar_h - 1, 
                        fill=color, outline=""
                    )
                val_text = f"{_format_stat(current)}/{_format_stat(maximum)}"
                self.canvas.create_text(bar_x + bar_w / 2, y + 9, text=val_text, fill="#ffffff", font=("Segoe UI", 7, "bold"))
                pct_text = f"{int(fraction * 100)}%"
                self.canvas.create_text(214, y + 9, text=pct_text, fill=color, font=("Segoe UI", 7, "bold"))
            else:
                self.canvas.create_text(bar_x + bar_w / 2, y + 9, text="OFFLINE", fill="#57606f", font=("Segoe UI", 7))
            y += 23
    def destroy(self) -> None: self.window.destroy()

# ==================== MINIMAP RADAR PANEL ====================
class MiniMapPanel:
    def __init__(self, root: tk.Tk, opacity: float = 1.0):
        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", opacity)
        self.window.attributes("-transparentcolor", "#000001")
        self.window.configure(bg="#000001")
        self.window.geometry(f"+{HUD_MARGIN}+{HUD_MARGIN}")
        
        self.is_movable = False
        self._drag_start_x = 0
        self._drag_start_y = 0
        self.shape = "Vuông"
        
        self.canvas = tk.Canvas(self.window, width=MINI_MAP_SIZE, height=MINI_MAP_SIZE, background="#000001", highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_motion)
        
        self._photo = None
        self.window.update_idletasks()
        self._set_clickthrough(True)
        self.hide()

    def _set_clickthrough(self, clickthrough: bool) -> None:
        try:
            self.window.update_idletasks()
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.window.winfo_id())
            if not hwnd: hwnd = self.window.winfo_id()
            style = user32.GetWindowLongW(hwnd, -20)
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            WS_EX_NOACTIVATE = 0x08000000
            if clickthrough: style |= (WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE)
            else:
                style &= ~WS_EX_TRANSPARENT
                style |= (WS_EX_LAYERED | WS_EX_NOACTIVATE)
            user32.SetWindowLongW(hwnd, -20, style)
        except Exception: pass

    def set_opacity(self, alpha: float) -> None:
        self.window.attributes("-alpha", alpha)

    def toggle_move_mode(self) -> None:
        self.is_movable = not self.is_movable
        self._set_clickthrough(not self.is_movable)

    def _on_drag_start(self, event) -> None:
        if self.is_movable:
            self._drag_start_x = event.x_root - self.window.winfo_x()
            self._drag_start_y = event.y_root - self.window.winfo_y()

    def _on_drag_motion(self, event) -> None:
        if self.is_movable:
            x = event.x_root - self._drag_start_x
            y = event.y_root - self._drag_start_y
            self.window.geometry(f"+{x}+{y}")

    def show(self) -> None: self.window.deiconify()
    def hide(self) -> None: self.window.withdraw()
    
    def update_map(self, source_image, profile: MapProfile, x: float, y: float, heading_deg: float, zone_images: tuple["Image.Image", ...] = (), path_history: list[Position] = None, show_regions: bool = False, shape: str = "Vuông", teammates: dict = None, map_app_ref=None) -> None:
        self.shape = shape
        self.canvas.delete("all")
        if source_image is None: return

        nx, ny = profile.to_normalized(Position(x, y, 0.0))
        width, height = source_image.size
        frac = MINI_MAP_CROP_FRACTION
        left = min(max(nx - frac / 2, 0.0), 1.0 - frac)
        top = min(max(ny - frac / 2, 0.0), 1.0 - frac)
        crop_box = (int(left * width), int(top * height), int((left + frac) * width), int((top + frac) * height))
        cropped = source_image.crop(crop_box).convert("RGBA")

        for zone_image in zone_images:
            if zone_image.size != source_image.size:
                zone_image = zone_image.resize(
                    source_image.size,
                    Image.Resampling.LANCZOS
                )
            cropped.alpha_composite(zone_image.crop(crop_box))

        resized = cropped.resize(
            (MINI_MAP_SIZE, MINI_MAP_SIZE),
            Image.Resampling.LANCZOS
        )
        
        if shape == "Tròn":
            mask = Image.new("L", (MINI_MAP_SIZE, MINI_MAP_SIZE), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, MINI_MAP_SIZE, MINI_MAP_SIZE), fill=255)
            bg_img = Image.new("RGBA", (MINI_MAP_SIZE, MINI_MAP_SIZE), "#000001")
            resized = Image.composite(resized, bg_img, mask)

        self._photo = ImageTk.PhotoImage(resized)
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)

        center = MINI_MAP_SIZE / 2
        hud_clip_rect = (2.0, 2.0, MINI_MAP_SIZE - 2.0, MINI_MAP_SIZE - 2.0)
        hud_clip_circle = (center, center, MINI_MAP_SIZE / 2.0 - 2.0) if shape == "Tròn" else None

        def hud_point_visible(px, py, margin=0.0):
            return (
                _point_in_rect(px, py, hud_clip_rect, margin)
                and (hud_clip_circle is None or _point_in_circle(px, py, hud_clip_circle, margin))
            )

        self.canvas.create_line(center - 12, center, center + 12, center, fill="#ffffff", width=1)
        self.canvas.create_line(center, center - 12, center, center + 12, fill="#ffffff", width=1)
        self.canvas.create_oval(center - 24, center - 24, center + 24, center + 24, outline="#ffffff", width=0.8, dash=(2, 4))

        if map_app_ref and hasattr(map_app_ref, 'local_markers'):
            for item in map_app_ref.local_markers:
                key = item.get("key", "").lower()
                if map_app_ref.overlay_vars.get(key) and map_app_ref.overlay_vars[key].get():
                    color = map_app_ref.overlay_colors.get(key, "#ffffff")
                    pos = Position(item.get("x", 0.0), item.get("y", 0.0), 0.0)
                    mnx, mny = profile.to_normalized(pos)
                    mx = (mnx - left) / frac * MINI_MAP_SIZE
                    my = (mny - top) / frac * MINI_MAP_SIZE
                    if hud_point_visible(mx, my, 3.0):
                        self.canvas.create_oval(mx-2.5, my-2.5, mx+2.5, my+2.5, fill=color, outline="#000000", width=0.5)
        
        # ADD-ONLY: draw extra Gateway POIs on HUD; old markers/layers above are unchanged.
        if map_app_ref and getattr(map_app_ref, "gateway_pois", None):
            def _hud_world_to_screen(pos: Position) -> tuple[float, float]:
                pnx, pny = profile.to_normalized(pos)
                return ((pnx - left) / frac * MINI_MAP_SIZE, (pny - top) / frac * MINI_MAP_SIZE)
            _draw_gateway_pois(
                self.canvas, profile, map_app_ref.gateway_pois, _hud_world_to_screen,
                hud=True,
                visible=getattr(map_app_ref, "_zone_visible", None),
                clip_rect=hud_clip_rect,
                clip_circle=hud_clip_circle,
            )

        if path_history and len(path_history) > 0:
            trail_points = []
            for pos in path_history + [Position(x, y, 0.0)]:
                hnx, hny = profile.to_normalized(pos)
                trail_points.append((
                    (hnx - left) / frac * MINI_MAP_SIZE,
                    (hny - top) / frac * MINI_MAP_SIZE
                ))
            _draw_clipped_polyline(
                self.canvas, trail_points,
                fill=ACCENT_CYAN,
                width=2,
                clip_rect=hud_clip_rect,
                clip_circle=hud_clip_circle,
            )

        if show_regions and MAP_LABELS:
            label_font_size = 8
            label_pad = 4.0
            mini_center = MINI_MAP_SIZE / 2.0
            mini_radius = MINI_MAP_SIZE / 2.0 - 2.0

            for name, pos, color, size in MAP_LABELS:
                r_nx, r_ny = profile.to_normalized(pos)
                rx = (r_nx - left) / frac * MINI_MAP_SIZE
                ry = (r_ny - top) / frac * MINI_MAP_SIZE

                # Do not pull labels from outside the current crop onto an edge.
                if not (0.0 <= rx <= MINI_MAP_SIZE and 0.0 <= ry <= MINI_MAP_SIZE):
                    continue

                if shape == "Tròn":
                    # The source point must actually be visible inside the round HUD.
                    dx = rx - mini_center
                    dy = ry - mini_center
                    if dx * dx + dy * dy > mini_radius * mini_radius:
                        continue

                    draw_x, draw_y = _clamp_text_to_circle(
                        rx, ry, name, label_font_size,
                        mini_center, mini_center, mini_radius,
                        padding=label_pad
                    )
                else:
                    draw_x, draw_y = _clamp_text_to_rect(
                        rx, ry, name, label_font_size,
                        2.0, 2.0,
                        MINI_MAP_SIZE - 2.0, MINI_MAP_SIZE - 2.0,
                        padding=label_pad
                    )

                _draw_text_with_outline(
                    self.canvas, draw_x, draw_y,
                    name, label_font_size, color
                )

        border_col = ACCENT_RED if self.is_movable else HUD_BORDER_ACTIVE
        if shape == "Tròn":
            self.canvas.create_oval(2, 2, MINI_MAP_SIZE-2, MINI_MAP_SIZE-2, outline=border_col, width=2)
            self.canvas.create_text(center, 12, text="▲ N", fill=ACCENT_CYAN, font=("Segoe UI", 7, "bold"))
        else:
            self.canvas.create_rectangle(1, 1, MINI_MAP_SIZE-1, MINI_MAP_SIZE-1, outline=border_col, width=1.5)
            self.canvas.create_line(1, 1, 16, 1, fill=ACCENT_CYAN, width=3)
            self.canvas.create_line(1, 1, 1, 16, fill=ACCENT_CYAN, width=3)
            self.canvas.create_line(MINI_MAP_SIZE-16, 1, MINI_MAP_SIZE-1, 1, fill=ACCENT_CYAN, width=3)
            self.canvas.create_line(MINI_MAP_SIZE-1, 1, MINI_MAP_SIZE-1, 16, fill=ACCENT_CYAN, width=3)
            self.canvas.create_text(center, 10, text="N", fill=ACCENT_CYAN, font=("Segoe UI", 7, "bold"))

        self.canvas.create_rectangle(center - 45, MINI_MAP_SIZE - 16, center + 45, MINI_MAP_SIZE - 2, fill="#0c1015", outline="#212e3d")
        self.canvas.create_text(center, MINI_MAP_SIZE - 9, text=f"{int(x)}, {int(y)}", fill="#c8d6e5", font=("Segoe UI", 6, "bold"))

        if teammates:
            try:
                for tid, tdata in teammates.items():
                    if not tdata.get("has_pos"): continue
                    tnx, tny = profile.to_normalized(tdata["pos"])
                    hx = (tnx - left) / frac * MINI_MAP_SIZE
                    hy = (tny - top) / frac * MINI_MAP_SIZE
                    if hud_point_visible(hx, hy, 12.0):
                        _draw_heading_polygon(self.canvas, hx, hy, tdata["yaw"], 10, ACCENT_GREEN)
            except Exception: pass

        marker_x = (nx - left) / frac * MINI_MAP_SIZE
        marker_y = (ny - top) / frac * MINI_MAP_SIZE

        if hud_clip_circle is not None:
            cx, cy, radius = hud_clip_circle
            dx, dy = marker_x - cx, marker_y - cy
            safe_radius = max(1.0, radius - 13.0)
            dist = math.hypot(dx, dy)
            if dist > safe_radius and dist > 0:
                marker_x = cx + dx * safe_radius / dist
                marker_y = cy + dy * safe_radius / dist
        else:
            marker_x = max(15.0, min(MINI_MAP_SIZE - 15.0, marker_x))
            marker_y = max(15.0, min(MINI_MAP_SIZE - 15.0, marker_y))

        _draw_heading_polygon(self.canvas, marker_x, marker_y, heading_deg, 11, ACCENT_RED)

    def destroy(self) -> None: self.window.destroy()

# ==================== QUEST PANEL (HUD NHIỆM VỤ) ====================
class QuestPanel:
    def __init__(self, root: tk.Tk, opacity: float = 1.0):
        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", opacity)
        self.window.configure(bg=HUD_BG)
        self.window.geometry(f"+{root.winfo_screenwidth() - QUEST_PANEL_WIDTH - HUD_MARGIN}+{HUD_MARGIN}")
        
        self.is_movable = False
        self._drag_start_x = 0
        self._drag_start_y = 0
        
        self.main_frame = ctk.CTkFrame(self.window, fg_color=HUD_BG, border_width=1.5, border_color=HUD_BORDER, corner_radius=8)
        self.main_frame.pack(fill="both", expand=True, padx=2, pady=2)
        
        top_bar = ctk.CTkFrame(self.main_frame, fg_color="#141c24", corner_radius=6, height=28)
        top_bar.pack(fill="x", padx=6, pady=(6, 4))
        
        self.lbl_title = ctk.CTkLabel(top_bar, text="❖ PRIME OBJECTIVES", font=ctk.CTkFont(size=10, weight="bold"), text_color=ACCENT_CYAN)
        self.lbl_title.pack(side="left", padx=8)
        
        self.prime_val_var = tk.StringVar(value="0/0")
        self.lbl_val = ctk.CTkLabel(top_bar, textvariable=self.prime_val_var, font=ctk.CTkFont(size=10, weight="bold"), text_color=ACCENT_YELLOW)
        self.lbl_val.pack(side="right", padx=8)

        self.prime_progress = ctk.CTkProgressBar(self.main_frame, height=4, progress_color=ACCENT_YELLOW, fg_color="#1a2530")
        self.prime_progress.pack(fill="x", padx=8, pady=(0, 6))
        self.prime_progress.set(0)

        self._bind_drag(self.main_frame)
        self._bind_drag(top_bar)
        self._bind_drag(self.lbl_title)

        self._rows: list[tuple[tk.Label, tk.Label]] = []
        for _ in range(10):
            row = tk.Frame(self.main_frame, bg=HUD_BG)
            row.pack(fill="x", padx=8, pady=1)
            check = tk.Label(row, text="", fg="#57606f", bg=HUD_BG, font=("Segoe UI", 9, "bold"), width=2)
            check.pack(side="left")
            name = tk.Label(row, text="", fg="#c8d6e5", bg=HUD_BG, font=("Segoe UI", 8), anchor="w", wraplength=QUEST_PANEL_WIDTH - 45, justify="left")
            name.pack(side="left", fill="x", expand=True)
            self._rows.append((check, name))
            self._bind_drag(row)
            self._bind_drag(check)
            self._bind_drag(name)
            
        self.window.update_idletasks()
        self._set_clickthrough(True)
        self.hide()

    def _set_clickthrough(self, clickthrough: bool) -> None:
        try:
            self.window.update_idletasks()
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.window.winfo_id())
            if not hwnd: hwnd = self.window.winfo_id()
            style = user32.GetWindowLongW(hwnd, -20)
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            WS_EX_NOACTIVATE = 0x08000000
            if clickthrough: style |= (WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE)
            else:
                style &= ~WS_EX_TRANSPARENT
                style |= (WS_EX_LAYERED | WS_EX_NOACTIVATE)
            user32.SetWindowLongW(hwnd, -20, style)
        except Exception: pass

    def _bind_drag(self, widget: tk.Widget) -> None:
        widget.bind("<ButtonPress-1>", self._on_drag_start)
        widget.bind("<B1-Motion>", self._on_drag_motion)

    def set_opacity(self, alpha: float) -> None:
        self.window.attributes("-alpha", alpha)
        
    def toggle_move_mode(self) -> None:
        self.is_movable = not self.is_movable
        border = ACCENT_RED if self.is_movable else HUD_BORDER
        self.main_frame.configure(border_color=border)
        self._set_clickthrough(not self.is_movable)

    def _on_drag_start(self, event) -> None:
        if self.is_movable:
            self._drag_start_x = event.x_root - self.window.winfo_x()
            self._drag_start_y = event.y_root - self.window.winfo_y()

    def _on_drag_motion(self, event) -> None:
        if self.is_movable:
            x = event.x_root - self._drag_start_x
            y = event.y_root - self._drag_start_y
            self.window.geometry(f"+{x}+{y}")

    def show(self) -> None: self.window.deiconify()
    def hide(self) -> None: self.window.withdraw()
    def update(self, status: "islepilot.IslePilotStatus") -> None:
        self.prime_val_var.set(f"{status.prime_done} / {status.prime_total}")
        if status.prime_total > 0:
            self.prime_progress.set(status.prime_done / status.prime_total)
        for index, (check, name) in enumerate(self._rows):
            if index < len(status.quests):
                quest = status.quests[index]
                check.configure(text="●" if quest.done else "○", fg=ACCENT_GREEN if quest.done else "#57606f")
                name.configure(text=islepilot.translate_quest(quest.name), fg="#ffffff" if quest.done else "#8395a7")
            else:
                check.configure(text="")
                name.configure(text="")
    def destroy(self) -> None: self.window.destroy()


# ==================== DIRECTIONAL PING HUD ====================
class PingDirectionOverlay:
    EDGE_MARGIN_X = 115
    EDGE_MARGIN_Y = 90

    def __init__(self, root: tk.Tk, opacity: float = 1.0):
        self.root = root
        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", opacity)
        self.window.configure(bg="#000001")
        self.window.attributes("-transparentcolor", "#000001")
        sw = max(1, root.winfo_screenwidth())
        sh = max(1, root.winfo_screenheight())
        self.window.geometry(f"{sw}x{sh}+0+0")
        self.canvas = tk.Canvas(self.window, width=sw, height=sh, background="#000001", highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.window.update_idletasks()
        self._set_clickthrough()
        self.hide()

    def _set_clickthrough(self) -> None:
        try:
            self.window.update_idletasks()
            user32 = ctypes.windll.user32
            hwnd = user32.GetAncestor(self.window.winfo_id(), 2)
            if not hwnd: hwnd = self.window.winfo_id()
            style = user32.GetWindowLongW(hwnd, -20)
            style |= 0x00000020 | 0x00080000 | 0x08000000 | 0x00000080
            user32.SetWindowLongW(hwnd, -20, style)
        except Exception:
            pass

    def show(self) -> None: self.window.deiconify()
    def hide(self) -> None:
        self.canvas.delete("all")
        self.window.withdraw()

    @staticmethod
    def _distance_meters(a: Position, b: Position) -> float:
        return math.hypot(b.x-a.x, b.y-a.y) / 100.0

    @staticmethod
    def _map_bearing(profile: MapProfile, origin: Position, target: Position) -> float:
        ox, oy = profile.to_normalized(origin)
        tx, ty = profile.to_normalized(target)
        return math.degrees(math.atan2(tx-ox, -(ty-oy))) % 360.0

    def _draw_one(self, profile: MapProfile, player_pos: Position, heading: float, ping_pos: Position, label: str, color: str, index: int) -> None:
        sw = max(self.canvas.winfo_width(), self.root.winfo_screenwidth(), 1)
        sh = max(self.canvas.winfo_height(), self.root.winfo_screenheight(), 1)
        cx, cy = sw/2.0, sh/2.0
        bearing = self._map_bearing(profile, player_pos, ping_pos)
        relative = (bearing-heading+180.0) % 360.0 - 180.0
        theta = math.radians(relative)
        rx = max(80.0, cx-self.EDGE_MARGIN_X)
        ry = max(70.0, cy-self.EDGE_MARGIN_Y)
        px = cx + math.sin(theta)*rx
        py = cy - math.cos(theta)*ry
        if index:
            px += math.cos(theta) * (((index % 3)-1)*24.0)
            py += math.sin(theta) * (((index % 3)-1)*24.0)
        dist = self._distance_meters(player_pos, ping_pos)
        dist_text = f"{dist/1000.0:.1f} km" if dist >= 1000 else f"{int(round(dist))} m"
        ux, uy = math.sin(theta), -math.cos(theta)
        txv, tyv = math.cos(theta), math.sin(theta)
        tipx, tipy = px+ux*17, py+uy*17
        basex, basey = px-ux*7, py-uy*7
        # Same directional arrow shape for Party / Manual / Asset pings.
        # Black Asset Ping uses a white text outline so it remains visible
        # against the game and transparent HUD background.
        text_outline = "#ffffff" if str(color).lower() in {"#000000", "black"} else "#05070a"

        self.canvas.create_polygon(
            tipx, tipy,
            basex + txv*8, basey + tyv*8,
            basex - txv*8, basey - tyv*8,
            fill=color,
            outline="#ffffff",
            width=1.2,
            joinstyle="round"
        )
        _draw_text_with_outline(
            self.canvas,
            px - ux*34,
            py - uy*34,
            f"{label}  •  {dist_text}",
            10,
            color,
            outline_color=text_outline
        )

    def update(self, profile: MapProfile, player_pos: Position | None, player_heading: float | None, teammates: dict | None, my_ping: dict | None = None, manual_ping: dict | None = None, asset_ping: dict | None = None) -> int:
        self.canvas.delete("all")
        if player_pos is None or player_heading is None: return 0
        entries = []
        if teammates:
            for _tid, tdata in teammates.items():
                ping = tdata.get("ping")
                if not ping: continue
                expires_at = ping.get("expires_at") if isinstance(ping, dict) else None
                if expires_at is not None:
                    try:
                        if float(expires_at) <= time.time():
                            continue
                    except (TypeError, ValueError):
                        pass
                try: p = Position(float(ping["x"]), float(ping["y"]), 0.0)
                except (KeyError, TypeError, ValueError): continue
                entries.append((p, str(tdata.get("name") or "Đồng đội"), ACCENT_YELLOW))
        if my_ping and isinstance(my_ping.get("pos"), Position):
            expires_at = my_ping.get("expires_at")
            expired = False
            if expires_at is not None:
                try:
                    expired = float(expires_at) <= time.time()
                except (TypeError, ValueError):
                    expired = False
            if not expired:
                entries.append((my_ping["pos"], "Ping bạn", ACCENT_CYAN))

        if manual_ping and isinstance(manual_ping.get("pos"), Position):
            expires_at = manual_ping.get("expires_at")
            expired = False
            if expires_at is not None:
                try:
                    expired = float(expires_at) <= time.time()
                except (TypeError, ValueError):
                    expired = False
            if not expired:
                entries.append(
                    (manual_ping["pos"], "Manual Ping", ACCENT_RED)
                )
        if asset_ping and isinstance(asset_ping.get("pos"), Position):
            expires_at = asset_ping.get("expires_at")
            expired = False
            if expires_at is not None:
                try:
                    expired = float(expires_at) <= time.time()
                except (TypeError, ValueError):
                    expired = False
            if not expired:
                entries.append((asset_ping["pos"], "Asset Ping", "#000000"))

        for i,(p,label,color) in enumerate(entries): self._draw_one(profile, player_pos, float(player_heading), p, label, color, i)
        return len(entries)

    def destroy(self) -> None: self.window.destroy()


class IslePilotHud:
    def __init__(self, root: tk.Tk, opacity: float = 1.0):
        self.minimap = MiniMapPanel(root, opacity)
        self.vitals = VitalsPanel(root, opacity)
        self.quests = QuestPanel(root, opacity)
        
    def toggle_move_mode(self) -> None:
        self.minimap.toggle_move_mode()
        self.vitals.toggle_move_mode()
        self.quests.toggle_move_mode()
        
    def show(self, show_minimap: bool = True, show_vitals: bool = True, show_quests: bool = True) -> None:
        if show_minimap: self.minimap.show()
        else: self.minimap.hide()

        if show_vitals: self.vitals.show()
        else: self.vitals.hide()

        if show_quests: self.quests.show()
        else: self.quests.hide()
        
    def hide(self) -> None:
        self.minimap.hide()
        self.vitals.hide()
        self.quests.hide()
        
    def update_map(self, source_image, profile: MapProfile, x: float, y: float, heading_deg: float, zone_images: tuple["Image.Image", ...] = (), path_history: list[Position] = None, show_regions: bool = False, shape: str = "Vuông", teammates: dict = None, map_app_ref=None) -> None:
        self.minimap.update_map(source_image, profile, x, y, heading_deg, zone_images=zone_images, path_history=path_history, show_regions=show_regions, shape=shape, teammates=teammates, map_app_ref=map_app_ref)
        
    def update_vitals(self, status: "islepilot.IslePilotStatus") -> None: 
        self.vitals.update(status)
        
    def update_quests(self, status: "islepilot.IslePilotStatus") -> None: 
        self.quests.update(status)
        
    def destroy(self) -> None:
        self.minimap.destroy()
        self.vitals.destroy()
        self.quests.destroy()

FOREGROUND_POLL_MS = 300
LOCAL_POSITION_FRESH_SECONDS = 2.0
LOCAL_TRAIL_MIN_INTERVAL_SECONDS = 1.5

# ==================== MAIN APPLICATION ====================
class MapApp:
    POLL_MS = 150

    def __init__(self, root: ctk.CTk):
        self.root = root
        
        self.current_hotkey_name = "Tab"
        self.current_hotkey_vk = HOTKEYS["Tab"]
        self.move_hotkey_name = "F2"
        self.move_hotkey_vk = HOTKEYS["F2"]
        self.ingame_hotkey_name = "M"
        self.ingame_hotkey_vk = HOTKEYS["M"]
        
        self.minimap_opacity = 1.0
        self.minimap_shape = "Vuông"
        self.show_regions_var = ctk.BooleanVar(value=True)
        
        self.show_minimap_var = ctk.BooleanVar(value=True)
        self.show_vitals_var = ctk.BooleanVar(value=True)
        self.show_quests_var = ctk.BooleanVar(value=True)
        self.show_hud_when_app_focused_var = ctk.BooleanVar(value=False)
        self.asset_location_ping_enabled_var = ctk.BooleanVar(value=False)
        
        self.show_teammate_vitals_map_var = ctk.BooleanVar(value=True)
        self.show_teammate_vitals_menu_var = ctk.BooleanVar(value=True)
        # Party Ping duration (independent H / M / S)
        self.ping_duration_hours_var = ctk.StringVar(value="0")
        self.ping_duration_minutes_var = ctk.StringVar(value="2")
        self.ping_duration_seconds_var = ctk.StringVar(value="0")

        self.manual_ping_coord_var = ctk.StringVar(value="")

        # Manual Coordinate Ping duration (independent H / M / S)
        self.manual_ping_duration_hours_var = ctk.StringVar(value="0")
        self.manual_ping_duration_minutes_var = ctk.StringVar(value="5")
        self.manual_ping_duration_seconds_var = ctk.StringVar(value="0")
        
        self.profiles = load_profiles()
        self.profile = self._load_app_config()
        self.shape_var = ctk.StringVar(value=self.minimap_shape)
        
        self.current: Position | None = None
        self.path_history: list[Position] = []

        self.last_clipboard = ""
        self.source_image: Image.Image | None = None
        self.tray_icon: pystray.Icon | None = None
        
        self.global_escape = threading.Event()
        self.ingame_escape = threading.Event()
        self.last_clipboard_sequence = ctypes.windll.user32.GetClipboardSequenceNumber()

        # Party
        saved_api_url, saved_name = self._load_sv_config()
        self.api_url_var = ctk.StringVar(value=saved_api_url)
        self.player_name_var = ctk.StringVar(value=saved_name)
        self.party_code_var = ctk.StringVar(value="")
        self.party_pw_var = ctk.StringVar(value="")
        self.player_id = str(uuid.uuid4())[:4].upper()
        self.teammates = {}
        self.is_party_active = False
        
        self.last_vitals = None
        self.my_active_ping = None
        self.manual_active_ping = None
        self.asset_location_active_ping = None

        self.m_zoom = MIN_ZOOM
        self.m_center_nx = 0.5
        self.m_center_ny = 0.5
        self.m_view: tuple[float, float, float, float] | None = None
        self._m_pan_last: tuple[int, int] | None = None
        self._m_pending_hq_job: str | None = None
        self.m_x_offset = 0.0
        self.m_y_offset = 0.0
        self.m_canvas_w = 1
        self.m_canvas_h = 1
        self.m_placeholder_rect = None
        self.m_map_image: ImageTk.PhotoImage | None = None
        self.m_rendered_size: tuple[int, int] | None = None

        self.ig_zoom = MIN_ZOOM
        self.ig_center_nx = 0.5
        self.ig_center_ny = 0.5
        self.ig_view: tuple[float, float, float, float] | None = None
        self._ig_pan_last: tuple[int, int] | None = None
        self._ig_pending_hq_job: str | None = None
        self.ig_x_offset = 0.0
        self.ig_y_offset = 0.0
        self.ig_canvas_w = 1
        self.ig_canvas_h = 1
        self.ig_placeholder_rect = None
        self.ig_map_image: ImageTk.PhotoImage | None = None
        self.ig_rendered_size: tuple[int, int] | None = None

        self._zone_images: dict[str, Image.Image] = {}
        self._zone_visible: dict[str, bool] = {key: (False if key in {"400OV", "600OV"} else True) for key, _label, _filename, _color in MAP_TOGGLE_LAYERS}
        self._m_zone_toggle_hitboxes: dict[str, tuple[float, float, float, float]] = {}
        self._ig_zone_toggle_hitboxes: dict[str, tuple[float, float, float, float]] = {}

        self._islepilot_cred_path = DATA_ROOT / "islepilot.cred"
        self._islepilot_session: islepilot.IslePilotSession | None = None
        self._islepilot_steam_id: str | None = None
        self._islepilot_heading_deg: float | None = None
        self._islepilot_online = False
        self._islepilot_logging_in = False
        self._hud: IslePilotHud | None = None
        self._ping_direction_hud = PingDirectionOverlay(self.root, opacity=self.minimap_opacity)

        self._local_session: localtelemetry.LocalMovementSession | None = None
        self._local_state = "starting"
        self._local_last_update = 0.0
        self._local_heading_deg: float | None = None
        self._local_trail_last_update = 0.0
        self._npcap_prompted = False

        self.map_visible = False
        self.ingame_map_visible = False

        # True only when the in-game map is temporarily hidden because
        # The Isle is not the foreground application.
        # This does NOT change the user's actual on/off state.
        self._ingame_map_focus_hidden = False

        self.local_markers: list[dict] = []
        self.gateway_pois: dict[str, list[dict]] = {"sanctuaries": [], "migrations": [], "patrol_zones": [], "salt_licks": []}
        self.overlay_vars: dict[str, ctk.BooleanVar] = {}
        self.overlay_colors: dict[str, str] = {}
        self.animal_keys: list[str] = []
        self.herb_keys: list[str] = []

        self.root.title(f"The-Maps {APP_VERSION}")
        if APP_ICON_ICO.exists(): self.root.iconbitmap(default=str(APP_ICON_ICO))
        
        self.root.geometry("420x940")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self._exit)

        self.ingame_map_window = tk.Toplevel(self.root)
        self.ingame_map_window.overrideredirect(True)
        self.ingame_map_window.attributes("-topmost", True)
        self.ingame_map_window.attributes("-alpha", 0.95)
        self.ingame_map_window.configure(bg="#0c1015")
        
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = int(sh * 0.85)
        h = int(sh * 0.85)
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.ingame_map_window.geometry(f"{w}x{h}+{x}+{y}")
        self._set_window_noactivate(self.ingame_map_window)
        self.ingame_map_window.withdraw()

        self._build_ui()

        self.root.bind(
            "<FocusIn>",
            lambda _e: self.root.after(20, self._apply_focus_visibility),
            add="+"
        )
        self.root.bind(
            "<FocusOut>",
            lambda _e: self.root.after(20, self._apply_focus_visibility),
            add="+"
        )

        self._load_map_image()
        self._load_local_animal_herbs()
        self._load_gateway_pois()
        self._redraw()
        self._start_tray()
        
        threading.Thread(target=self._keyboard_hook_loop, daemon=True).start()
        self._poll_clipboard()
        self._poll_global_escape_event()
        self._start_local_telemetry()
        self.root.after(1000, self._prompt_for_npcap_if_needed)

        saved_credentials = islepilot.load_credentials(self._islepilot_cred_path)
        if saved_credentials: self._islepilot_start_session(*saved_credentials)
        self._poll_hud_visibility()
        self._update_notified = False
        self.root.after(5000, self._check_for_update)

    def _set_window_noactivate(self, window: tk.Toplevel) -> None:
        try:
            window.update_idletasks()
            user32 = ctypes.windll.user32
            hwnd = user32.GetAncestor(window.winfo_id(), 2)
            style = user32.GetWindowLongW(hwnd, -20)
            WS_EX_NOACTIVATE = 0x08000000
            style |= WS_EX_NOACTIVATE
            user32.SetWindowLongW(hwnd, -20, style)
        except Exception: pass

    def _is_game_foreground(self) -> bool:
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = user32.GetForegroundWindow()
            if not hwnd: return False
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h_process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if h_process:
                path_buf = ctypes.create_unicode_buffer(260)
                size = ctypes.c_ulong(260)
                if kernel32.QueryFullProcessImageNameW(h_process, 0, path_buf, ctypes.byref(size)):
                    kernel32.CloseHandle(h_process)
                    process_path = path_buf.value.lower()
                    if "theisle" in process_path: return True
                    else: return False
                else: kernel32.CloseHandle(h_process)
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.lower().strip()
            return title == "the isle"
        except Exception: return False

    def _is_app_foreground(self) -> bool:
        """True khi cửa sổ foreground thuộc chính process The-Maps."""
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return False

            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return int(pid.value) == int(os.getpid())
        except Exception:
            return False

    def _focus_allows_hud(self) -> bool:
        """Apply the The-Maps focus option explicitly before game detection."""
        if self._is_app_foreground():
            return bool(self.show_hud_when_app_focused_var.get())
        return self._is_game_foreground()

    def _load_gateway_pois(self) -> None:
        """Load only Sanctuaries, Migrations, Patrol Zones and Salt from the second JSON file."""
        json_file = GATEWAY_POI_JSON_PATH if GATEWAY_POI_JSON_PATH.exists() else GATEWAY_POI_JSON_FALLBACK
        if not json_file.exists():
            return
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            self.gateway_pois = {
                "sanctuaries": list(data.get("sanctuaries", []) or []),
                "migrations": list(data.get("migrations", []) or []),
                "patrol_zones": list(data.get("patrol_zones", []) or []),
                "salt_licks": list(data.get("salt_licks", []) or []),
            }
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.gateway_pois = {"sanctuaries": [], "migrations": [], "patrol_zones": [], "salt_licks": []}

    def _load_local_animal_herbs(self):
        json_file = LOCAL_JSON_PATH if LOCAL_JSON_PATH.exists() else LOCAL_JSON_FALLBACK
        if not json_file.exists(): return

        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.local_markers = []
            if isinstance(data, dict):
                for cat_name, items in data.items():
                    if cat_name == "General": continue
                    for item in items:
                        item["key"] = item["name"].lower()
                        self.local_markers.append(item)
            elif isinstance(data, list):
                self.local_markers = data

            animal_dict = {}
            herb_dict = {}
            
            for item in self.local_markers:
                k = item.get("key", "").lower()
                n = item.get("name", "Unknown")
                cat = item.get("category", item.get("group", ""))
                if k == "_road_": continue
                if "Animal" in cat or k in ["chicken", "deer", "boar", "rabbit", "goat", "galli", "turtle", "crab", "taco", "fish", "frog", "dryo", "deino", "galliai", "deinoai"]:
                    animal_dict[k] = n
                else:
                    herb_dict[k] = n

            self.animal_keys = sorted(animal_dict.keys())
            self.herb_keys = sorted(herb_dict.keys())

            animal_color_map = {
                "chicken": "#feca57", "deer": "#ff9f43", "boar": "#8e44ad", 
                "rabbit": "#1dd1a1", "goat": "#c8d6e5", "galli": "#ee5253", "galliai": "#ee5253", 
                "turtle": "#10ac84", "crab": "#ff6b6b", "taco": "#ff9f43", 
                "fish": "#48dbfb", "frog": "#2ed573", "dryo": "#8395a7", 
                "deino": "#00d2d3", "deinoai": "#00d2d3"
            }
            herb_color_map = {
                "agave": "#2ed573", "ash": "#8395a7", "azureapol": "#0abde3", 
                "banana": "#feca57", "cashew": "#e67e22", "chanterelle": "#f39c12", 
                "coconut": "#ff9f43", "crimapol": "#ee5253", "fiddlehead": "#10ac84", 
                "fireweed": "#ff78c4", "jackfruit": "#feca57", "mango": "#f39c12", 
                "marigold": "#feca57", "melon": "#2ed573", "orange": "#ff9f43", 
                "papaya": "#ff9f43", "potato": "#e67e22", "potatovine": "#1dd1a1", 
                "pumpkin": "#e67e22", "radish": "#ff78c4", "redcurrant": "#c0392b", 
                "russula": "#ee5253", "sumac": "#c0392b", "sunchoke": "#feca57", 
                "trillium": "#ffffff", "violetapol": "#a55eea",
                "gastro": "#8395a7", "saltrock": "#f1f2f6", "clamrock": "#57606f"
            }

            for k in self.animal_keys:
                self.overlay_vars[k] = ctk.BooleanVar(value=False)
                self.overlay_colors[k] = animal_color_map.get(k, "#feca57")

            for k in self.herb_keys:
                self.overlay_vars[k] = ctk.BooleanVar(value=False)
                self.overlay_colors[k] = herb_color_map.get(k, "#2ed573")

            cols = 3
            for idx, k in enumerate(self.animal_keys):
                r, c = idx // cols, idx % cols
                chk = ctk.CTkCheckBox(self.animal_frame, text=animal_dict[k], variable=self.overlay_vars[k], 
                                      command=self._redraw, checkbox_width=16, checkbox_height=16, font=ctk.CTkFont(size=11), text_color="#c8d6e5")
                chk.grid(row=r, column=c, sticky="w", pady=3, padx=2)

            for idx, k in enumerate(self.herb_keys):
                r, c = idx // cols, idx % cols
                chk = ctk.CTkCheckBox(self.herb_frame, text=herb_dict[k], variable=self.overlay_vars[k], 
                                      command=self._redraw, checkbox_width=16, checkbox_height=16, font=ctk.CTkFont(size=11), text_color="#c8d6e5")
                chk.grid(row=r, column=c, sticky="w", pady=3, padx=2)

        except Exception as e:
            traceback.print_exc()

    def _toggle_all_animals(self):
        val = self.all_animals_var.get()
        for k in self.animal_keys:
            if k in self.overlay_vars: self.overlay_vars[k].set(val)
        self._redraw()

    def _toggle_all_herbs(self):
        val = self.all_herbs_var.get()
        for k in self.herb_keys:
            if k in self.overlay_vars: self.overlay_vars[k].set(val)
        self._redraw()

    def _toggle_animal_frame(self):
        self.animal_expanded = not self.animal_expanded
        if self.animal_expanded:
            self.btn_toggle_animals.configure(text="▼ Động Vật (Animals)")
            self.animal_frame.pack(fill="x", padx=12, pady=(0, 6), after=self.animal_head)
        else:
            self.btn_toggle_animals.configure(text="▶ Động Vật (Animals)")
            self.animal_frame.pack_forget()

    def _toggle_herb_frame(self):
        self.herb_expanded = not self.herb_expanded
        if self.herb_expanded:
            self.btn_toggle_herbs.configure(text="▼ Thực Vật/Khác")
            self.herb_frame.pack(fill="x", padx=12, pady=(0, 6), after=self.herb_head)
        else:
            self.btn_toggle_herbs.configure(text="▶ Thực Vật/Khác")
            self.herb_frame.pack_forget()

    def _load_sv_config(self) -> tuple[str, str]:
        if CONFIG_SV_PATH.exists():
            try: 
                data = json.loads(CONFIG_SV_PATH.read_text(encoding="utf-8"))
                return data.get("api_url", ""), data.get("player_name", "")
            except (json.JSONDecodeError, OSError): pass
        return "", ""

    def _save_sv_config(self) -> None:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        try:
            CONFIG_SV_PATH.write_text(json.dumps({
                "api_url": self.api_url_var.get().strip(),
                "player_name": self.player_name_var.get().strip()
            }, indent=2), encoding="utf-8")
        except OSError: pass

    def _load_app_config(self) -> MapProfile:
        selected_map = ""
        if CONFIG_PATH.exists():
            try: 
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                selected_map = data.get("map", "")
                hk = data.get("hotkey", "Tab")
                if hk in HOTKEYS:
                    self.current_hotkey_name = hk
                    self.current_hotkey_vk = HOTKEYS[hk]
                m_hk = data.get("move_hotkey", "F2")
                if m_hk in HOTKEYS:
                    self.move_hotkey_name = m_hk
                    self.move_hotkey_vk = HOTKEYS[m_hk]
                ig_hk = data.get("ingame_hotkey", "M")
                if ig_hk in HOTKEYS:
                    self.ingame_hotkey_name = ig_hk
                    self.ingame_hotkey_vk = HOTKEYS[ig_hk]
                self.minimap_opacity = data.get("minimap_opacity", 1.0)
                self.show_regions_var.set(data.get("show_regions", True))
                self.minimap_shape = data.get("minimap_shape", "Vuông")
                self.show_minimap_var.set(data.get("show_minimap", True))
                self.show_vitals_var.set(data.get("show_vitals", True))
                self.show_quests_var.set(data.get("show_quests", True))
                self.show_hud_when_app_focused_var.set(
                    data.get("show_hud_when_app_focused", False)
                )
                self.asset_location_ping_enabled_var.set(
                    data.get("asset_location_ping_enabled", False)
                )
                self.show_teammate_vitals_map_var.set(data.get("show_teammate_vitals_map", True))
                self.show_teammate_vitals_menu_var.set(data.get("show_teammate_vitals_menu", True))
                # PARTY PING H:M:S
                try:
                    if any(
                        key in data
                        for key in (
                            "ping_duration_hours",
                            "ping_duration_minutes_hms",
                            "ping_duration_seconds",
                        )
                    ):
                        party_h = int(float(data.get("ping_duration_hours", 0)))
                        party_m = int(float(data.get("ping_duration_minutes_hms", 0)))
                        party_s = int(float(data.get("ping_duration_seconds", 0)))
                        party_total = max(
                            1,
                            min(
                                6 * 3600,
                                party_h * 3600 + party_m * 60 + party_s
                            )
                        )
                    else:
                        # Migrate old config: ping_duration_minutes
                        old_minutes = float(data.get("ping_duration_minutes", 2))
                        party_total = max(
                            1,
                            min(6 * 3600, int(round(old_minutes * 60.0)))
                        )

                    party_h, rem = divmod(party_total, 3600)
                    party_m, party_s = divmod(rem, 60)
                    self.ping_duration_hours_var.set(str(party_h))
                    self.ping_duration_minutes_var.set(str(party_m))
                    self.ping_duration_seconds_var.set(str(party_s))
                except (TypeError, ValueError):
                    self.ping_duration_hours_var.set("0")
                    self.ping_duration_minutes_var.set("2")
                    self.ping_duration_seconds_var.set("0")

                # MANUAL PING H:M:S
                try:
                    if any(
                        key in data
                        for key in (
                            "manual_ping_duration_hours",
                            "manual_ping_duration_minutes_hms",
                            "manual_ping_duration_seconds",
                        )
                    ):
                        manual_h = int(float(data.get("manual_ping_duration_hours", 0)))
                        manual_m = int(float(data.get("manual_ping_duration_minutes_hms", 0)))
                        manual_s = int(float(data.get("manual_ping_duration_seconds", 0)))
                        manual_total = max(
                            1,
                            min(
                                6 * 3600,
                                manual_h * 3600 + manual_m * 60 + manual_s
                            )
                        )
                    else:
                        # Migrate old config: manual_ping_duration_minutes
                        old_manual_minutes = float(
                            data.get("manual_ping_duration_minutes", 5)
                        )
                        manual_total = max(
                            1,
                            min(
                                6 * 3600,
                                int(round(old_manual_minutes * 60.0))
                            )
                        )

                    manual_h, rem = divmod(manual_total, 3600)
                    manual_m, manual_s = divmod(rem, 60)
                    self.manual_ping_duration_hours_var.set(str(manual_h))
                    self.manual_ping_duration_minutes_var.set(str(manual_m))
                    self.manual_ping_duration_seconds_var.set(str(manual_s))
                except (TypeError, ValueError):
                    self.manual_ping_duration_hours_var.set("0")
                    self.manual_ping_duration_minutes_var.set("5")
                    self.manual_ping_duration_seconds_var.set("0")
            except (json.JSONDecodeError, OSError): pass
        return next((p for p in self.profiles if p.profile_id == selected_map), self.profiles[0])

    def _save_app_config(self) -> None:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps({
            "map": self.profile.profile_id,
            "hotkey": self.current_hotkey_name,
            "move_hotkey": self.move_hotkey_name,
            "ingame_hotkey": self.ingame_hotkey_name,
            "minimap_opacity": self.minimap_opacity,
            "show_regions": self.show_regions_var.get(),
            "minimap_shape": self.shape_var.get(),
            "show_minimap": self.show_minimap_var.get(),
            "show_vitals": self.show_vitals_var.get(),
            "show_quests": self.show_quests_var.get(),
            "show_hud_when_app_focused": self.show_hud_when_app_focused_var.get(),
            "asset_location_ping_enabled": self.asset_location_ping_enabled_var.get(),
            "show_teammate_vitals_map": self.show_teammate_vitals_map_var.get(),
            "show_teammate_vitals_menu": self.show_teammate_vitals_menu_var.get(),
            # Legacy minute values kept for compatibility with older builds.
            "ping_duration_minutes": self._get_ping_duration_seconds() / 60.0,
            "manual_ping_duration_minutes": self._get_manual_ping_duration_seconds() / 60.0,

            # New H:M:S settings.
            "ping_duration_hours": int(self.ping_duration_hours_var.get() or 0),
            "ping_duration_minutes_hms": int(self.ping_duration_minutes_var.get() or 0),
            "ping_duration_seconds": int(self.ping_duration_seconds_var.get() or 0),

            "manual_ping_duration_hours": int(self.manual_ping_duration_hours_var.get() or 0),
            "manual_ping_duration_minutes_hms": int(self.manual_ping_duration_minutes_var.get() or 0),
            "manual_ping_duration_seconds": int(self.manual_ping_duration_seconds_var.get() or 0)
        }, indent=2), encoding="utf-8")

    def _build_ui(self) -> None:
        self.control_frame = ctk.CTkScrollableFrame(self.root, width=420, corner_radius=0, fg_color="#0c1015")
        self.control_frame.pack(side="left", fill="both", expand=True)

        header_frame = ctk.CTkFrame(self.control_frame, fg_color="transparent")
        header_frame.pack(pady=(14, 6))
        ctk.CTkLabel(header_frame, text="THE-MAPS PRO", font=ctk.CTkFont(size=22, weight="bold"), text_color=ACCENT_CYAN).pack()
        ctk.CTkLabel(header_frame, text="TACTICAL SUITE // THE ISLE EVRIMA", font=ctk.CTkFont(size=9, weight="bold"), text_color=TEXT_MUTED).pack()

        self.btn_toggle_map = ctk.CTkButton(
            self.control_frame, text=f"MỞ BẢN ĐỒ CHI TIẾT [{self.current_hotkey_name}]", 
            font=ctk.CTkFont(size=13, weight="bold"), height=40,
            fg_color="#0984e3", hover_color="#00cec9", text_color="#ffffff",
            corner_radius=8, command=self._toggle_map_view
        )
        self.btn_toggle_map.pack(pady=(6, 8), padx=16, fill="x")

        # CARD 1: PHÍM TẮT & GIAO DIỆN
        card_hk = ctk.CTkFrame(self.control_frame, fg_color=CARD_BG, border_width=1, border_color=CARD_BORDER, corner_radius=10)
        card_hk.pack(fill="x", padx=16, pady=4)
        
        ctk.CTkLabel(card_hk, text="CẤU HÌNH ĐIỀU KHIỂN & HUD", font=ctk.CTkFont(size=11, weight="bold"), text_color=ACCENT_CYAN).pack(anchor="w", padx=12, pady=(8, 4))
        
        hk_grid = ctk.CTkFrame(card_hk, fg_color="transparent")
        hk_grid.pack(fill="x", padx=10, pady=(0, 4))
        hk_grid.grid_columnconfigure((0,1,2), weight=1)

        ctk.CTkLabel(hk_grid, text="Bật Map", font=ctk.CTkFont(size=10), text_color=TEXT_MUTED).grid(row=0, column=0)
        self.hotkey_combo = ctk.CTkComboBox(hk_grid, values=list(HOTKEYS.keys()), command=self._on_hotkey_change, width=95, height=26, corner_radius=6)
        self.hotkey_combo.set(self.current_hotkey_name)
        self.hotkey_combo.grid(row=1, column=0, padx=2)

        ctk.CTkLabel(hk_grid, text="Ingame", font=ctk.CTkFont(size=10), text_color=TEXT_MUTED).grid(row=0, column=1)
        self.ingame_hotkey_combo = ctk.CTkComboBox(hk_grid, values=list(HOTKEYS.keys()), command=self._on_ingame_hotkey_change, width=95, height=26, corner_radius=6)
        self.ingame_hotkey_combo.set(self.ingame_hotkey_name)
        self.ingame_hotkey_combo.grid(row=1, column=1, padx=2)

        ctk.CTkLabel(hk_grid, text="Kéo HUD", font=ctk.CTkFont(size=10), text_color=TEXT_MUTED).grid(row=0, column=2)
        self.move_hotkey_combo = ctk.CTkComboBox(hk_grid, values=list(HOTKEYS.keys()), command=self._on_move_hotkey_change, width=95, height=26, corner_radius=6)
        self.move_hotkey_combo.set(self.move_hotkey_name)
        self.move_hotkey_combo.grid(row=1, column=2, padx=2)

        ctk.CTkLabel(card_hk, text="Độ mờ lớp HUD:", font=ctk.CTkFont(size=10), text_color=TEXT_MUTED).pack(anchor="w", padx=12, pady=(6, 0))
        self.opacity_slider = ctk.CTkSlider(card_hk, from_=0.2, to=1.0, command=self._on_opacity_change, height=14, progress_color=ACCENT_CYAN)
        self.opacity_slider.set(self.minimap_opacity)
        self.opacity_slider.pack(fill="x", padx=12, pady=(2, 4))

        shape_row = ctk.CTkFrame(card_hk, fg_color="transparent")
        shape_row.pack(fill="x", padx=12, pady=(2, 6))
        ctk.CTkLabel(shape_row, text="Dáng MiniMap:", font=ctk.CTkFont(size=11), text_color="#c8d6e5").pack(side="left")
        self.shape_seg = ctk.CTkSegmentedButton(shape_row, values=["Vuông", "Tròn"], variable=self.shape_var, command=self._on_shape_change, corner_radius=6)
        self.shape_seg.pack(side="right")

        hud_checks = ctk.CTkFrame(card_hk, fg_color="transparent")
        hud_checks.pack(fill="x", padx=10, pady=(0, 8))
        hud_checks.grid_columnconfigure((0,1), weight=1)
        ctk.CTkCheckBox(hud_checks, text="Hiện MiniMap", variable=self.show_minimap_var, command=self._on_hud_toggle, checkbox_width=16, checkbox_height=16, font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w", pady=2)
        ctk.CTkCheckBox(hud_checks, text="Hiện Chỉ số", variable=self.show_vitals_var, command=self._on_hud_toggle, checkbox_width=16, checkbox_height=16, font=ctk.CTkFont(size=11)).grid(row=0, column=1, sticky="w", pady=2)
        ctk.CTkCheckBox(hud_checks, text="Hiện Nhiệm vụ", variable=self.show_quests_var, command=self._on_hud_toggle, checkbox_width=16, checkbox_height=16, font=ctk.CTkFont(size=11)).grid(row=1, column=0, sticky="w", pady=2)
        ctk.CTkCheckBox(hud_checks, text="Tên Khu Vực", variable=self.show_regions_var, command=self._on_region_toggle, checkbox_width=16, checkbox_height=16, font=ctk.CTkFont(size=11)).grid(row=1, column=1, sticky="w", pady=2)

        ctk.CTkCheckBox(
            hud_checks,
            text="Hiện HUD/Map khi focus The-Maps",
            variable=self.show_hud_when_app_focused_var,
            command=self._on_focus_mode_change,
            checkbox_width=16,
            checkbox_height=16,
            font=ctk.CTkFont(size=11)
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 2))

        ctk.CTkCheckBox(
            hud_checks,
            text="Asset Location → Ping (không mở map)",
            variable=self.asset_location_ping_enabled_var,
            command=self._on_asset_location_ping_toggle,
            checkbox_width=16,
            checkbox_height=16,
            font=ctk.CTkFont(size=11)
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(2, 2))

        # CARD 2: ĐỘNG VẬT (COLLAPSIBLE)
        card_animal = ctk.CTkFrame(self.control_frame, fg_color=CARD_BG, border_width=1, border_color=CARD_BORDER, corner_radius=10)
        card_animal.pack(fill="x", padx=16, pady=4)
        
        self.animal_head = ctk.CTkFrame(card_animal, fg_color="transparent")
        self.animal_head.pack(fill="x", padx=10, pady=6)
        self.animal_expanded = False
        self.btn_toggle_animals = ctk.CTkButton(self.animal_head, text="▶ Động Vật (Animals)", width=140, fg_color="transparent", hover_color="#212e3d", text_color="#ffffff", anchor="w", font=ctk.CTkFont(weight="bold", size=11), command=self._toggle_animal_frame)
        self.btn_toggle_animals.pack(side="left")
        self.all_animals_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.animal_head, text="Tất cả", variable=self.all_animals_var, command=self._toggle_all_animals, checkbox_width=16, checkbox_height=16, font=ctk.CTkFont(size=11)).pack(side="right")
        
        self.animal_frame = ctk.CTkFrame(card_animal, fg_color="transparent")

        # CARD 3: THỰC VẬT / TÀI NGUYÊN (COLLAPSIBLE)
        card_herb = ctk.CTkFrame(self.control_frame, fg_color=CARD_BG, border_width=1, border_color=CARD_BORDER, corner_radius=10)
        card_herb.pack(fill="x", padx=16, pady=4)
        
        self.herb_head = ctk.CTkFrame(card_herb, fg_color="transparent")
        self.herb_head.pack(fill="x", padx=10, pady=6)
        self.herb_expanded = False
        self.btn_toggle_herbs = ctk.CTkButton(self.herb_head, text="▶ Thực Vật & Khoáng Sản", width=160, fg_color="transparent", hover_color="#212e3d", text_color="#ffffff", anchor="w", font=ctk.CTkFont(weight="bold", size=11), command=self._toggle_herb_frame)
        self.btn_toggle_herbs.pack(side="left")
        self.all_herbs_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.herb_head, text="Tất cả", variable=self.all_herbs_var, command=self._toggle_all_herbs, checkbox_width=16, checkbox_height=16, font=ctk.CTkFont(size=11)).pack(side="right")
        
        self.herb_frame = ctk.CTkFrame(card_herb, fg_color="transparent")

        # CARD 4: PARTY / ĐỒNG ĐỘI
        card_party = ctk.CTkFrame(self.control_frame, fg_color=CARD_BG, border_width=1, border_color=CARD_BORDER, corner_radius=10)
        card_party.pack(fill="x", padx=16, pady=4)
        
        ctk.CTkLabel(card_party, text="KẾT NỐI TỔ ĐỘI (PARTY)", font=ctk.CTkFont(size=11, weight="bold"), text_color=ACCENT_CYAN).pack(anchor="w", padx=12, pady=(8, 2))
        
        self.entry_api = ctk.CTkEntry(card_party, textvariable=self.api_url_var, height=28, placeholder_text="API Relay Server...")
        self.entry_api.pack(fill="x", padx=10, pady=2)

        name_box = ctk.CTkEntry(card_party, textvariable=self.player_name_var, placeholder_text="Tên của bạn trong Party...", height=28)
        name_box.pack(fill="x", padx=10, pady=2)

        party_row = ctk.CTkFrame(card_party, fg_color="transparent")
        party_row.pack(fill="x", padx=10, pady=2)
        self.entry_party = ctk.CTkEntry(party_row, textvariable=self.party_code_var, width=120, placeholder_text="Mã phòng...", height=28)
        self.entry_party.pack(side="left", padx=(0, 4))
        self.entry_party_pw = ctk.CTkEntry(party_row, textvariable=self.party_pw_var, width=100, placeholder_text="Mật khẩu", show="*", height=28)
        self.entry_party_pw.pack(side="left", padx=(0, 4))
        self.btn_party = ctk.CTkButton(party_row, text="Kết nối", width=70, height=28, fg_color="#0984e3", hover_color="#00cec9", command=self._toggle_party)
        self.btn_party.pack(side="left", fill="x", expand=True)

        party_opts = ctk.CTkFrame(card_party, fg_color="transparent")
        party_opts.pack(fill="x", padx=10, pady=(2, 4))
        ctk.CTkCheckBox(party_opts, text="Chỉ số trên Map", variable=self.show_teammate_vitals_map_var, command=lambda: (self._save_app_config(), self._redraw()), checkbox_width=16, checkbox_height=16, font=ctk.CTkFont(size=10)).pack(side="left")
        ctk.CTkCheckBox(party_opts, text="Chỉ số trên Menu", variable=self.show_teammate_vitals_menu_var, command=lambda: (self._save_app_config(), self._update_teammates_ui()), checkbox_width=16, checkbox_height=16, font=ctk.CTkFont(size=10)).pack(side="right")

        ping_opts = ctk.CTkFrame(card_party, fg_color="transparent")
        ping_opts.pack(fill="x", padx=10, pady=(0, 5))

        ctk.CTkLabel(
            ping_opts, text="Thời gian Ping:",
            text_color=TEXT_MUTED, font=ctk.CTkFont(size=10)
        ).pack(side="left")

        def _party_time_entry(parent, variable, suffix):
            entry = ctk.CTkEntry(
                parent,
                textvariable=variable,
                width=38,
                height=25,
                justify="center"
            )
            entry.pack(side="left", padx=(5, 2))
            ctk.CTkLabel(
                parent,
                text=suffix,
                text_color="#57606f",
                font=ctk.CTkFont(size=9)
            ).pack(side="left")
            entry.bind(
                "<FocusOut>",
                lambda _e: self._normalize_ping_duration(save=True)
            )
            entry.bind(
                "<Return>",
                lambda _e: self._normalize_ping_duration(save=True)
            )
            return entry

        self.entry_ping_hours = _party_time_entry(
            ping_opts, self.ping_duration_hours_var, "giờ"
        )
        self.entry_ping_minutes = _party_time_entry(
            ping_opts, self.ping_duration_minutes_var, "phút"
        )
        self.entry_ping_seconds = _party_time_entry(
            ping_opts, self.ping_duration_seconds_var, "giây"
        )

        manual_ping_frame = ctk.CTkFrame(
            card_party,
            fg_color="#0c1015",
            corner_radius=6,
            border_width=1,
            border_color="#1a2530"
        )
        manual_ping_frame.pack(fill="x", padx=10, pady=(2, 7))

        ctk.CTkLabel(
            manual_ping_frame,
            text="⌖ Manual Coordinate Ping",
            text_color=ACCENT_CYAN,
            font=ctk.CTkFont(size=10, weight="bold")
        ).pack(anchor="w", padx=8, pady=(6, 3))

        manual_coord_row = ctk.CTkFrame(
            manual_ping_frame, fg_color="transparent"
        )
        manual_coord_row.pack(fill="x", padx=8, pady=2)

        self.entry_manual_ping_coord = ctk.CTkEntry(
            manual_coord_row,
            textvariable=self.manual_ping_coord_var,
            placeholder_text="304,333.126, -310,414.508, 22,003.88",
            height=27
        )
        self.entry_manual_ping_coord.pack(
            side="left", fill="x", expand=True
        )

        manual_action_row = ctk.CTkFrame(
            manual_ping_frame, fg_color="transparent"
        )
        manual_action_row.pack(fill="x", padx=8, pady=(2, 7))

        ctk.CTkLabel(
            manual_action_row,
            text="Tồn tại:",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=9)
        ).pack(side="left")

        def _manual_time_entry(parent, variable, suffix):
            entry = ctk.CTkEntry(
                parent,
                textvariable=variable,
                width=34,
                height=25,
                justify="center"
            )
            entry.pack(side="left", padx=(4, 1))
            ctk.CTkLabel(
                parent,
                text=suffix,
                text_color="#57606f",
                font=ctk.CTkFont(size=8)
            ).pack(side="left")
            entry.bind(
                "<FocusOut>",
                lambda _e: self._normalize_manual_ping_duration(save=True)
            )
            entry.bind(
                "<Return>",
                lambda _e: self._normalize_manual_ping_duration(save=True)
            )
            return entry

        self.entry_manual_ping_hours = _manual_time_entry(
            manual_action_row,
            self.manual_ping_duration_hours_var,
            "giờ"
        )
        self.entry_manual_ping_minutes = _manual_time_entry(
            manual_action_row,
            self.manual_ping_duration_minutes_var,
            "phút"
        )
        self.entry_manual_ping_seconds = _manual_time_entry(
            manual_action_row,
            self.manual_ping_duration_seconds_var,
            "giây"
        )

        ctk.CTkButton(
            manual_action_row,
            text="PING",
            width=50,
            height=25,
            command=self._create_manual_coordinate_ping
        ).pack(side="left", padx=(5, 2))

        ctk.CTkButton(
            manual_action_row,
            text="XÓA",
            width=46,
            height=25,
            fg_color="#5b1f24",
            hover_color="#7a2930",
            command=self._clear_manual_ping
        ).pack(side="right")
        self.entry_manual_ping_coord.bind(
            "<Return>",
            lambda _e: self._create_manual_coordinate_ping()
        )

        self.teammates_panel = ctk.CTkFrame(card_party, fg_color="#0c1015", corner_radius=6)

        # Party members must appear ABOVE Manual Coordinate Ping.
        # "before=manual_ping_frame" changes only the UI order; all Party and
        # Manual Ping logic remains unchanged.
        self.teammates_panel.pack(
            fill="x",
            padx=10,
            pady=(2, 8),
            before=manual_ping_frame
        )
        self._update_teammates_ui()

        # CARD 5: BẢN ĐỒ & HỆ THỐNG TELEMETRY
        card_sys = ctk.CTkFrame(self.control_frame, fg_color=CARD_BG, border_width=1, border_color=CARD_BORDER, corner_radius=10)
        card_sys.pack(fill="x", padx=16, pady=4)
        
        ctk.CTkLabel(card_sys, text="HỆ THỐNG & TELEMETRY", font=ctk.CTkFont(size=11, weight="bold"), text_color=ACCENT_CYAN).pack(anchor="w", padx=12, pady=(8, 2))

        self.map_combo = ctk.CTkComboBox(card_sys, values=[p.name for p in self.profiles], command=self._select_profile, height=28)
        self.map_combo.set(self.profile.name)
        self.map_combo.pack(fill="x", padx=10, pady=2)

        self.islepilot_status_var = tk.StringVar(value=self._islepilot_status_text())
        ctk.CTkLabel(card_sys, textvariable=self.islepilot_status_var, text_color=ACCENT_GREEN, font=ctk.CTkFont(size=10)).pack(anchor="w", padx=12, pady=(2, 2))

        islepilot_btns = ctk.CTkFrame(card_sys, fg_color="transparent")
        islepilot_btns.pack(fill="x", padx=10, pady=(0, 4))
        self.btn_islepilot = ctk.CTkButton(islepilot_btns, text="Steam Login", fg_color="#10ac84", hover_color="#1dd1a1", command=self._on_connect_click, height=26)
        self.btn_islepilot.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.btn_islepilot_token = ctk.CTkButton(islepilot_btns, text="Web Token", fg_color="#2c3e50", hover_color="#34495e", command=self._on_manual_token_click, height=26)
        self.btn_islepilot_token.pack(side="right", fill="x", expand=True)

        self.local_status_var = tk.StringVar(value=self._local_status_text())
        ctk.CTkLabel(card_sys, textvariable=self.local_status_var, text_color=TEXT_MUTED, font=ctk.CTkFont(size=10)).pack(anchor="w", padx=12, pady=(2, 2))

        btn_row = ctk.CTkFrame(card_sys, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkButton(btn_row, text="Kiểm tra lại", height=26, fg_color="#2c3e50", hover_color="#34495e", command=lambda: (self._retry_local_telemetry(), self.local_status_var.set(self._local_status_text()))).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(btn_row, text="Cài Npcap", height=26, fg_color="#ee5253", hover_color="#ff6b6b", command=self._install_npcap_async).pack(side="right", fill="x", expand=True)

        footer = ctk.CTkFrame(self.control_frame, fg_color="transparent")
        footer.pack(fill="x", padx=16, pady=10)
        ctk.CTkButton(footer, text="YouTube", width=120, fg_color="#2c3e50", hover_color="#34495e", command=lambda: webbrowser.open(YOUTUBE_URL), height=26).pack(side="left")
        ctk.CTkButton(footer, text="Discord", width=120, fg_color="#5865F2", hover_color="#4752C4", command=lambda: webbrowser.open(DISCORD_URL), height=26).pack(side="right")

        # KHUNG MAP LỚN
        self.map_frame = ctk.CTkFrame(self.root, corner_radius=0)
        self.menu_canvas = tk.Canvas(self.map_frame, background="#0c1015", highlightthickness=0)
        self.menu_canvas.pack(fill="both", expand=True)
        self.menu_canvas.bind("<Configure>", lambda e: self._redraw_menu())
        self.menu_canvas.bind("<MouseWheel>", lambda e: self._on_mouse_wheel(e, False))
        self.menu_canvas.bind("<ButtonPress-1>", lambda e: self._on_pan_start(e, False))
        self.menu_canvas.bind("<B1-Motion>", lambda e: self._on_pan_move(e, False))
        self.menu_canvas.bind("<ButtonRelease-1>", lambda e: self._on_pan_end(e, False))
        self.menu_canvas.bind("<Double-Button-1>", lambda e: self._on_reset_view(e, False))
        self.menu_canvas.bind("<ButtonPress-2>", lambda e: self._on_map_ping(e, False))

        self.ingame_canvas = tk.Canvas(self.ingame_map_window, background="#0c1015", highlightthickness=1.5, highlightbackground=ACCENT_CYAN)
        self.ingame_canvas.pack(fill="both", expand=True)
        self.ingame_canvas.bind("<Configure>", lambda e: self._redraw_ingame())
        self.ingame_canvas.bind("<MouseWheel>", lambda e: self._on_mouse_wheel(e, True))
        self.ingame_canvas.bind("<ButtonPress-1>", lambda e: self._on_pan_start(e, True))
        self.ingame_canvas.bind("<B1-Motion>", lambda e: self._on_pan_move(e, True))
        self.ingame_canvas.bind("<ButtonRelease-1>", lambda e: self._on_pan_end(e, True))
        self.ingame_canvas.bind("<Double-Button-1>", lambda e: self._on_reset_view(e, True))
        self.ingame_canvas.bind("<ButtonPress-2>", lambda e: self._on_map_ping(e, True))
        
        self._update_statuses()

    def _update_teammates_ui(self):
        for widget in self.teammates_panel.winfo_children():
            widget.destroy()

        if not getattr(self, 'is_party_active', False) or not getattr(self, 'teammates', {}):
            ctk.CTkLabel(self.teammates_panel, text="Không có đồng đội trong phòng", text_color="#57606f", font=ctk.CTkFont(size=10)).pack(pady=8)
            return

        for tid, tdata in self.teammates.items():
            tname = tdata.get("name", f"[{tid}]")
            has_pos = tdata.get("has_pos", False)
            tvitals = tdata.get("vitals")

            row = ctk.CTkFrame(self.teammates_panel, fg_color="#141c24", corner_radius=6)
            row.pack(fill="x", padx=6, pady=3)

            top = ctk.CTkFrame(row, fg_color="transparent")
            top.pack(fill="x", padx=6, pady=2)
            dot_col = ACCENT_GREEN if has_pos else "#57606f"
            ctk.CTkLabel(top, text="●", text_color=dot_col, font=ctk.CTkFont(size=8)).pack(side="left", padx=(0, 4))
            ctk.CTkLabel(top, text=tname, font=ctk.CTkFont(weight="bold", size=11), text_color="#ffffff").pack(side="left")

            if tvitals and self.show_teammate_vitals_menu_var.get():
                bars = ctk.CTkFrame(row, fg_color="transparent")
                bars.pack(fill="x", padx=6, pady=(0, 4))
                def make_bar(parent, val, max_val, color):
                    frac = max(0.0, min(1.0, val / max_val)) if max_val else 0
                    bar = ctk.CTkProgressBar(parent, height=3, progress_color=color, fg_color="#212e3d")
                    bar.set(frac)
                    bar.pack(side="top", fill="x", pady=1)

                make_bar(bars, tvitals.get('h', 0), tvitals.get('mh', 1), ACCENT_RED)
                make_bar(bars, tvitals.get('s', 0), tvitals.get('ms', 1), ACCENT_YELLOW)
                make_bar(bars, tvitals.get('f', 0), tvitals.get('mf', 1), ACCENT_ORANGE)
                make_bar(bars, tvitals.get('w', 0), tvitals.get('mw', 1), "#0984e3")

    def _reset_party_ui(self, show_error=None):
        self.is_party_active = False
        self.btn_party.configure(text="Kết nối", fg_color="#0984e3", hover_color="#00cec9")
        self.entry_party.configure(state="normal")
        self.entry_party_pw.configure(state="normal")
        self.entry_api.configure(state="normal")
        self.teammates.clear()
        self._update_teammates_ui()
        self._redraw()
        if show_error: messagebox.showerror("The-Maps", show_error)

    def _toggle_party(self):
        if self.is_party_active:
            self._reset_party_ui()
        else:
            code = self.party_code_var.get().strip()
            if not code:
                messagebox.showwarning("The-Maps", "Vui lòng nhập mã phòng!")
                return
            api_url = self.api_url_var.get().strip()
            if not api_url:
                messagebox.showwarning("The-Maps", "Vui lòng nhập API Server!")
                return
            
            self._save_sv_config()
            self.is_party_active = True
            self.btn_party.configure(text="Ngắt", fg_color=ACCENT_RED, hover_color="#ff6b6b")
            self.entry_party.configure(state="disabled")
            self.entry_party_pw.configure(state="disabled")
            self.entry_api.configure(state="disabled")
            threading.Thread(target=self._party_sync_loop, daemon=True).start()

    @staticmethod
    def _parse_hms_component(value, default: int = 0) -> int:
        try:
            parsed = int(float(str(value).strip()))
        except (TypeError, ValueError):
            parsed = default
        return max(0, parsed)

    @staticmethod
    def _seconds_to_hms(total_seconds: int) -> tuple[int, int, int]:
        total_seconds = max(1, int(total_seconds))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return hours, minutes, seconds

    def _get_manual_ping_duration_seconds(self) -> int:
        hours = self._parse_hms_component(
            self.manual_ping_duration_hours_var.get()
        )
        minutes = self._parse_hms_component(
            self.manual_ping_duration_minutes_var.get()
        )
        seconds = self._parse_hms_component(
            self.manual_ping_duration_seconds_var.get()
        )

        # Normalize values such as 0h 90m 90s naturally through total seconds.
        total = hours * 3600 + minutes * 60 + seconds

        # Minimum 1 second, maximum 6 hours.
        return max(1, min(6 * 3600, total))

    def _normalize_manual_ping_duration(self, save: bool = False) -> int:
        total = self._get_manual_ping_duration_seconds()
        hours, minutes, seconds = self._seconds_to_hms(total)

        self.manual_ping_duration_hours_var.set(str(hours))
        self.manual_ping_duration_minutes_var.set(str(minutes))
        self.manual_ping_duration_seconds_var.set(str(seconds))

        if save:
            try:
                self._save_app_config()
            except Exception:
                pass

        return total

    @staticmethod
    def _parse_manual_ping_coordinate(raw: str) -> Position | None:
        """
        Accept The Isle coordinates where commas inside numbers are
        thousands separators, for example:

            304,333.126, -310,414.508
            304,333.126, -310,414.508, 22,003.88
        """
        raw = str(raw or "").strip()
        if not raw:
            return None

        # Same number grammar as the game coordinate parser.
        number_re = re.compile(
            r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
        )

        matches = list(number_re.finditer(raw))
        if len(matches) not in (2, 3):
            return None

        # Everything between coordinate numbers must only be the coordinate
        # separator: comma + optional whitespace. This prevents accepting
        # unrelated text while still preserving commas INSIDE the numbers.
        cursor = 0
        for index, match in enumerate(matches):
            gap = raw[cursor:match.start()]

            if index == 0:
                if gap.strip():
                    return None
            else:
                if re.fullmatch(r"\s*,\s*", gap) is None:
                    return None

            cursor = match.end()

        if raw[cursor:].strip():
            return None

        try:
            values = [
                float(match.group(0).replace(",", ""))
                for match in matches
            ]
        except (TypeError, ValueError):
            return None

        if len(values) == 2:
            values.append(0.0)

        x, y, z = values
        if not all(math.isfinite(v) for v in (x, y, z)):
            return None

        return Position(x, y, z)

    def _create_manual_coordinate_ping(self) -> None:
        pos = self._parse_manual_ping_coordinate(
            self.manual_ping_coord_var.get()
        )
        if pos is None:
            messagebox.showwarning(
                "Manual Ping",
                "Tọa độ không hợp lệ.\n\n"
                "Hỗ trợ XY hoặc XYZ theo format của game.\n"
                "Ví dụ:\n"
                "304,333.126, -310,414.508\n"
                "hoặc\n"
                "304,333.126, -310,414.508, 22,003.88"
            )
            return

        duration_seconds = self._normalize_manual_ping_duration(save=True)
        now = time.time()

        self.manual_active_ping = {
            "pos": pos,
            "created_at": now,
            "expires_at": now + duration_seconds,
            "duration_seconds": duration_seconds,
            # Keep duration_min for compatibility with older rendering/code.
            "duration_min": duration_seconds / 60.0,
        }

        self._redraw()
        self._apply_focus_visibility()

    def _create_asset_location_ping(self, position: Position) -> None:
        duration_seconds = self._get_manual_ping_duration_seconds()
        now = time.time()
        self.asset_location_active_ping = {
            "pos": position,
            "created_at": now,
            "expires_at": now + duration_seconds,
            "duration_seconds": duration_seconds,
            "duration_min": duration_seconds / 60.0,
        }
        self._redraw()
        self._apply_focus_visibility()

    def _clear_asset_location_ping(self) -> None:
        self.asset_location_active_ping = None
        self._redraw()
        self._apply_focus_visibility()

    def _asset_location_ping_is_active(self) -> bool:
        ping = getattr(self, "asset_location_active_ping", None)
        if not ping:
            return False
        if self._ping_is_expired(ping):
            self.asset_location_active_ping = None
            return False
        return True

    def _clear_manual_ping(self) -> None:
        self.manual_active_ping = None
        self._redraw()
        self._apply_focus_visibility()

    def _manual_ping_is_active(self) -> bool:
        ping = getattr(self, "manual_active_ping", None)
        if not ping:
            return False

        if self._ping_is_expired(ping):
            self.manual_active_ping = None
            return False

        return True

    def _get_ping_duration_seconds(self) -> int:
        hours = self._parse_hms_component(
            self.ping_duration_hours_var.get()
        )
        minutes = self._parse_hms_component(
            self.ping_duration_minutes_var.get()
        )
        seconds = self._parse_hms_component(
            self.ping_duration_seconds_var.get()
        )

        total = hours * 3600 + minutes * 60 + seconds
        # Minimum 1 second, maximum 6 hours.
        return max(1, min(6 * 3600, total))

    def _normalize_ping_duration(self, save: bool = False) -> int:
        total = self._get_ping_duration_seconds()
        hours, minutes, seconds = self._seconds_to_hms(total)

        self.ping_duration_hours_var.set(str(hours))
        self.ping_duration_minutes_var.set(str(minutes))
        self.ping_duration_seconds_var.set(str(seconds))

        if save:
            try:
                self._save_app_config()
            except Exception:
                pass

        return total

    @staticmethod
    def _ping_is_expired(ping: dict | None, now: float | None = None) -> bool:
        if not ping:
            return True
        expires_at = ping.get("expires_at") if isinstance(ping, dict) else None
        if expires_at is None:
            return False
        try:
            return float(expires_at) <= (time.time() if now is None else now)
        except (TypeError, ValueError):
            return False

    def _clear_my_ping(self) -> None:
        if self.my_active_ping is None:
            return
        self.my_active_ping = None
        self._redraw()
        ping_hud = getattr(self, "_ping_direction_hud", None)
        if ping_hud is not None:
            try:
                ping_hud.update(
                    self.profile,
                    self.current,
                    self._current_heading_degrees(),
                    self.teammates if self.is_party_active else {},
                    None,
                )
            except Exception:
                pass


    def _party_sync_loop(self):
        empty_room_counter = 0
        while self.is_party_active:
            game_x = self.current.y if self.current else 999999.0
            game_y = self.current.x if self.current else 999999.0
            yaw = self._current_heading_degrees() or 0.0 if self.current else 0.0

            current_time = time.time()
            if self.my_active_ping and self._ping_is_expired(self.my_active_ping, current_time):
                self.my_active_ping = None
                self.root.after(0, self._redraw)

            ping_payload = None
            if self.my_active_ping:
                ping_payload = {
                    "x": self.my_active_ping["pos"].x,
                    "y": self.my_active_ping["pos"].y,
                    "created_at": self.my_active_ping.get("created_at", self.my_active_ping.get("time", current_time)),
                    "expires_at": self.my_active_ping.get("expires_at"),
                    "duration_min": self.my_active_ping.get("duration_min"),
                }

            payload = {
                "room_code": self.party_code_var.get().strip(),
                "password": self.party_pw_var.get().strip(),
                "player_id": self.player_id,
                "name": self.player_name_var.get().strip() or self.player_id,
                "x": game_x,
                "y": game_y,
                "yaw": yaw,
                "ping": ping_payload,
                "vitals": self.last_vitals
            }
            
            target_url = self.api_url_var.get().strip()
            try:
                resp = requests.post(target_url, json=payload, timeout=3)
                if resp.status_code == 200:
                    data = resp.json().get("teammates", [])
                    valid_teammates = {}
                    for t in data:
                        has_pos = (t["x"] != 999999.0 and t["y"] != 999999.0)
                        teammate_ping = t.get("ping")
                        if teammate_ping and self._ping_is_expired(teammate_ping, current_time):
                            teammate_ping = None
                        valid_teammates[t["id"]] = {
                            "name": t.get("name", t["id"]),
                            "pos": Position(t["y"], t["x"], 0.0) if has_pos else None, 
                            "yaw": t["yaw"],
                            "ping": teammate_ping,
                            "vitals": t.get("vitals"),
                            "has_pos": has_pos
                        }
                    
                    if str(self.teammates) != str(valid_teammates):
                        self.teammates = valid_teammates
                        self.root.after(0, self._update_teammates_ui)
                        self.root.after(0, self._redraw)

                    if not valid_teammates: empty_room_counter += 1
                    else: empty_room_counter = 0
                elif resp.status_code == 403:
                    self.root.after(0, lambda: self._reset_party_ui("Sai mật khẩu phòng!"))
                    break
            except Exception: pass
            time.sleep(3 if empty_room_counter > 0 else 1)

    def _on_map_ping(self, event, is_ingame=False) -> None:
        view = self.ig_view if is_ingame else self.m_view
        c_w = self.ig_canvas_w if is_ingame else self.m_canvas_w
        c_h = self.ig_canvas_h if is_ingame else self.m_canvas_h
        x_off = self.ig_x_offset if is_ingame else self.m_x_offset
        y_off = self.ig_y_offset if is_ingame else self.m_y_offset
        rect = self.ig_placeholder_rect if is_ingame else self.m_placeholder_rect

        real_x = event.x - x_off
        real_y = event.y - y_off

        if view is None and rect is not None:
            left, top, width, height = rect
            if 0 <= real_x - left <= width and 0 <= real_y - top <= height:
                nx = (real_x - left) / width
                ny = (real_y - top) / height
            else: return
        elif view is not None:
            if not (0 <= real_x <= c_w and 0 <= real_y <= c_h): return
            view_left, view_top, view_w, view_h = view
            nx = view_left + (real_x / c_w) * view_w
            ny = view_top + (real_y / c_h) * view_h
        else: return

        wx, wy = self.profile.from_normalized(nx, ny)
        duration_seconds = self._normalize_ping_duration(save=True)
        created_at = time.time()
        self.my_active_ping = {
            "pos": Position(wx, wy, 0.0),
            "time": created_at,
            "created_at": created_at,
            "expires_at": created_at + duration_seconds,
            "duration_seconds": duration_seconds,
            # Kept for compatibility with Party payload/server versions.
            "duration_min": duration_seconds / 60.0,
        }
        self._redraw()

    def _update_statuses(self):
        self.local_status_var.set(self._local_status_text())
        self.islepilot_status_var.set(self._islepilot_status_text())
        
        if self._islepilot_connected():
            self.btn_islepilot.configure(text="Ngắt kết nối", state="normal")
            if hasattr(self, 'btn_islepilot_token'):
                self.btn_islepilot_token.configure(state="disabled")
        else:
            self.btn_islepilot.configure(text="Steam Login", state="normal")
            if hasattr(self, 'btn_islepilot_token'):
                self.btn_islepilot_token.configure(state="normal")
                
        self.root.after(500, self._update_statuses)

    def _on_hotkey_change(self, choice: str) -> None:
        self.current_hotkey_name = choice
        self.current_hotkey_vk = HOTKEYS[choice]
        self._save_app_config()
        if self.map_visible:
            self.btn_toggle_map.configure(text=f"ẨN BẢN ĐỒ CHI TIẾT [{self.current_hotkey_name}]")
        else:
            self.btn_toggle_map.configure(text=f"MỞ BẢN ĐỒ CHI TIẾT [{self.current_hotkey_name}]")

    def _on_ingame_hotkey_change(self, choice: str) -> None:
        self.ingame_hotkey_name = choice
        self.ingame_hotkey_vk = HOTKEYS[choice]
        self._save_app_config()

    def _on_move_hotkey_change(self, choice: str) -> None:
        self.move_hotkey_name = choice
        self.move_hotkey_vk = HOTKEYS[choice]
        self._save_app_config()

    def _on_opacity_change(self, value: float) -> None:
        self.minimap_opacity = value
        if getattr(self, '_hud', None):
            self._hud.minimap.set_opacity(value)
            self._hud.vitals.set_opacity(value)
            self._hud.quests.set_opacity(value)
        self._save_app_config()

    def _on_shape_change(self, value: str) -> None:
        self.minimap_shape = value
        self._save_app_config()
        if getattr(self, '_hud', None) and self.current:
            heading = self._current_heading_degrees()
            if heading is None: heading = 0.0
            self._hud.update_map(
                self.source_image, self.profile, self.current.x, self.current.y, heading,
                zone_images=self._active_zone_images(), path_history=self.path_history,
                show_regions=self.show_regions_var.get(), shape=self.minimap_shape, teammates=self.teammates, map_app_ref=self
            )

    def _on_region_toggle(self) -> None:
        self._save_app_config()
        self._redraw()

    def _on_focus_mode_change(self) -> None:
        self._save_app_config()
        self._apply_focus_visibility()

    def _on_asset_location_ping_toggle(self) -> None:
        self._save_app_config()

    def _on_hud_toggle(self) -> None:
        self._save_app_config()
        if getattr(self, '_hud', None) is not None:
            self._apply_focus_visibility()

    def _on_connect_click(self):
        if self._islepilot_connected():
            self._islepilot_disconnect()
        else:
            self.btn_islepilot.configure(state="disabled")
            self.islepilot_status_var.set("Đang mở cửa sổ đăng nhập Steam…")
            self._islepilot_login_async(lambda: self.btn_islepilot.configure(state="normal"))

    def _on_manual_token_click(self):
        if self._islepilot_connected():
            self._islepilot_disconnect()
        else:
            dialog = ctk.CTkInputDialog(text="Dán Token lấy từ trang web IslePilot vào đây:", title="Nhập Token IslePilot")
            token = dialog.get_input()
            if token and token.strip():
                self.btn_islepilot_token.configure(state="disabled")
                self.btn_islepilot.configure(state="disabled")
                self.islepilot_status_var.set("Đang kết nối bằng Token...")
                steam_id = "ManualWeb"
                islepilot.save_credentials(self._islepilot_cred_path, steam_id, token.strip())
                self._islepilot_start_session(steam_id, token.strip())

    def _toggle_ingame_map(self) -> None:
        if self.ingame_map_visible:
            # User explicitly turned the in-game map OFF.
            self.ingame_map_window.withdraw()
            self.ingame_map_visible = False
            self._ingame_map_focus_hidden = False
        else:
            if self.map_visible:
                self._toggle_map_view()

            # User explicitly turned the in-game map ON.
            self.ingame_map_visible = True
            self._ingame_map_focus_hidden = False

            # Respect the selected HUD/Map focus mode immediately.
            if self._focus_allows_hud():
                self.ingame_map_window.deiconify()
                self.ingame_map_window.lift()
                self._set_window_noactivate(self.ingame_map_window)
                self._redraw_ingame()
            else:
                self.ingame_map_window.withdraw()
                self._ingame_map_focus_hidden = True

    def _toggle_map_view(self) -> None:
        if getattr(self, 'ingame_map_visible', False):
            self._toggle_ingame_map()
            
        hk_text = self.current_hotkey_name
        if self.map_visible:
            self.map_frame.pack_forget()
            self.root.geometry("420x940")
            self.root.resizable(False, False)
            self.btn_toggle_map.configure(text=f"MỞ BẢN ĐỒ CHI TIẾT [{hk_text}]", fg_color="#0984e3", hover_color="#00cec9")
            self.map_visible = False
        else:
            self.root.geometry("1180x940")
            self.root.resizable(True, True) 
            self.map_frame.pack(side="right", fill="both", expand=True, padx=(4, 0))
            self.btn_toggle_map.configure(text=f"ẨN BẢN ĐỒ CHI TIẾT [{hk_text}]", fg_color=ACCENT_RED, hover_color="#ff6b6b")
            self.map_visible = True
            self._redraw_menu()

    def _poll_global_escape_event(self) -> None:
        if self.global_escape.is_set():
            self.global_escape.clear()
            self._toggle_map_view()
        if getattr(self, 'ingame_escape', None) and self.ingame_escape.is_set():
            self.ingame_escape.clear()
            self._toggle_ingame_map()
        self.root.after(20, self._poll_global_escape_event)

    def _show_map(self) -> None:
        if getattr(self, 'ingame_map_visible', False):
            self._toggle_ingame_map()
        if not self.map_visible:
            self._toggle_map_view()
        self.root.deiconify()
        self.root.lift()

    def _start_tray(self) -> None:
        if APP_ICON_PNG.exists(): image = Image.open(APP_ICON_PNG).convert("RGBA")
        else: image = Image.new("RGBA", (64, 64), "#0c1015")
        menu = pystray.Menu(pystray.MenuItem("Mở The-Maps", self._tray_open), pystray.MenuItem("Thoát", self._tray_exit))
        self.tray_icon = pystray.Icon("The-Maps", image, "The-Maps", menu)
        self.tray_icon.run_detached()

    def _tray_open(self, _icon=None, _item=None) -> None:
        self.root.after(0, self.root.deiconify)
        self.root.after(0, self.root.lift)

    def _tray_exit(self, _icon=None, _item=None) -> None:
        self.root.after(0, self._exit)

    def _exit(self) -> None:
        if getattr(self, 'tray_icon', None): self.tray_icon.stop()
        self._islepilot_stop_session()
        self._stop_local_telemetry()
        self.root.destroy()

    def _keyboard_hook_loop(self) -> None:
        class KeyboardEvent(ctypes.Structure):
            _fields_ = (("vk_code", wintypes.DWORD), ("scan_code", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("extra_info", ctypes.c_size_t))
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hook_proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        
        @hook_proc_type
        def keyboard_hook(code, message, data):
            if code >= 0 and message in (0x0100, 0x0104):
                event = ctypes.cast(data, ctypes.POINTER(KeyboardEvent)).contents
                current_time = time.time()
                if event.vk_code == self.current_hotkey_vk:
                    if current_time - getattr(self, '_last_menu_toggle', 0) > 0.3:
                        self._last_menu_toggle = current_time
                        self.global_escape.set()
                elif event.vk_code == getattr(self, 'ingame_hotkey_vk', None):
                    if current_time - getattr(self, '_last_ig_toggle', 0) > 0.3:
                        self._last_ig_toggle = current_time
                        self.ingame_escape.set()
                elif event.vk_code == self.move_hotkey_vk:
                    if current_time - getattr(self, '_last_move_toggle', 0) > 0.3:
                        self._last_move_toggle = current_time
                        if getattr(self, '_hud', None) is not None:
                            self.root.after(0, self._hud.toggle_move_mode)
            return user32.CallNextHookEx(None, code, message, data)
            
        kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        user32.SetWindowsHookExW.argtypes = (ctypes.c_int, hook_proc_type, ctypes.c_void_p, wintypes.DWORD)
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.argtypes = (ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        hook = user32.SetWindowsHookExW(13, keyboard_hook, kernel32.GetModuleHandleW(None), 0)
        if not hook: return
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

    def _select_profile(self, selected_name: str) -> None:
        self.profile = next(p for p in self.profiles if p.name == selected_name)
        self._local_heading_deg = None
        self._islepilot_heading_deg = None
        self.path_history.clear()
        self._save_app_config()
        self._load_map_image()
        self._redraw()

    def _local_position_fresh(self) -> bool:
        return (self._local_last_update > 0.0 and time.monotonic() - self._local_last_update <= LOCAL_POSITION_FRESH_SECONDS)

    def _local_status_text(self) -> str:
        labels = {"starting": "Local telemetry: Đang khởi động...", "npcap_missing": "Local telemetry: Thiếu Npcap", "waiting_game": "Local telemetry: Chờ game The Isle", "waiting_packets": "Local telemetry: Chờ dữ liệu di chuyển", "tracking": "Local telemetry: Hoạt động (Realtime)", "capture_error": "Local telemetry: Lỗi Npcap"}
        return labels.get(self._local_state, f"Local: {self._local_state}")

    def _start_local_telemetry(self) -> None:
        self._stop_local_telemetry()
        def on_sample(sample: localtelemetry.LocalMovementSample) -> None:
            self.root.after(0, lambda s=sample: self._apply_local_movement(s))
        def on_state(state: str) -> None:
            self.root.after(0, lambda s=state: self._set_local_state(s))
        self._local_session = localtelemetry.LocalMovementSession(on_sample, on_state)
        self._local_session.start()

    def _stop_local_telemetry(self) -> None:
        if getattr(self, '_local_session', None) is not None:
            self._local_session.stop()
            self._local_session = None

    def _set_local_state(self, state: str) -> None:
        self._local_state = state

    def _prompt_for_npcap_if_needed(self) -> None:
        if self._npcap_prompted or localtelemetry.npcap_installed(): return
        self._npcap_prompted = True
        if messagebox.askyesno("The-Maps Telemetry", "Minimap realtime cần Npcap để đọc dữ liệu vị trí mượt hơn.\nCài đặt Npcap ngay?"):
            self._install_npcap_async()

    def _install_npcap_async(self) -> None:
        if localtelemetry.npcap_installed():
            messagebox.showinfo("The-Maps", "Npcap đã được cài đặt.")
            self._retry_local_telemetry()
            return
        progress_window = tk.Toplevel(self.root)
        progress_window.title("Cài đặt Npcap")
        progress_window.resizable(False, False)
        progress_window.protocol("WM_DELETE_WINDOW", lambda: None)
        frame = ttk.Frame(progress_window, padding=16)
        frame.pack(fill="both", expand=True)
        status_var = tk.StringVar(value="Đang kết nối npcap.com...")
        ttk.Label(frame, textvariable=status_var, width=50).pack(anchor="w")
        progress = ttk.Progressbar(frame, length=380, mode="indeterminate")
        progress.pack(fill="x", pady=(10, 0))
        progress.start(12)

        def set_status(text: str) -> None: self.root.after(0, lambda: status_var.set(text))
        def on_progress(downloaded: int, total: int | None) -> None:
            if total and total > 0: set_status(f"Đang tải Npcap: {min(100.0, downloaded * 100.0 / total):.0f}%")
            else: set_status(f"Đang tải Npcap: {downloaded / 1024:.0f} KB")

        def worker() -> None:
            reboot_required = False
            try: success, message, reboot_required = localtelemetry.install_npcap_from_official_site(on_progress)
            except Exception as exc: success, message = False, str(exc)
            def finish() -> None:
                if progress_window.winfo_exists(): progress.stop(); progress_window.destroy()
                if success and reboot_required: messagebox.showinfo("The-Maps", f"{message}\nKhởi động lại máy để kích hoạt.")
                elif success: messagebox.showinfo("The-Maps", message); self._retry_local_telemetry()
                else: messagebox.showerror("The-Maps", f"Không cài được Npcap:\n{message}")
            self.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    def _retry_local_telemetry(self) -> None:
        self._local_state = "starting"
        self._start_local_telemetry()

    def _apply_local_movement(self, sample: localtelemetry.LocalMovementSample) -> None:
        self._local_last_update = time.monotonic()
        self._local_state = "tracking"
        position = Position(sample.y, sample.x, sample.z)
        
        if position != self.current and self._local_last_update - self._local_trail_last_update >= LOCAL_TRAIL_MIN_INTERVAL_SECONDS:
            if self.current:
                self.path_history.append(self.current)
                if len(self.path_history) > MAX_HISTORY_POINTS:
                    self.path_history.pop(0)
            self._local_trail_last_update = self._local_last_update
            
        self.current = position
        self._local_heading_deg = self.profile.transform_yaw(sample.yaw)
        
        if getattr(self, '_hud', None) is None: self._hud = IslePilotHud(self.root, opacity=self.minimap_opacity)
        self._hud.update_map(self.source_image, self.profile, position.x, position.y, self._local_heading_deg, zone_images=self._active_zone_images(), path_history=self.path_history, show_regions=self.show_regions_var.get(), shape=self.minimap_shape, teammates=self.teammates, map_app_ref=self)
        if getattr(self, 'map_visible', False) or getattr(self, 'ingame_map_visible', False): self._redraw()

    def _islepilot_status_text(self) -> str:
        if getattr(self, '_islepilot_steam_id', None):
            if self._islepilot_steam_id == "ManualWeb": return "● IslePilot: Web Token Active"
            return f"● IslePilot: Steam Connected (...{self._islepilot_steam_id[-4:]})"
        return "○ IslePilot: Chưa kết nối"

    def _islepilot_connected(self) -> bool: return getattr(self, '_islepilot_steam_id', None) is not None

    def _islepilot_login_async(self, on_done) -> None:
        if getattr(self, '_islepilot_logging_in', False): return
        self._islepilot_logging_in = True
        def worker() -> None:
            result = islepilot.run_login_subprocess()
            def finish() -> None:
                self._islepilot_logging_in = False
                if result is not None:
                    steam_id, token = result
                    islepilot.save_credentials(self._islepilot_cred_path, steam_id, token)
                    self._islepilot_start_session(steam_id, token)
                on_done()
            self.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    def _islepilot_start_session(self, steam_id: str, token: str) -> None:
        self._islepilot_stop_session()
        self._islepilot_steam_id = steam_id
        self._islepilot_heading_deg = None
        self._islepilot_online = False
        def on_status(status: islepilot.IslePilotStatus) -> None: self.root.after(0, lambda: self._apply_islepilot_status(status))
        def on_error(_reason: str) -> None: self.root.after(0, self._islepilot_handle_expired)
        self._islepilot_session = islepilot.IslePilotSession(token, on_status, on_error)
        self._islepilot_session.start()
        if getattr(self, '_hud', None) is None: self._hud = IslePilotHud(self.root, opacity=self.minimap_opacity)

    def _islepilot_stop_session(self) -> None:
        if getattr(self, '_islepilot_session', None) is not None:
            self._islepilot_session.stop()
            self._islepilot_session = None

    def _islepilot_disconnect(self) -> None:
        self._islepilot_stop_session()
        islepilot.clear_credentials(self._islepilot_cred_path)
        self._islepilot_steam_id = None
        self._islepilot_heading_deg = None
        self._islepilot_online = False
        if getattr(self, '_hud', None) is not None:
            self._hud.hide()
            self._hud.destroy()
            self._hud = None

    def _islepilot_handle_expired(self) -> None:
        was_connected = self._islepilot_connected()
        self._islepilot_disconnect()
        if was_connected: messagebox.showwarning("The-Maps", "Phiên IslePilot đã hết hạn.")

    def _apply_islepilot_status(self, status: islepilot.IslePilotStatus) -> None:
        self._islepilot_online = status.online
        self.last_vitals = {
            "h": getattr(status, 'health', 0), "mh": getattr(status, 'max_health', 1),
            "s": getattr(status, 'stamina', 0), "ms": getattr(status, 'max_stamina', 1),
            "w": getattr(status, 'thirst', 0), "mw": getattr(status, 'max_thirst', 1),
            "f": getattr(status, 'hunger', 0), "mf": getattr(status, 'max_hunger', 1)
        }

        if getattr(self, '_hud', None) is None and (status.online or self._local_position_fresh()): 
            self._hud = IslePilotHud(self.root, opacity=self.minimap_opacity)
        if getattr(self, '_hud', None) is not None:
            self._hud.update_vitals(status)
            self._hud.update_quests(status)
        if self._local_position_fresh(): return
        
        heading_changed = False
        if status.pos_yaw is not None:
            new_heading = self.profile.transform_yaw(status.pos_yaw)
            heading_changed = new_heading != getattr(self, '_islepilot_heading_deg', None)
            self._islepilot_heading_deg = new_heading
            
        position: Position | None = None
        position_changed = False
        if status.pos_x is not None and status.pos_y is not None:
            position = Position(status.pos_y, status.pos_x, status.pos_z or 0.0)
            if position != self.current:
                if self.current:
                    self.path_history.append(self.current)
                    if len(self.path_history) > MAX_HISTORY_POINTS:
                        self.path_history.pop(0)
                self.current = position
                position_changed = True
                
        if (position_changed or heading_changed) and (getattr(self, 'map_visible', False) or getattr(self, 'ingame_map_visible', False)): 
            self._redraw()
            
        draw_position = position or self.current
        if getattr(self, '_hud', None) is not None and draw_position is not None:
            heading = getattr(self, '_islepilot_heading_deg', 0.0) if getattr(self, '_islepilot_heading_deg', None) is not None else 0.0
            self._hud.update_map(self.source_image, self.profile, draw_position.x, draw_position.y, heading, zone_images=self._active_zone_images(), path_history=self.path_history, show_regions=self.show_regions_var.get(), shape=self.minimap_shape, teammates=self.teammates, map_app_ref=self)

    def _apply_focus_visibility(self) -> None:
        if (
            getattr(self, "manual_active_ping", None)
            and self._ping_is_expired(self.manual_active_ping)
        ):
            self.manual_active_ping = None
            self._redraw()

        if (
            getattr(self, "asset_location_active_ping", None)
            and self._ping_is_expired(self.asset_location_active_ping)
        ):
            self.asset_location_active_ping = None
            self._redraw()

        local_live = self._local_position_fresh()
        has_live_source = local_live or getattr(self, '_islepilot_online', False)
        focus_allowed = self._focus_allows_hud()

        # In-game Map dùng cùng rule với HUD.
        if getattr(self, 'ingame_map_visible', False):
            if focus_allowed:
                if getattr(self, '_ingame_map_focus_hidden', False):
                    self.ingame_map_window.deiconify()
                    self.ingame_map_window.lift()
                    self._set_window_noactivate(self.ingame_map_window)
                    self._ingame_map_focus_hidden = False
                    self._redraw_ingame()
            else:
                if not getattr(self, '_ingame_map_focus_hidden', False):
                    self.ingame_map_window.withdraw()
                    self._ingame_map_focus_hidden = True
        else:
            self._ingame_map_focus_hidden = False

        # Main HUD.
        if getattr(self, '_hud', None) is not None:
            if has_live_source and focus_allowed:
                self._hud.show(
                    show_minimap=self.show_minimap_var.get(),
                    show_vitals=self.show_vitals_var.get(),
                    show_quests=(
                        self.show_quests_var.get()
                        and getattr(self, '_islepilot_online', False)
                    )
                )
            else:
                self._hud.hide()

        # Directional Ping HUD.
        ping_hud = getattr(self, '_ping_direction_hud', None)
        if ping_hud is not None:
            if has_live_source and focus_allowed and self.current is not None:
                count = ping_hud.update(
                    self.profile,
                    self.current,
                    self._current_heading_degrees(),
                    self.teammates if self.is_party_active else {},
                    self.my_active_ping,
                    self.manual_active_ping,
                    self.asset_location_active_ping
                )
                if count > 0:
                    ping_hud.show()
                else:
                    ping_hud.hide()
            else:
                ping_hud.hide()

    def _poll_hud_visibility(self) -> None:
        self._apply_focus_visibility()
        self.root.after(
            FOREGROUND_POLL_MS,
            self._poll_hud_visibility
        )

    def _check_for_update(self) -> None:
        threading.Thread(target=self._check_for_update_worker, daemon=True).start()
        self.root.after(UPDATE_CHECK_INTERVAL_MS, self._check_for_update)

    def _check_for_update_worker(self) -> None:
        try:
            response = requests.get(GITHUB_RELEASE_API, timeout=8.0, headers={"Accept": "application/vnd.github+json"})
            response.raise_for_status()
            latest_tag = response.json().get("tag_name")
        except (requests.RequestException, ValueError, OSError): return
        if latest_tag and latest_tag != RELEASE_TAG: self.root.after(0, lambda: self._notify_update_available(latest_tag))

    def _notify_update_available(self, latest_tag: str) -> None:
        if getattr(self, '_update_notified', False): return
        self._update_notified = True
        if messagebox.askyesno("The-Maps", f"Có bản cập nhật mới ({latest_tag}). Tải ngay?"):
            webbrowser.open(GITHUB_RELEASE_PAGE)

    def _load_map_image(self) -> None:
        self.m_zoom = self.ig_zoom = MIN_ZOOM
        self.m_center_nx = self.ig_center_nx = 0.5
        self.m_center_ny = self.ig_center_ny = 0.5
        self.m_view = self.ig_view = None
        self._m_pan_last = self._ig_pan_last = None
        self._m_pending_hq_job = self._ig_pending_hq_job = None
        self.m_x_offset = self.ig_x_offset = 0.0
        self.m_y_offset = self.ig_y_offset = 0.0
        self.m_canvas_w = self.ig_canvas_w = 1
        self.m_canvas_h = self.ig_canvas_h = 1
        self.m_placeholder_rect = self.ig_placeholder_rect = None
        self.m_map_image = self.ig_map_image = None
        self.m_rendered_size = self.ig_rendered_size = None
        
        if getattr(self.profile, 'image_path', None):
            try:
                # Ảnh map chính lấy từ "image" trong map.json.
                # Kích thước thật của ảnh map này là kích thước chuẩn
                # cho toàn bộ image overlay / ZONE_LAYERS.
                self.source_image = Image.open(
                    self.profile.image_path
                ).convert("RGB")
            except (OSError, ValueError):
                self.source_image = None

        self._zone_images = {}

        # AUTO RESIZE TẤT CẢ IMAGE LAYER THEO KÍCH THƯỚC MAP
        map_size = (
            self.source_image.size
            if self.source_image is not None
            else None
        )

        for key, path in self.profile.zone_image_paths.items():
            try:
                layer_image = Image.open(path).convert("RGBA")

                if (
                    map_size is not None
                    and layer_image.size != map_size
                ):
                    layer_image = layer_image.resize(
                        map_size,
                        Image.Resampling.LANCZOS
                    )

                self._zone_images[key] = layer_image

            except (OSError, ValueError):
                pass

    def _poll_clipboard(self) -> None:
        try:
            sequence = ctypes.windll.user32.GetClipboardSequenceNumber()
            if sequence != self.last_clipboard_sequence:
                self.last_clipboard_sequence = sequence
                text = self.root.clipboard_get()
                self.last_clipboard = text
                self._accept_clipboard(text)
        except tk.TclError: pass
        self.root.after(self.POLL_MS, self._poll_clipboard)

    def _accept_clipboard(self, text: str) -> None:
        position = parse_coordinate(text)
        if position is None:
            return

        asset_mode = bool(
            getattr(self, "asset_location_ping_enabled_var", None)
            and self.asset_location_ping_enabled_var.get()
        )

        if asset_mode:
            if position != self.current:
                if self.current:
                    self.path_history.append(self.current)
                    if len(self.path_history) > MAX_HISTORY_POINTS:
                        self.path_history.pop(0)
                self.current = position
                if not self._islepilot_connected() and not self._local_position_fresh():
                    self._islepilot_heading_deg = None
                    self._local_heading_deg = None

            # IMPORTANT: create ping only; do not call _show_map().
            self._create_asset_location_ping(position)
            return

        if position == self.current:
            self._show_map()
            return

        if self.current:
            self.path_history.append(self.current)
            if len(self.path_history) > MAX_HISTORY_POINTS:
                self.path_history.pop(0)

        self.current = position
        if not self._islepilot_connected() and not self._local_position_fresh():
            self._islepilot_heading_deg = None
            self._local_heading_deg = None
        self._show_map()

    def _redraw(self):
        if getattr(self, 'map_visible', False): self._redraw_menu()
        if getattr(self, 'ingame_map_visible', False): self._redraw_ingame()

    def _redraw_menu(self, resample: int | None = None) -> None:
        if not getattr(self, 'map_visible', False): return
        self._render_map(self.menu_canvas, False, resample)

    def _redraw_ingame(self, resample: int | None = None) -> None:
        if not getattr(self, 'ingame_map_visible', False): return
        self._render_map(self.ingame_canvas, True, resample)

    def _render_map(self, canvas: tk.Canvas, is_ingame: bool, resample: int | None = None) -> None:
        zoom = self.ig_zoom if is_ingame else self.m_zoom
        center_nx = self.ig_center_nx if is_ingame else self.m_center_nx
        center_ny = self.ig_center_ny if is_ingame else self.m_center_ny
        rendered_size = self.ig_rendered_size if is_ingame else self.m_rendered_size
        
        c_w, c_h = max(canvas.winfo_width(), 1), max(canvas.winfo_height(), 1)
        canvas.delete("all")

        view_w = view_h = 1.0 / zoom
        max_left, max_top = max(0.0, 1.0 - view_w), max(0.0, 1.0 - view_h)
        left = min(max(center_nx - view_w / 2, 0.0), max_left)
        top = min(max(center_ny - view_h / 2, 0.0), max_top)
        center_nx, center_ny = left + view_w / 2, top + view_h / 2
        view = (left, top, view_w, view_h)
        
        if is_ingame:
            self.ig_center_nx, self.ig_center_ny = center_nx, center_ny
            self.ig_view = view
        else:
            self.m_center_nx, self.m_center_ny = center_nx, center_ny
            self.m_view = view

        if getattr(self, 'source_image', None):
            source_width, source_height = self.source_image.size
            crop_left, crop_top = max(0, int(left * source_width)), max(0, int(top * source_height))
            crop_right = min(source_width, max(crop_left + 1, round((left + view_w) * source_width)))
            crop_bottom = min(source_height, max(crop_top + 1, round((top + view_h) * source_height)))
            crop_box = (crop_left, crop_top, crop_right, crop_bottom)
            
            view_pixel_w = crop_right - crop_left
            view_pixel_h = crop_bottom - crop_top
            scale = min(c_w / view_pixel_w, c_h / view_pixel_h)
            draw_w = max(1, int(view_pixel_w * scale))
            draw_h = max(1, int(view_pixel_h * scale))
            
            x_offset = (c_w - draw_w) / 2.0
            y_offset = (c_h - draw_h) / 2.0
            
            if is_ingame:
                self.ig_canvas_w, self.ig_canvas_h = draw_w, draw_h
                self.ig_x_offset, self.ig_y_offset = x_offset, y_offset
                self.ig_placeholder_rect = None
            else:
                self.m_canvas_w, self.m_canvas_h = draw_w, draw_h
                self.m_x_offset, self.m_y_offset = x_offset, y_offset
                self.m_placeholder_rect = None

            resample_filter = resample if resample is not None else Image.Resampling.LANCZOS
            active_zone_keys = tuple(key for key, _l, _f, _c in ZONE_LAYERS if self._zone_visible.get(key) and key in self._zone_images)
            cache_key = (crop_box, (draw_w, draw_h), resample_filter, active_zone_keys)
            
            if rendered_size != cache_key:
                cropped = self.source_image.crop(crop_box).convert("RGBA")
                for key in active_zone_keys: cropped.alpha_composite(self._zone_images[key].crop(crop_box))
                resized = cropped.resize((draw_w, draw_h), resample_filter)
                photo = ImageTk.PhotoImage(resized)
                if is_ingame:
                    self.ig_map_image = photo
                    self.ig_rendered_size = cache_key
                else:
                    self.m_map_image = photo
                    self.m_rendered_size = cache_key
                
            image_to_draw = self.ig_map_image if is_ingame else self.m_map_image
            canvas.create_image(x_offset + draw_w / 2, y_offset + draw_h / 2, image=image_to_draw)
        else:
            if is_ingame:
                self.ig_view = None
                self.ig_x_offset = self.ig_y_offset = 0
                self.ig_canvas_w, self.ig_canvas_h = c_w, c_h
            else:
                self.m_view = None
                self.m_x_offset = self.m_y_offset = 0
                self.m_canvas_w, self.m_canvas_h = c_w, c_h
            
            margin = 24
            r_left, r_top = margin, margin
            map_width, map_height = c_w - margin * 2, c_h - margin * 2
            rect = (r_left, r_top, map_width, map_height)
            if is_ingame: self.ig_placeholder_rect = rect
            else: self.m_placeholder_rect = rect
            
            canvas.create_rectangle(r_left, r_top, r_left + map_width, r_top + map_height, fill="#121820", outline="#212e3d", width=1.5)
            canvas.create_text(c_w / 2, c_h / 2, text=f"{self.profile.name}\nChưa có ảnh map", fill="#8395a7", font=("Segoe UI", 14, "bold"), justify="center")

        self._draw_zone_toggles_on(canvas, is_ingame)

        # Exact map-image viewport for all world-space overlays.
        if getattr(self, 'source_image', None):
            overlay_clip_rect = (
                float(x_offset),
                float(y_offset),
                float(x_offset + draw_w),
                float(y_offset + draw_h),
            )
        else:
            _rect = self.ig_placeholder_rect if is_ingame else self.m_placeholder_rect
            if _rect is not None:
                _l, _t, _w, _h = _rect
                overlay_clip_rect = (
                    float(_l), float(_t),
                    float(_l + _w), float(_t + _h),
                )
            else:
                overlay_clip_rect = (0.0, 0.0, float(c_w), float(c_h))
        
        # VẼ ANIMALS & HERBS TRÊN MAP LỚN (Áp dụng Position chuẩn)
        if getattr(self, 'local_markers', None):
            for item in self.local_markers:
                key = item.get("key", "").lower()
                if self.overlay_vars.get(key) and self.overlay_vars[key].get():
                    color = self.overlay_colors.get(key, "#ffffff")
                    pos = Position(item.get("x", 0.0), item.get("y", 0.0), 0.0)
                    px, py = self._pixel(pos, is_ingame)
                    if _point_in_rect(px, py, overlay_clip_rect, 4.5):
                        canvas.create_oval(px-3.5, py-3.5, px+3.5, py+3.5, fill=color, outline="#000000", width=0.8)

        # ADD-ONLY: draw extra Gateway POIs on the large menu/in-game map.
        if getattr(self, "gateway_pois", None):
            _draw_gateway_pois(
                canvas, self.profile, self.gateway_pois,
                lambda pos: self._pixel(pos, is_ingame),
                hud=False,
                visible=self._zone_visible,
                clip_rect=overlay_clip_rect,
            )

        if self.show_regions_var.get() and MAP_LABELS:
            # Labels must stay inside the ACTUAL rendered map image, not merely
            # inside the Tk canvas (the canvas can contain letterbox margins).
            label_left, label_top, label_right, label_bottom = overlay_clip_rect

            for name, pos, color, size in MAP_LABELS:
                x, y = self._pixel(pos, is_ingame)
                raw_x = x + TEXT_OFFSET_X
                raw_y = y + TEXT_OFFSET_Y

                # Do not move labels from outside the current zoomed viewport
                # onto the edge. Only labels whose anchor is truly visible draw.
                if not (
                    label_left <= raw_x <= label_right
                    and label_top <= raw_y <= label_bottom
                ):
                    continue

                draw_x, draw_y = _clamp_text_to_rect(
                    raw_x, raw_y, name, size,
                    label_left, label_top,
                    label_right, label_bottom,
                    padding=5.0
                )
                _draw_text_with_outline(
                    canvas, draw_x, draw_y,
                    name, size, color
                )

        positions = getattr(self, 'path_history', []) + ([self.current] if self.current else [])
        if len(positions) >= 2:
            trail_points = [self._pixel(position, is_ingame) for position in positions]
            _draw_clipped_polyline(
                canvas, trail_points,
                fill=ACCENT_CYAN,
                width=2.5,
                clip_rect=overlay_clip_rect,
            )

        # VẼ PING
        if getattr(self, 'is_party_active', False) and getattr(self, 'teammates', None):
            for tid, tdata in self.teammates.items():
                ping = tdata.get("ping")
                if ping and not self._ping_is_expired(ping):
                    px, py = self._pixel(Position(ping["x"], ping["y"], 0.0), is_ingame)
                    if _point_in_rect(px, py, overlay_clip_rect, 16.0):
                        canvas.create_oval(px-8, py-8, px+8, py+8, fill=ACCENT_YELLOW, outline="white", width=1.5)
                        canvas.create_oval(px-15, py-15, px+15, py+15, outline=ACCENT_YELLOW, width=1.5, dash=(3, 3))
                        label_x, label_y = _clamp_text_to_rect(
                            px, py - 22, str(tdata["name"]), 9,
                            *overlay_clip_rect, padding=4.0
                        )
                        _draw_text_with_outline(canvas, label_x, label_y, f"{tdata['name']}", 9, ACCENT_YELLOW)

        if getattr(self, 'my_active_ping', None) and not self._ping_is_expired(self.my_active_ping):
            px, py = self._pixel(self.my_active_ping["pos"], is_ingame)
            if _point_in_rect(px, py, overlay_clip_rect, 16.0):
                canvas.create_oval(px-8, py-8, px+8, py+8, fill=ACCENT_CYAN, outline="white", width=1.5)
                canvas.create_oval(px-15, py-15, px+15, py+15, outline=ACCENT_CYAN, width=1.5, dash=(3, 3))
                label_x, label_y = _clamp_text_to_rect(
                    px, py - 22, "Ping bạn", 9,
                    *overlay_clip_rect, padding=4.0
                )
                _draw_text_with_outline(canvas, label_x, label_y, "Ping bạn", 9, ACCENT_CYAN)

        # Local-only coordinate ping.
        if self._manual_ping_is_active():
            manual_ping = self.manual_active_ping
            mx, my = self._pixel(manual_ping["pos"], is_ingame)

            if _point_in_rect(mx, my, overlay_clip_rect, 16.0):
                canvas.create_rectangle(
                    mx - 7, my - 7, mx + 7, my + 7,
                    fill=ACCENT_RED,
                    outline="#ffffff",
                    width=1.5
                )
                canvas.create_oval(
                    mx - 15, my - 15, mx + 15, my + 15,
                    outline=ACCENT_RED,
                    width=1.5,
                    dash=(3, 3)
                )

                remain_seconds = max(
                    0.0,
                    float(manual_ping["expires_at"]) - time.time()
                )
                remain_minutes = remain_seconds / 60.0
                manual_label = f"Manual Ping • {remain_minutes:.1f}m"

                label_x, label_y = _clamp_text_to_rect(
                    mx, my - 22, manual_label, 9,
                    *overlay_clip_rect, padding=4.0
                )
                _draw_text_with_outline(
                    canvas,
                    label_x,
                    label_y,
                    manual_label,
                    9,
                    ACCENT_RED
                )

        if self._asset_location_ping_is_active():
            asset_ping = self.asset_location_active_ping
            ax, ay = self._pixel(asset_ping["pos"], is_ingame)

            if _point_in_rect(ax, ay, overlay_clip_rect, 16.0):
                canvas.create_polygon(
                    ax, ay - 9,
                    ax + 9, ay,
                    ax, ay + 9,
                    ax - 9, ay,
                    fill="#000000",
                    outline="#ffffff",
                    width=1.5
                )
                canvas.create_oval(
                    ax - 16, ay - 16, ax + 16, ay + 16,
                    outline="#ffffff",
                    width=1.5,
                    dash=(3, 3)
                )

                remaining = max(
                    0,
                    int(float(asset_ping["expires_at"]) - time.time())
                )
                hh, rem = divmod(remaining, 3600)
                mm, ss = divmod(rem, 60)
                asset_label = f"Asset Ping • {hh:02d}:{mm:02d}:{ss:02d}"

                label_x, label_y = _clamp_text_to_rect(
                    ax, ay - 24, asset_label, 9,
                    *overlay_clip_rect, padding=4.0
                )
                _draw_text_with_outline(
                    canvas, label_x, label_y,
                    asset_label, 9, "#000000", outline_color="#ffffff"
                )

        # VẼ ĐỒNG ĐỘI
        if getattr(self, 'is_party_active', False) and getattr(self, 'teammates', None):
            try:
                for tid, tdata in self.teammates.items():
                    if not tdata.get("has_pos"): continue
                    tx, ty = self._pixel(tdata["pos"], is_ingame)
                    tvitals = tdata.get("vitals")
                    needs_vitals = bool(
                        tvitals
                        and getattr(self, 'show_teammate_vitals_map_var', None)
                        and self.show_teammate_vitals_map_var.get()
                    )

                    if not _point_in_rect(
                        tx, ty, overlay_clip_rect,
                        42.0 if needs_vitals else 22.0
                    ):
                        continue

                    _draw_heading_polygon(canvas, tx, ty, tdata["yaw"], 13, ACCENT_GREEN)
                    canvas.create_oval(tx - 5, ty - 5, tx + 5, ty + 5, fill="#10ac84", outline="white", width=1)
                    name_x, name_y = _clamp_text_to_rect(
                        tx, ty + 16, str(tdata["name"]), 8,
                        *overlay_clip_rect, padding=4.0
                    )
                    _draw_text_with_outline(canvas, name_x, name_y, tdata["name"], 8, ACCENT_GREEN)

                    if needs_vitals:
                        bar_w, bar_h, start_y = 28, 3, ty + 24
                        def draw_mini_bar(val, max_val, color, offset_y):
                            if not max_val: max_val = 1
                            fraction = max(0.0, min(1.0, val / max_val))
                            canvas.create_rectangle(tx - bar_w/2, start_y + offset_y, tx + bar_w/2, start_y + offset_y + bar_h, fill="#0c1015", outline="")
                            if fraction > 0:
                                canvas.create_rectangle(tx - bar_w/2, start_y + offset_y, tx - bar_w/2 + (bar_w * fraction), start_y + offset_y + bar_h, fill=color, outline="")

                        draw_mini_bar(tvitals.get('h', 0), tvitals.get('mh', 1), ACCENT_RED, 0)
                        draw_mini_bar(tvitals.get('s', 0), tvitals.get('ms', 1), ACCENT_YELLOW, 4)
                        draw_mini_bar(tvitals.get('f', 0), tvitals.get('mf', 1), ACCENT_ORANGE, 8)
                        draw_mini_bar(tvitals.get('w', 0), tvitals.get('mw', 1), "#0984e3", 12)
            except Exception: pass

        if self.current:
            heading = self._current_heading_degrees()
            x, y = self._pixel(self.current, is_ingame)
            if _point_in_rect(x, y, overlay_clip_rect, 15.0):
                if heading is None:
                    canvas.create_oval(x - 10, y - 10, x + 10, y + 10, fill=ACCENT_RED, outline="white", width=2)
                else:
                    _draw_heading_polygon(canvas, x, y, heading, 13, ACCENT_RED)

    def _pixel(self, position: Position, is_ingame: bool) -> tuple[float, float]:
        nx, ny = self.profile.to_normalized(position)
        view = self.ig_view if is_ingame else self.m_view
        c_w = self.ig_canvas_w if is_ingame else self.m_canvas_w
        c_h = self.ig_canvas_h if is_ingame else self.m_canvas_h
        x_off = self.ig_x_offset if is_ingame else self.m_x_offset
        y_off = self.ig_y_offset if is_ingame else self.m_y_offset
        rect = self.ig_placeholder_rect if is_ingame else self.m_placeholder_rect
        
        if view is None and rect is not None:
            left, top, width, height = rect
            return left + nx * width, top + ny * height
            
        if view is not None:
            view_left, view_top, view_w, view_h = view
            x = (nx - view_left) / view_w * c_w
            y = (ny - view_top) / view_h * c_h
            return x + x_off, y + y_off
        return 0, 0

    def _active_zone_images(self) -> tuple["Image.Image", ...]:
        return tuple(self._zone_images[key] for key, _l, _f, _c in ZONE_LAYERS if self._zone_visible.get(key) and key in self._zone_images)

    def _draw_zone_toggles_on(self, canvas: tk.Canvas, is_ingame: bool) -> None:
        hitboxes = {}
        margin, chip_h, gap = 14, 26, 6
        canvas_w = max(canvas.winfo_width(), 1)
        x, y = margin, canvas.winfo_height() - margin - chip_h

        for key, label, _filename, color in MAP_TOGGLE_LAYERS:
            # Layer ảnh cũ chỉ hiện khi file ảnh tồn tại.
            if key in {item[0] for item in ZONE_LAYERS} and key not in self._zone_images:
                continue

            # Ba layer JSON chỉ hiện nút khi JSON thực sự có dữ liệu tương ứng.
            if key == "poi_sanctuaries" and not self.gateway_pois.get("sanctuaries"):
                continue
            if key == "poi_migrations" and not self.gateway_pois.get("migrations"):
                continue
            if key == "poi_patrol_zones" and not self.gateway_pois.get("patrol_zones"):
                continue
            if key == "poi_salt" and not self.gateway_pois.get("salt_licks"):
                continue

            active = self._zone_visible.get(key, False)
            text = f"{'■' if active else '□'} {label.upper()}"

            # Đo trước chiều rộng để tự xuống dòng khi quá mép map.
            probe = canvas.create_text(-10000, -10000, text=text, font=("Segoe UI", 8, "bold"), anchor="w")
            bbox = canvas.bbox(probe)
            canvas.delete(probe)
            chip_w = (bbox[2] - bbox[0]) + 20 if bbox else 90
            if x + chip_w > canvas_w - margin and x > margin:
                x = margin
                y -= chip_h + gap

            text_id = canvas.create_text(
                x + 10, y + chip_h / 2, text=text,
                fill="#ffffff" if active else "#8395a7",
                font=("Segoe UI", 8, "bold"), anchor="w"
            )
            rect_id = canvas.create_rectangle(
                x, y, x + chip_w, y + chip_h,
                fill=color if active else "#141b24",
                outline=color if active else "#212e3d", width=1.2
            )
            canvas.tag_lower(rect_id, text_id)
            hitboxes[key] = (x, y, x + chip_w, y + chip_h)
            x += chip_w + gap

        # Action chip: permanently remove your own active ping.
        if self.my_active_ping and not self._ping_is_expired(self.my_active_ping):
            clear_key = "__clear_my_ping__"
            clear_text = "✕ PING"
            clear_color = ACCENT_RED

            probe = canvas.create_text(
                -10000, -10000, text=clear_text,
                font=("Segoe UI", 8, "bold"), anchor="w"
            )
            bbox = canvas.bbox(probe)
            canvas.delete(probe)
            chip_w = (bbox[2] - bbox[0]) + 20 if bbox else 72

            if x + chip_w > canvas_w - margin and x > margin:
                x = margin
                y -= chip_h + gap

            text_id = canvas.create_text(
                x + 10, y + chip_h / 2, text=clear_text,
                fill="#ffffff", font=("Segoe UI", 8, "bold"), anchor="w"
            )
            rect_id = canvas.create_rectangle(
                x, y, x + chip_w, y + chip_h,
                fill=clear_color, outline="#ff7675", width=1.2
            )
            canvas.tag_lower(rect_id, text_id)
            hitboxes[clear_key] = (x, y, x + chip_w, y + chip_h)


        if self._manual_ping_is_active():
            manual_key = "__clear_manual_ping__"
            manual_text = "✕ MANUAL"
            manual_color = "#8e44ad"

            probe = canvas.create_text(
                -10000, -10000,
                text=manual_text,
                font=("Segoe UI", 8, "bold"),
                anchor="w"
            )
            bbox = canvas.bbox(probe)
            canvas.delete(probe)

            manual_chip_w = (
                (bbox[2] - bbox[0]) + 20
                if bbox else 85
            )

            if (
                x + manual_chip_w > canvas_w - margin
                and x > margin
            ):
                x = margin
                y -= chip_h + gap

            text_id = canvas.create_text(
                x + 10,
                y + chip_h / 2,
                text=manual_text,
                fill="#ffffff",
                font=("Segoe UI", 8, "bold"),
                anchor="w"
            )

            rect_id = canvas.create_rectangle(
                x, y,
                x + manual_chip_w, y + chip_h,
                fill=manual_color,
                outline="#c56cf0",
                width=1.2
            )
            canvas.tag_lower(rect_id, text_id)

            hitboxes[manual_key] = (
                x, y,
                x + manual_chip_w, y + chip_h
            )
            x += manual_chip_w + gap

        if self._asset_location_ping_is_active():
            asset_key = "__clear_asset_ping__"
            asset_text = "✕ ASSET"
            probe = canvas.create_text(
                -10000, -10000,
                text=asset_text,
                font=("Segoe UI", 8, "bold"),
                anchor="w"
            )
            bbox = canvas.bbox(probe)
            canvas.delete(probe)
            asset_chip_w = (bbox[2] - bbox[0]) + 20 if bbox else 82

            if x + asset_chip_w > canvas_w - margin and x > margin:
                x = margin
                y -= chip_h + gap

            text_id = canvas.create_text(
                x + 10, y + chip_h / 2,
                text=asset_text,
                fill="#ffffff",
                font=("Segoe UI", 8, "bold"),
                anchor="w"
            )
            rect_id = canvas.create_rectangle(
                x, y, x + asset_chip_w, y + chip_h,
                fill=ACCENT_ORANGE,
                outline="#ffffff",
                width=1.2
            )
            canvas.tag_lower(rect_id, text_id)
            hitboxes[asset_key] = (x, y, x + asset_chip_w, y + chip_h)
            x += asset_chip_w + gap

        if is_ingame:
            self._ig_zone_toggle_hitboxes = hitboxes
        else:
            self._m_zone_toggle_hitboxes = hitboxes

    def _current_heading_degrees(self) -> float | None:
        if self._local_position_fresh() and getattr(self, '_local_heading_deg', None) is not None: return self._local_heading_deg
        if getattr(self, '_islepilot_heading_deg', None) is not None: return self._islepilot_heading_deg
        if self.current and getattr(self, 'path_history', []):
            prev = self.path_history[-1]
            nx1, ny1 = self.profile.to_normalized(prev)
            nx2, ny2 = self.profile.to_normalized(self.current)
            dx, dy = nx2 - nx1, ny2 - ny1
            if math.hypot(dx, dy) > 0.0001:
                return math.degrees(math.atan2(dx, -dy)) % 360.0
        return None

    def _schedule_hq_redraw_menu(self):
        if getattr(self, '_m_pending_hq_job', None): self.root.after_cancel(self._m_pending_hq_job)
        self._m_pending_hq_job = self.root.after(HQ_REDRAW_DELAY_MS, self._hq_redraw_menu)
        
    def _hq_redraw_menu(self):
        self._m_pending_hq_job = None
        self._redraw_menu()

    def _schedule_hq_redraw_ingame(self):
        if getattr(self, '_ig_pending_hq_job', None): self.root.after_cancel(self._ig_pending_hq_job)
        self._ig_pending_hq_job = self.root.after(HQ_REDRAW_DELAY_MS, self._hq_redraw_ingame)
        
    def _hq_redraw_ingame(self):
        self._ig_pending_hq_job = None
        self._redraw_ingame()

    def _on_mouse_wheel(self, event, is_ingame=False) -> None:
        if not getattr(self, 'source_image', None): return
        x_off = self.ig_x_offset if is_ingame else self.m_x_offset
        y_off = self.ig_y_offset if is_ingame else self.m_y_offset
        c_w = self.ig_canvas_w if is_ingame else self.m_canvas_w
        c_h = self.ig_canvas_h if is_ingame else self.m_canvas_h
        view = self.ig_view if is_ingame else self.m_view
        zoom = self.ig_zoom if is_ingame else self.m_zoom
        
        if view is None: return
        real_x = event.x - x_off
        real_y = event.y - y_off
        if not (0 <= real_x <= c_w and 0 <= real_y <= c_h): return
        
        view_left, view_top, view_w, view_h = view
        cursor_nx = view_left + (real_x / c_w) * view_w
        cursor_ny = view_top + (real_y / c_h) * view_h
        
        factor = ZOOM_STEP if event.delta > 0 else (1.0 / ZOOM_STEP)
        new_zoom = min(MAX_ZOOM, max(MIN_ZOOM, zoom * factor))
        if new_zoom == zoom: return
        
        new_view_w = new_view_h = 1.0 / new_zoom
        new_center_nx = cursor_nx - (real_x / c_w - 0.5) * new_view_w
        new_center_ny = cursor_ny - (real_y / c_h - 0.5) * new_view_h
        
        if is_ingame:
            self.ig_zoom = new_zoom
            self.ig_center_nx = new_center_nx
            self.ig_center_ny = new_center_ny
            self._redraw_ingame(resample=Image.Resampling.BILINEAR)
            self._schedule_hq_redraw_ingame()
        else:
            self.m_zoom = new_zoom
            self.m_center_nx = new_center_nx
            self.m_center_ny = new_center_ny
            self._redraw_menu(resample=Image.Resampling.BILINEAR)
            self._schedule_hq_redraw_menu()

    def _on_pan_start(self, event, is_ingame=False) -> None:
        hitboxes = self._ig_zone_toggle_hitboxes if is_ingame else self._m_zone_toggle_hitboxes
        for key, (x1, y1, x2, y2) in hitboxes.items():
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                if key == "__clear_my_ping__":
                    self._clear_my_ping()
                    return
                if key == "__clear_manual_ping__":
                    self._clear_manual_ping()
                    return
                if key == "__clear_asset_ping__":
                    self._clear_asset_location_ping()
                    return
                self._zone_visible[key] = not self._zone_visible[key]
                self._redraw()
                return
        if not getattr(self, 'source_image', None): return
        if is_ingame: self._ig_pan_last = (event.x, event.y)
        else: self._m_pan_last = (event.x, event.y)

    def _on_pan_move(self, event, is_ingame=False) -> None:
        if not getattr(self, 'source_image', None): return
        pan_last = self._ig_pan_last if is_ingame else self._m_pan_last
        view = self.ig_view if is_ingame else self.m_view
        
        if pan_last is None or view is None: return
        last_x, last_y = pan_last
        dx, dy = event.x - last_x, event.y - last_y
        
        if is_ingame:
            self._ig_pan_last = (event.x, event.y)
            _vl, _vt, vw, vh = self.ig_view
            self.ig_center_nx -= (dx / self.ig_canvas_w) * vw
            self.ig_center_ny -= (dy / self.ig_canvas_h) * vh
            self._redraw_ingame(resample=Image.Resampling.BILINEAR)
            self._schedule_hq_redraw_ingame()
        else:
            self._m_pan_last = (event.x, event.y)
            _vl, _vt, vw, vh = self.m_view
            self.m_center_nx -= (dx / self.m_canvas_w) * vw
            self.m_center_ny -= (dy / self.m_canvas_h) * vh
            self._redraw_menu(resample=Image.Resampling.BILINEAR)
            self._schedule_hq_redraw_menu()

    def _on_pan_end(self, event, is_ingame=False) -> None:
        if is_ingame: self._ig_pan_last = None
        else: self._m_pan_last = None

    def _on_reset_view(self, event, is_ingame=False) -> None:
        if is_ingame:
            if getattr(self, '_ig_pending_hq_job', None):
                self.root.after_cancel(self._ig_pending_hq_job)
                self._ig_pending_hq_job = None
            self.ig_zoom = MIN_ZOOM
            self.ig_center_nx = 0.5
            self.ig_center_ny = 0.5
            self._redraw_ingame()
        else:
            if getattr(self, '_m_pending_hq_job', None):
                self.root.after_cancel(self._m_pending_hq_job)
                self._m_pending_hq_job = None
            self.m_zoom = MIN_ZOOM
            self.m_center_nx = 0.5
            self.m_center_ny = 0.5
            self._redraw_menu()

def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == islepilot.LOGIN_SUBPROCESS_FLAG:
        result = islepilot.login_via_steam()
        payload = {"steam_id": result[0], "token": result[1]} if result else None
        print(json.dumps(payload))
        return

    root = ctk.CTk()
    try:
        MapApp(root)
    except RuntimeError as exc:
        messagebox.showerror("The-Maps", str(exc))
        root.destroy()
        return
    except Exception:
        crash_log = DATA_ROOT / "crash.log"
        try:
            DATA_ROOT.mkdir(parents=True, exist_ok=True)
            crash_log.write_text(traceback.format_exc(), encoding="utf-8")
        except OSError: pass
        messagebox.showerror(
            "The-Maps",
            f"The-Maps gặp lỗi khi khởi động.\nChi tiết lỗi được ghi vào:\n{crash_log}",
        )
        root.destroy()
        return
    root.mainloop()

if __name__ == "__main__":
    main()