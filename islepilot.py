from __future__ import annotations

import ctypes
import json
import re
import subprocess
import sys
import threading
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests
import webview

SERVICE_BASE_URL = "https://islepilot.eu"
LOGIN_URL = f"{SERVICE_BASE_URL}/api/overlay/auth/steam"
ME_URL = f"{SERVICE_BASE_URL}/api/overlay/me"
OVERLAY_VERSION = "2"

CALLBACK_PATTERN = re.compile(
    r"isle-overlay://[^\"'<>\s]*?sid=(?P<sid>\d{5,})[^\"'<>\s]*?token=(?P<token>[A-Za-z0-9_.\-]+)"
)

# IslePilot REST supplies vitals / quests / metadata and a slow
# position/yaw fallback. Live testing showed its position snapshot changes
# only about every ~5 seconds, so smooth minimap motion comes from the local
# Npcap movement stream in app.py instead.
POLL_INTERVAL_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 8.0
LOGIN_WINDOW_TITLE = "Đăng nhập Steam qua IslePilot"
LOGIN_SUBPROCESS_FLAG = "--islepilot-login"
LOGIN_TIMEOUT_SECONDS = 300.0

_LOADING_HTML = """
<html><body style="margin:0;height:100vh;display:flex;align-items:center;
justify-content:center;background:#10191d;color:#cfd8dc;
font-family:'Segoe UI',sans-serif;font-size:14px;">
Đang mở trang đăng nhập Steam…
</body></html>
"""

# The 10 Prime Elder quest names IslePilot reports, translated for display.
QUEST_TRANSLATIONS: dict[str, str] = {
    "Visit a Sanctuary as a juvenile": "Ghé Sanctuary khi còn non",
    "Get nested in": "Được sinh ra từ tổ",
    "Get perfect diet (1% of each)": "Đủ 3 chất dinh dưỡng (mỗi chất ≥ 1%)",
    "Visit Mass Migration zone": "Ghé vùng Đại di cư",
    "Visit 2 Migration zones": "Ghé 2 vùng Di cư",
    "Visit 4 Patrol zones": "Ghé 4 vùng Tuần tra",
    "Never be Infertile": "Không bị Vô sinh",
    "Never get Muscle spasms": "Không bị Co thắt cơ",
    "Raise children to Subadult": "Nuôi con tới Subadult",
    "Be a Hypsi, Troodon, Beipi, Dryo or Deino": "Chơi Hypsi / Troodon / Beipi / Dryo / Deino",
}


def translate_quest(name: str) -> str:
    return QUEST_TRANSLATIONS.get(name.strip(), name)


@dataclass(frozen=True)
class PrimeQuest:
    name: str
    done: bool


@dataclass(frozen=True)
class IslePilotStatus:
    steam_id: str
    online: bool
    server: Optional[str]
    species: Optional[str]
    growth: Optional[float]
    health: Optional[float]
    max_health: Optional[float]
    hunger: Optional[float]
    max_hunger: Optional[float]
    thirst: Optional[float]
    max_thirst: Optional[float]
    stamina: Optional[float]
    max_stamina: Optional[float]
    pos_x: Optional[float]
    pos_y: Optional[float]
    pos_z: Optional[float]
    pos_yaw: Optional[float]
    prime_done: int
    prime_required: int
    prime_total: int
    quests: tuple[PrimeQuest, ...]

    @staticmethod
    def from_json(data: dict) -> "IslePilotStatus":
        position = data.get("position") or {}
        prime = data.get("prime") or {}
        quests = tuple(
            PrimeQuest(name=str(quest.get("name") or ""), done=bool(quest.get("done")))
            for quest in (prime.get("quests") or [])
        )
        return IslePilotStatus(
            steam_id=str(data.get("steamId") or ""),
            online=bool(data.get("online")),
            server=data.get("server"),
            species=data.get("species"),
            growth=_num(data.get("growth")),
            health=_num(data.get("health")),
            max_health=_num(data.get("maxHealth")),
            hunger=_num(data.get("hunger")),
            max_hunger=_num(data.get("maxHunger")),
            thirst=_num(data.get("thirst")),
            max_thirst=_num(data.get("maxThirst")),
            stamina=_num(data.get("stamina")),
            max_stamina=_num(data.get("maxStamina")),
            pos_x=_num(position.get("x")),
            pos_y=_num(position.get("y")),
            pos_z=_num(position.get("z")),
            pos_yaw=_num(position.get("yaw")),
            prime_done=int(prime.get("done") or 0),
            prime_required=int(prime.get("required") or 0),
            prime_total=int(prime.get("total") or 0),
            quests=quests,
        )


def _num(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------- #
# Steam login — a one-shot embedded browser window. The user authenticates
# with Steam directly (their password never passes through this app). On
# success IslePilot's callback page tries to redirect the browser to the
# custom "isle-overlay://" scheme, embedding the player's overlay token in
# the URL. No OS protocol handler is required: we read the token straight
# out of the page HTML (the redirect script is inline, plain text) each
# time a navigation completes, so a failed/no-op custom-scheme navigation
# doesn't matter.
# --------------------------------------------------------------------- #


def login_via_steam() -> Optional[tuple[str, str]]:
    """Blocking. Opens a login window and returns (steam_id, token) or None."""
    result: dict[str, str] = {}

    def _check_for_callback() -> None:
        if result:
            return
        try:
            html = window.evaluate_js("document.documentElement.outerHTML")
        except Exception:
            return
        if not html:
            return
        match = CALLBACK_PATTERN.search(html)
        if match:
            result["sid"] = match.group("sid")
            result["token"] = match.group("token")
            window.destroy()

    window = webview.create_window(
        LOGIN_WINDOW_TITLE,
        html=_LOADING_HTML,
        width=460,
        height=640,
        on_top=True,
    )
    window.events.loaded += _check_for_callback

    def _navigate_to_login() -> None:
        # WebView2's first-ever launch spins up its own browser process,
        # which can take a few seconds — show placeholder text immediately
        # (above) instead of a blank window while that happens, then swap
        # to the real login page once the window is actually on screen.
        window.load_url(LOGIN_URL)

    window.events.shown += _navigate_to_login

    # Force the WebView2-based backend: it's the only one this app bundles
    # (see The-Maps.spec excludes) and it's what ships with Windows 10/11.
    webview.start(gui="edgechromium")

    if "sid" in result and "token" in result:
        return result["sid"], result["token"]
    return None


def run_login_subprocess() -> Optional[tuple[str, str]]:
    """Runs login_via_steam() in a fresh child process.

    pywebview refuses to start on any thread other than its process's main
    thread, and this app's main thread is already owned by Tkinter's
    mainloop — so the login window is launched as a short-lived helper
    process instead (re-invoking this same executable/script with
    LOGIN_SUBPROCESS_FLAG), keeping the main app fully responsive while the
    user is signing in. Safe to call from a background thread.
    """
    if getattr(sys, "frozen", False):
        command = [sys.executable, LOGIN_SUBPROCESS_FLAG]
    else:
        app_path = Path(__file__).resolve().parent / "app.py"
        command = [sys.executable, str(app_path), LOGIN_SUBPROCESS_FLAG]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=LOGIN_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    for line in reversed(completed.stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not payload:
            return None
        try:
            return str(payload["steam_id"]), str(payload["token"])
        except (KeyError, TypeError):
            return None
    return None


# --------------------------------------------------------------------- #
# IslePilot status polling — vitals/quests + slow position fallback.
# --------------------------------------------------------------------- #


class IslePilotSession:
    def __init__(
        self,
        token: str,
        on_status: Callable[[IslePilotStatus], None],
        on_error: Callable[[str], None],
    ) -> None:
        self._token = token
        self._on_status = on_status
        self._on_error = on_error
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        session = requests.Session()
        session.headers.update(
            {
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                "X-Overlay-Version": OVERLAY_VERSION,
            }
        )
        while not self._stop.is_set():
            try:
                response = session.get(ME_URL, timeout=REQUEST_TIMEOUT_SECONDS)
                if response.status_code in (401, 403):
                    self._on_error("expired")
                    return
                response.raise_for_status()
                self._on_status(IslePilotStatus.from_json(response.json()))
            except (requests.RequestException, ValueError):
                pass
            self._stop.wait(POLL_INTERVAL_SECONDS)


# --------------------------------------------------------------------- #
# Credential storage — DPAPI-encrypted (tied to the current Windows user),
# same security model as the reference IsleLiveMap client.
# --------------------------------------------------------------------- #


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_protect(plaintext: str) -> bytes:
    data = plaintext.encode("utf-8")
    buf = ctypes.create_string_buffer(data, len(data))
    in_blob = _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out_blob = _DataBlob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    )
    if not ok:
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(ciphertext: bytes) -> str:
    buf = ctypes.create_string_buffer(ciphertext, len(ciphertext))
    in_blob = _DataBlob(len(ciphertext), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out_blob = _DataBlob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    )
    if not ok:
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def save_credentials(path: Path, steam_id: str, token: str) -> None:
    payload = json.dumps({"steam_id": steam_id, "token": token})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_dpapi_protect(payload))


def load_credentials(path: Path) -> Optional[tuple[str, str]]:
    if not path.exists():
        return None
    try:
        payload = json.loads(_dpapi_unprotect(path.read_bytes()))
        return str(payload["steam_id"]), str(payload["token"])
    except Exception:
        return None


def clear_credentials(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


# --------------------------------------------------------------------- #
# Foreground-window detection — out-of-process only (EnumWindows +
# GetForegroundWindow). No memory reads, no hooks into the game process.
# --------------------------------------------------------------------- #

_GAME_WINDOW_TITLES = ("the isle", "theisle")


def _find_game_hwnd() -> Optional[int]:
    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd: int, _lparam: int) -> bool:
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip().lower()
        if title in _GAME_WINDOW_TITLES or title.startswith("the isle"):
            found.append(hwnd)
        return True

    user32.EnumWindows(_enum, 0)
    return found[0] if found else None


def is_game_foreground() -> bool:
    user32 = ctypes.windll.user32
    hwnd = _find_game_hwnd()
    if not hwnd:
        return False
    return user32.GetForegroundWindow() == hwnd
