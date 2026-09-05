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
    ("migrations", "Migration", "zone_migration.png", "#ff9800"),
    ("patrol_zones", "Patrol", "zone_patrol.png", "#ab47bc"),
    ("400OV", "400 Ô", "number.png", "#1674f0"),
    ("600OV", "600 Ô", "number2.png", "#eef106"),
)

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
        for zone_image in zone_images: cropped.alpha_composite(zone_image.crop(crop_box))
        resized = cropped.resize((MINI_MAP_SIZE, MINI_MAP_SIZE), Image.Resampling.LANCZOS)
        
        if shape == "Tròn":
            mask = Image.new("L", (MINI_MAP_SIZE, MINI_MAP_SIZE), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, MINI_MAP_SIZE, MINI_MAP_SIZE), fill=255)
            bg_img = Image.new("RGBA", (MINI_MAP_SIZE, MINI_MAP_SIZE), "#000001")
            resized = Image.composite(resized, bg_img, mask)

        self._photo = ImageTk.PhotoImage(resized)
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)

        center = MINI_MAP_SIZE / 2
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
                    if 0 <= mx <= MINI_MAP_SIZE and 0 <= my <= MINI_MAP_SIZE:
                        self.canvas.create_oval(mx-2.5, my-2.5, mx+2.5, my+2.5, fill=color, outline="#000000", width=0.5)
        
        if path_history and len(path_history) > 0:
            points = []
            for pos in path_history + [Position(x, y, 0.0)]:
                hnx, hny = profile.to_normalized(pos)
                hx = (hnx - left) / frac * MINI_MAP_SIZE
                hy = (hny - top) / frac * MINI_MAP_SIZE
                points.extend((hx, hy))
            if len(points) >= 4:
                self.canvas.create_line(*points, fill=ACCENT_CYAN, width=2, joinstyle="round", capstyle="round")

        if show_regions and MAP_LABELS:
            for name, pos, color, size in MAP_LABELS:
                r_nx, r_ny = profile.to_normalized(pos)
                rx = (r_nx - left) / frac * MINI_MAP_SIZE
                ry = (r_ny - top) / frac * MINI_MAP_SIZE
                if -20 <= rx <= MINI_MAP_SIZE + 20 and -20 <= ry <= MINI_MAP_SIZE + 20:
                    _draw_text_with_outline(self.canvas, rx, ry, name, 8, color)

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
                    _draw_heading_polygon(self.canvas, hx, hy, tdata["yaw"], 10, ACCENT_GREEN)
            except Exception: pass

        marker_x = max(0.0, min(float(MINI_MAP_SIZE), (nx - left) / frac * MINI_MAP_SIZE))
        marker_y = max(0.0, min(float(MINI_MAP_SIZE), (ny - top) / frac * MINI_MAP_SIZE))
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
        for _ in range(8):
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
        
        self.show_teammate_vitals_map_var = ctk.BooleanVar(value=True)
        self.show_teammate_vitals_menu_var = ctk.BooleanVar(value=True)
        
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
        self._zone_visible: dict[str, bool] = {key: (False if key == "400OV" or key == "600OV" else True) for key, _label, _filename, _color in ZONE_LAYERS}
        self._m_zone_toggle_hitboxes: dict[str, tuple[float, float, float, float]] = {}
        self._ig_zone_toggle_hitboxes: dict[str, tuple[float, float, float, float]] = {}

        self._islepilot_cred_path = DATA_ROOT / "islepilot.cred"
        self._islepilot_session: islepilot.IslePilotSession | None = None
        self._islepilot_steam_id: str | None = None
        self._islepilot_heading_deg: float | None = None
        self._islepilot_online = False
        self._islepilot_logging_in = False
        self._hud: IslePilotHud | None = None

        self._local_session: localtelemetry.LocalMovementSession | None = None
        self._local_state = "starting"
        self._local_last_update = 0.0
        self._local_heading_deg: float | None = None
        self._local_trail_last_update = 0.0
        self._npcap_prompted = False

        self.map_visible = False
        self.ingame_map_visible = False

        self.local_markers: list[dict] = []
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
        self._load_map_image()
        self._load_local_animal_herbs()
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
                self.show_teammate_vitals_map_var.set(data.get("show_teammate_vitals_map", True))
                self.show_teammate_vitals_menu_var.set(data.get("show_teammate_vitals_menu", True))
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
            "show_teammate_vitals_map": self.show_teammate_vitals_map_var.get(),
            "show_teammate_vitals_menu": self.show_teammate_vitals_menu_var.get()
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

        self.teammates_panel = ctk.CTkFrame(card_party, fg_color="#0c1015", corner_radius=6)
        self.teammates_panel.pack(fill="x", padx=10, pady=(2, 8))
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

    def _party_sync_loop(self):
        empty_room_counter = 0
        while self.is_party_active:
            game_x = self.current.y if self.current else 999999.0
            game_y = self.current.x if self.current else 999999.0
            yaw = self._current_heading_degrees() or 0.0 if self.current else 0.0

            current_time = time.time()
            if self.my_active_ping and current_time - self.my_active_ping["time"] > 7.0:
                self.my_active_ping = None
                self.root.after(0, self._redraw)

            ping_payload = None
            if self.my_active_ping:
                ping_payload = {
                    "x": self.my_active_ping["pos"].x, 
                    "y": self.my_active_ping["pos"].y
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
                        valid_teammates[t["id"]] = {
                            "name": t.get("name", t["id"]),
                            "pos": Position(t["y"], t["x"], 0.0) if has_pos else None, 
                            "yaw": t["yaw"],
                            "ping": t.get("ping"),
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
        self.my_active_ping = {"pos": Position(wx, wy, 0.0), "time": time.time()}
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

    def _on_hud_toggle(self) -> None:
        self._save_app_config()
        if getattr(self, '_hud', None) is not None:
            self._poll_hud_visibility()

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
            self.ingame_map_window.withdraw()
            self.ingame_map_visible = False
        else:
            if self.map_visible:
                self._toggle_map_view()
            self.ingame_map_window.deiconify()
            self.ingame_map_window.lift()
            self.ingame_map_visible = True
            self._redraw_ingame()

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

    def _poll_hud_visibility(self) -> None:
        if getattr(self, '_hud', None) is not None:
            local_live = self._local_position_fresh()
            has_live_source = local_live or getattr(self, '_islepilot_online', False)
            if has_live_source and self._is_game_foreground():
                self._hud.show(show_minimap=self.show_minimap_var.get(), show_vitals=self.show_vitals_var.get(), show_quests=self.show_quests_var.get() and getattr(self, '_islepilot_online', False))
            else: 
                self._hud.hide()
        self.root.after(FOREGROUND_POLL_MS, self._poll_hud_visibility)

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
            try: self.source_image = Image.open(self.profile.image_path).convert("RGB")
            except (OSError, ValueError): self.source_image = None
            
        self._zone_images = {}
        for key, path in self.profile.zone_image_paths.items():
            try: self._zone_images[key] = Image.open(path).convert("RGBA")
            except (OSError, ValueError): pass

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
        if position is None: return
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
        
        # VẼ ANIMALS & HERBS TRÊN MAP LỚN (Áp dụng Position chuẩn)
        if getattr(self, 'local_markers', None):
            for item in self.local_markers:
                key = item.get("key", "").lower()
                if self.overlay_vars.get(key) and self.overlay_vars[key].get():
                    color = self.overlay_colors.get(key, "#ffffff")
                    pos = Position(item.get("x", 0.0), item.get("y", 0.0), 0.0)
                    px, py = self._pixel(pos, is_ingame)
                    if -10 <= px <= c_w + 10 and -10 <= py <= c_h + 10:
                        canvas.create_oval(px-3.5, py-3.5, px+3.5, py+3.5, fill=color, outline="#000000", width=0.8)

        if self.show_regions_var.get() and MAP_LABELS:
            for name, pos, color, size in MAP_LABELS:
                x, y = self._pixel(pos, is_ingame)
                _draw_text_with_outline(canvas, x + TEXT_OFFSET_X, y + TEXT_OFFSET_Y, name, size, color)

        positions = getattr(self, 'path_history', []) + ([self.current] if self.current else [])
        if len(positions) >= 2:
            points = []
            for position in positions:
                x, y = self._pixel(position, is_ingame)
                points.extend((x, y))
            canvas.create_line(*points, fill=ACCENT_CYAN, width=2.5, joinstyle="round", capstyle="round")

        # VẼ PING
        if getattr(self, 'is_party_active', False) and getattr(self, 'teammates', None):
            for tid, tdata in self.teammates.items():
                if tdata.get("ping"):
                    px, py = self._pixel(Position(tdata["ping"]["x"], tdata["ping"]["y"], 0.0), is_ingame)
                    canvas.create_oval(px-8, py-8, px+8, py+8, fill=ACCENT_YELLOW, outline="white", width=1.5)
                    canvas.create_oval(px-15, py-15, px+15, py+15, outline=ACCENT_YELLOW, width=1.5, dash=(3, 3))
                    _draw_text_with_outline(canvas, px, py - 22, f"{tdata['name']}", 9, ACCENT_YELLOW)

        if getattr(self, 'my_active_ping', None):
            px, py = self._pixel(self.my_active_ping["pos"], is_ingame)
            canvas.create_oval(px-8, py-8, px+8, py+8, fill=ACCENT_CYAN, outline="white", width=1.5)
            canvas.create_oval(px-15, py-15, px+15, py+15, outline=ACCENT_CYAN, width=1.5, dash=(3, 3))
            _draw_text_with_outline(canvas, px, py - 22, "Ping bạn", 9, ACCENT_CYAN)

        # VẼ ĐỒNG ĐỘI
        if getattr(self, 'is_party_active', False) and getattr(self, 'teammates', None):
            try:
                for tid, tdata in self.teammates.items():
                    if not tdata.get("has_pos"): continue
                    tx, ty = self._pixel(tdata["pos"], is_ingame)
                    _draw_heading_polygon(canvas, tx, ty, tdata["yaw"], 13, ACCENT_GREEN)
                    canvas.create_oval(tx - 5, ty - 5, tx + 5, ty + 5, fill="#10ac84", outline="white", width=1)
                    _draw_text_with_outline(canvas, tx, ty + 16, tdata["name"], 8, ACCENT_GREEN)

                    tvitals = tdata.get("vitals")
                    if tvitals and getattr(self, 'show_teammate_vitals_map_var', None) and self.show_teammate_vitals_map_var.get():
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
        if not getattr(self, '_zone_images', None): return
        margin, chip_h = 14, 26
        x, y = margin, canvas.winfo_height() - margin - chip_h
        for key, label, _filename, color in ZONE_LAYERS:
            if key not in self._zone_images: continue
            active = self._zone_visible.get(key, False)
            text = f"{'■' if active else '□'} {label.upper()}"
            text_id = canvas.create_text(x + 10, y + chip_h / 2, text=text, fill="#ffffff" if active else "#8395a7", font=("Segoe UI", 8, "bold"), anchor="w")
            bbox = canvas.bbox(text_id)
            chip_w = (bbox[2] - bbox[0]) + 20 if bbox else 90
            rect_id = canvas.create_rectangle(x, y, x + chip_w, y + chip_h, fill=color if active else "#141b24", outline=color if active else "#212e3d", width=1.2)
            canvas.tag_lower(rect_id, text_id)
            hitboxes[key] = (x, y, x + chip_w, y + chip_h)
            x += chip_w + 6
        if is_ingame: self._ig_zone_toggle_hitboxes = hitboxes
        else: self._m_zone_toggle_hitboxes = hitboxes

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