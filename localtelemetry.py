from __future__ import annotations

import ctypes
import json
import math
import os
import re
import struct
import subprocess
import tempfile
import threading
import time
import winreg
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

import psutil
import requests

PROCESS_NAME = "TheIsleClient-Win64-Shipping.exe"
NPCAP_REBOOT_REQUIRED_EXIT_CODE = 3010  # ERROR_SUCCESS_REBOOT_REQUIRED
NPCAP_DOWNLOAD_PAGE = "https://npcap.com/#download"
NPCAP_DIST_URL = "https://npcap.com/dist/"
NPCAP_MAX_INSTALLER_BYTES = 20 * 1024 * 1024
_NPCAP_FILE_PATTERN = re.compile(
    r'href=["\'](?P<file>npcap-(?P<version>\d+(?:\.\d+)+)\.exe)["\']',
    re.IGNORECASE,
)

# The successful live test locked this UE movement layout dynamically; nothing
# below hard-codes the observed len/bit-count. The tracker discovers the
# current packet layout again on every game session.
_QUANTIZED_VECTOR_HEADER_BITS = 7
_FLOAT_BITS = 32
_MIN_LOCATION_COMPONENT_BITS = 18
_MIN_COMPONENT_BITS = 1
_MAX_COMPONENT_BITS = 31

_MIN_WORLD_X = -800_000.0
_MAX_WORLD_X = 800_000.0
_MIN_WORLD_Y = -800_000.0
_MAX_WORLD_Y = 800_000.0
_MIN_WORLD_Z = -300_000.0
_MAX_WORLD_Z = 300_000.0
_MAX_ACCELERATION = 100_000.0
_MAX_CLIENT_TIMESTAMP = 10_000_000.0

_HYPOTHESIS_LIFETIME = 1.0
_LOCK_LIFETIME = 2.0
_MIN_BOOTSTRAP_DURATION = 0.600
_MAX_READY_AGE = 0.250
_REQUIRED_CONSECUTIVE_HITS = 8
_TIMESTAMP_REGRESSION_TOLERANCE = 0.002
_TIMESTAMP_ADVANCE_ALLOWANCE_SECONDS = 2.0
_TIMESTAMP_WALL_CLOCK_MULTIPLIER = 4.0
_TIMESTAMP_RECOVERY_AGE = 0.250
_MAXIMUM_BASE_DELTA = 5_000.0
_MAXIMUM_UNITS_PER_SECOND = 100_000.0

# Rendering faster than this is unnecessary for the 220x220 minimap and just
# burns CPU. The network decoder may see more packets than this.
_MIN_PUBLISH_INTERVAL = 0.050  # <= 20 Hz


@dataclass(frozen=True)
class LocalMovementSample:
    x: float
    y: float
    z: float
    yaw: float
    observed_at: float


@dataclass(frozen=True)
class _Candidate:
    x: float
    y: float
    z: float
    yaw: float
    client_timestamp: float
    payload_length: int
    location_bit_offset: int
    component_bit_count: int

    @property
    def layout(self) -> tuple[int, int, int]:
        return (
            self.payload_length,
            self.location_bit_offset,
            self.component_bit_count,
        )


@dataclass
class _Hypothesis:
    candidate: _Candidate
    first_seen: float
    last_seen: float
    consecutive_hits: int


def npcap_installed() -> bool:
    """Best-effort Npcap presence check without opening capture devices."""
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidates = (
        windows / "System32" / "Npcap" / "wpcap.dll",
        windows / "SysWOW64" / "Npcap" / "wpcap.dll",
    )
    if any(path.exists() for path in candidates):
        return True

    registry_views = (
        winreg.KEY_WOW64_64KEY,
        winreg.KEY_WOW64_32KEY,
    )
    for view in registry_views:
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Npcap",
                0,
                winreg.KEY_READ | view,
            ):
                return True
        except OSError:
            pass

    # Last fallback: the NPF driver service is usually named "npcap".
    try:
        completed = subprocess.run(
            ["sc.exe", "query", "npcap"],
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False



def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def get_latest_npcap_installer(timeout: float = 10.0) -> tuple[str, str]:
    """Resolve the latest normal Free/Demo installer from npcap.com itself."""
    response = requests.get(
        NPCAP_DIST_URL,
        timeout=timeout,
        headers={"User-Agent": "The-Maps/2.0"},
    )
    response.raise_for_status()

    matches = [
        (m.group("version"), m.group("file"))
        for m in _NPCAP_FILE_PATTERN.finditer(response.text)
    ]
    if not matches:
        raise RuntimeError("Không tìm thấy Npcap installer trên trang chính thức.")

    version, filename = max(matches, key=lambda item: _version_key(item[0]))
    url = urljoin(NPCAP_DIST_URL, filename)
    parsed = urlparse(url)

    if (
        parsed.scheme != "https"
        or parsed.hostname != "npcap.com"
        or not parsed.path.startswith("/dist/")
        or Path(parsed.path).name != filename
    ):
        raise RuntimeError("Npcap download URL không hợp lệ.")

    return version, url


def download_npcap_installer(
    on_progress: Optional[Callable[[int, Optional[int]], None]] = None,
) -> tuple[str, Path]:
    """Download directly from npcap.com to %TEMP%."""
    version, url = get_latest_npcap_installer()
    target_dir = Path(tempfile.gettempdir()) / "The-Maps" / "Npcap"
    target_dir.mkdir(parents=True, exist_ok=True)

    final_path = target_dir / f"npcap-{version}.exe"
    partial_path = final_path.with_suffix(".exe.part")

    with requests.get(
        url,
        stream=True,
        timeout=(10.0, 30.0),
        headers={"User-Agent": "The-Maps/2.0"},
    ) as response:
        response.raise_for_status()

        total_header = response.headers.get("Content-Length")
        total: Optional[int] = None
        if total_header:
            try:
                total = int(total_header)
            except ValueError:
                total = None

        if total is not None and total > NPCAP_MAX_INSTALLER_BYTES:
            raise RuntimeError("Npcap installer lớn bất thường; đã hủy tải.")

        downloaded = 0
        try:
            with partial_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=128 * 1024):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > NPCAP_MAX_INSTALLER_BYTES:
                        raise RuntimeError("Npcap installer lớn bất thường; đã hủy tải.")
                    handle.write(chunk)
                    if on_progress is not None:
                        on_progress(downloaded, total)
            partial_path.replace(final_path)
        except Exception:
            try:
                partial_path.unlink()
            except FileNotFoundError:
                pass
            raise

    return version, final_path


def verify_npcap_installer(path: Path) -> tuple[bool, str]:
    """Require valid Windows Authenticode signed by Nmap Software LLC."""
    path = Path(path).resolve()
    escaped = str(path).replace("'", "''")
    # GetNameInfo(..SimpleName..) returns just the certificate's CN (e.g.
    # "Nmap Software LLC"), not the full "CN=...,O=...,L=..." Subject DN —
    # lets us compare for an exact match instead of a substring check
    # against the whole DN string.
    script = (
        "$s=Get-AuthenticodeSignature -LiteralPath '" + escaped + "';"
        "$o=[PSCustomObject]@{"
        "Status=$s.Status.ToString();"
        "Subject=if($s.SignerCertificate){"
        "$s.SignerCertificate.GetNameInfo("
        "[Security.Cryptography.X509Certificates.X509NameType]::SimpleName,$false)"
        "}else{''}"
        "};"
        "$o|ConvertTo-Json -Compress"
    )

    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Không kiểm tra được chữ ký số: {exc}"

    if completed.returncode != 0:
        return False, "Windows không xác minh được chữ ký số của Npcap installer."

    try:
        info = json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        return False, "Không đọc được kết quả chữ ký số của Npcap installer."

    status = str(info.get("Status") or "")
    subject = str(info.get("Subject") or "")
    if status.lower() != "valid":
        return False, f"Chữ ký Npcap installer không hợp lệ: {status or 'Unknown'}"

    if subject != "Nmap Software LLC":
        return False, f"Publisher không đúng Nmap Software LLC: {subject or 'Unknown'}"

    return True, subject


class _ShellExecuteInfoW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hKeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SW_SHOWNORMAL = 1
_ERROR_CANCELLED = 1223


def run_npcap_installer(path: Path) -> int:
    """Open the normal graphical installer, elevated.

    The installer's manifest requires Administrator. CreateProcess (which
    is what subprocess.Popen uses on Windows) does NOT elevate on its own —
    it just fails with ERROR_ELEVATION_REQUIRED. Only ShellExecute(Ex) with
    the "runas" verb actually triggers the UAC consent prompt.
    """
    info = _ShellExecuteInfoW()
    info.cbSize = ctypes.sizeof(_ShellExecuteInfoW)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS
    info.hwnd = None
    info.lpVerb = "runas"
    info.lpFile = str(Path(path).resolve())
    info.lpParameters = None
    info.lpDirectory = None
    info.nShow = _SW_SHOWNORMAL

    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.GetLastError()
        if error == _ERROR_CANCELLED:
            raise RuntimeError("Bạn đã hủy yêu cầu quyền Administrator.")
        raise ctypes.WinError(error)

    if not info.hProcess:
        # No process handle back (unusual, but not fatal) — we can't wait
        # for a real exit code. install_npcap_from_official_site's
        # npcap_installed() poll afterward is what actually decides success.
        return 0

    try:
        ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        exit_code = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code))
        return int(exit_code.value)
    finally:
        ctypes.windll.kernel32.CloseHandle(info.hProcess)


def install_npcap_from_official_site(
    on_progress: Optional[Callable[[int, Optional[int]], None]] = None,
) -> tuple[bool, str, bool]:
    """Consent happens in app.py before calling this function.

    Returns (success, message, windows_reboot_required).
    """
    if npcap_installed():
        return True, "Npcap đã được cài.", False

    version, installer = download_npcap_installer(on_progress)
    valid, detail = verify_npcap_installer(installer)
    if not valid:
        try:
            installer.unlink()
        except OSError:
            pass
        return False, detail, False

    exit_code = run_npcap_installer(installer)

    # 3010 = ERROR_SUCCESS_REBOOT_REQUIRED: the install itself succeeded,
    # but the driver won't actually be usable until Windows restarts —
    # polling npcap_installed() right now would just fail, so don't bother.
    if exit_code == NPCAP_REBOOT_REQUIRED_EXIT_CODE:
        return True, (
            f"Npcap {version} đã cài xong nhưng cần khởi động lại Windows "
            "trước khi vị trí realtime hoạt động được."
        ), True

    if exit_code != 0:
        return False, f"Npcap installer kết thúc với mã {exit_code}.", False

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if npcap_installed():
            return True, f"Npcap {version} đã được cài thành công.", False
        time.sleep(0.5)

    return False, (
        f"Npcap {version} installer đã đóng nhưng The-Maps chưa thấy driver. "
        "Có thể cần khởi động lại The-Maps."
    ), False

def _read_bits(payload: bytes, bit_offset: int, bit_count: int) -> int:
    value = 0
    for bit in range(bit_count):
        source_bit = bit_offset + bit
        if payload[source_bit >> 3] & (1 << (source_bit & 7)):
            value |= 1 << bit
    return value


def _read_signed(payload: bytes, bit_offset: int, bit_count: int) -> int:
    value = _read_bits(payload, bit_offset, bit_count)
    sign_bit = 1 << (bit_count - 1)
    return (value ^ sign_bit) - sign_bit


def _bits_needed(value: int) -> int:
    massaged = value ^ (value >> 63)
    return max(1, massaged.bit_length() + 1)


def _uses_canonical_bit_count(x: int, y: int, z: int, component_bits: int) -> bool:
    return max(_bits_needed(x), _bits_needed(y), _bits_needed(z)) == component_bits


def _is_plausible_world_location(x: float, y: float, z: float) -> bool:
    return (
        _MIN_WORLD_X <= x <= _MAX_WORLD_X
        and _MIN_WORLD_Y <= y <= _MAX_WORLD_Y
        and _MIN_WORLD_Z <= z <= _MAX_WORLD_Z
    )


def _try_read_move_prefix(payload: bytes, location_offset: int) -> Optional[float]:
    for acceleration_bits in range(_MIN_COMPONENT_BITS, _MAX_COMPONENT_BITS + 1):
        acceleration_offset = (
            location_offset
            - _QUANTIZED_VECTOR_HEADER_BITS
            - acceleration_bits * 3
        )
        timestamp_offset = acceleration_offset - _FLOAT_BITS
        if timestamp_offset < 0:
            continue

        header = _read_bits(
            payload, acceleration_offset, _QUANTIZED_VECTOR_HEADER_BITS
        )
        if (header & 63) != acceleration_bits:
            continue

        raw_x = _read_signed(
            payload,
            acceleration_offset + _QUANTIZED_VECTOR_HEADER_BITS,
            acceleration_bits,
        )
        raw_y = _read_signed(
            payload,
            acceleration_offset + _QUANTIZED_VECTOR_HEADER_BITS + acceleration_bits,
            acceleration_bits,
        )
        raw_z = _read_signed(
            payload,
            acceleration_offset + _QUANTIZED_VECTOR_HEADER_BITS + acceleration_bits * 2,
            acceleration_bits,
        )
        if not _uses_canonical_bit_count(raw_x, raw_y, raw_z, acceleration_bits):
            continue

        scale = 10.0 if (header & 64) else 1.0
        if max(abs(raw_x / scale), abs(raw_y / scale), abs(raw_z / scale)) > _MAX_ACCELERATION:
            continue

        timestamp_bits = _read_bits(payload, timestamp_offset, _FLOAT_BITS)
        timestamp = struct.unpack("<f", struct.pack("<I", timestamp_bits))[0]
        if (
            math.isfinite(timestamp)
            and 0.0 <= timestamp <= _MAX_CLIENT_TIMESTAMP
        ):
            return timestamp

    return None


def _try_read_axis(payload: bytes, bit_offset: int) -> Optional[tuple[float, int]]:
    if bit_offset >= len(payload) * 8:
        return None

    present = _read_bits(payload, bit_offset, 1) != 0
    bit_offset += 1
    if not present:
        return 0.0, bit_offset

    if bit_offset + 16 > len(payload) * 8:
        return None

    compressed = _read_bits(payload, bit_offset, 16)
    bit_offset += 16
    return compressed * 360.0 / 65_536.0, bit_offset


def _try_read_rotation(payload: bytes, bit_offset: int) -> Optional[tuple[float, float, float]]:
    values: list[float] = []
    for _ in range(3):
        result = _try_read_axis(payload, bit_offset)
        if result is None:
            return None
        value, bit_offset = result
        values.append(value)
    return values[0], values[1], values[2]


def _decode(payload: bytes) -> list[_Candidate]:
    if not payload:
        return []

    candidates: list[_Candidate] = []
    payload_bits = len(payload) * 8
    minimum_move_bits = (
        _QUANTIZED_VECTOR_HEADER_BITS
        + _MIN_LOCATION_COMPONENT_BITS * 3
        + 3
    )

    for location_offset in range(max(0, payload_bits - minimum_move_bits + 1)):
        header = _read_bits(
            payload, location_offset, _QUANTIZED_VECTOR_HEADER_BITS
        )
        component_bits = header & 63

        if (
            not (header & 64)
            or component_bits < _MIN_LOCATION_COMPONENT_BITS
            or component_bits > _MAX_COMPONENT_BITS
            or location_offset
            + _QUANTIZED_VECTOR_HEADER_BITS
            + component_bits * 3
            + 3
            > payload_bits
        ):
            continue

        raw_x = _read_signed(
            payload,
            location_offset + _QUANTIZED_VECTOR_HEADER_BITS,
            component_bits,
        )
        raw_y = _read_signed(
            payload,
            location_offset + _QUANTIZED_VECTOR_HEADER_BITS + component_bits,
            component_bits,
        )
        raw_z = _read_signed(
            payload,
            location_offset + _QUANTIZED_VECTOR_HEADER_BITS + component_bits * 2,
            component_bits,
        )

        if not _uses_canonical_bit_count(raw_x, raw_y, raw_z, component_bits):
            continue

        x, y, z = raw_x / 100.0, raw_y / 100.0, raw_z / 100.0
        if not _is_plausible_world_location(x, y, z):
            continue

        client_timestamp = _try_read_move_prefix(payload, location_offset)
        if client_timestamp is None:
            continue

        rotation_offset = (
            location_offset
            + _QUANTIZED_VECTOR_HEADER_BITS
            + component_bits * 3
        )
        rotation = _try_read_rotation(payload, rotation_offset)
        if rotation is None:
            continue

        _pitch, yaw, _roll = rotation
        candidates.append(
            _Candidate(
                x=x,
                y=y,
                z=z,
                yaw=yaw,
                client_timestamp=client_timestamp,
                payload_length=len(payload),
                location_bit_offset=location_offset,
                component_bit_count=component_bits,
            )
        )

    return candidates


def _distance(left: _Candidate, right: _Candidate) -> float:
    return math.sqrt(
        (right.x - left.x) ** 2
        + (right.y - left.y) ** 2
        + (right.z - left.z) ** 2
    )


def _is_continuous(
    previous: _Candidate,
    previous_at: float,
    current: _Candidate,
    current_at: float,
) -> bool:
    elapsed = max(0.0, current_at - previous_at)
    maximum_delta = _MAXIMUM_BASE_DELTA + _MAXIMUM_UNITS_PER_SECOND * elapsed
    return _distance(previous, current) <= maximum_delta


def _is_plausible_forward_timestamp(
    current: _Candidate,
    candidate: _Candidate,
    elapsed_seconds: float,
) -> bool:
    delta = candidate.client_timestamp - current.client_timestamp
    maximum_advance = (
        _TIMESTAMP_ADVANCE_ALLOWANCE_SECONDS
        + elapsed_seconds * _TIMESTAMP_WALL_CLOCK_MULTIPLIER
    )
    return (
        delta >= -_TIMESTAMP_REGRESSION_TOLERANCE
        and delta <= maximum_advance
    )


class _MovementTracker:
    def __init__(self) -> None:
        self._hypotheses: dict[tuple[int, int, int], _Hypothesis] = {}
        self._current: Optional[_Candidate] = None
        self._last_lock_update = 0.0
        # Survives reset(): other bit-offsets in the same packet (an
        # acceleration/velocity QuantizedVector, for example) can pass every
        # plausibility check just as well as the real location once the
        # player starts moving and those fields stop being all-zero. Without
        # something to anchor to, a fresh bootstrap has no way to prefer the
        # real (far-from-origin, matches where we actually were) candidate
        # over one of these — this is what was locking onto small,
        # near-(0,0,0) decoys mid-flight in practice.
        self._last_known: Optional[_Candidate] = None
        self._last_known_at = 0.0

    def reset(self) -> None:
        self._hypotheses.clear()
        self._current = None
        self._last_lock_update = 0.0

    def try_track(
        self,
        payload: bytes,
        observed_at: float,
    ) -> Optional[_Candidate]:
        candidates = _decode(payload)

        if (
            self._current is not None
            and observed_at - self._last_lock_update <= _LOCK_LIFETIME
        ):
            sample = self._try_continue(candidates, observed_at)
            if sample is not None:
                self._current = sample
                self._last_lock_update = observed_at
                self._last_known = sample
                self._last_known_at = observed_at
                return sample

            # Saved/resend moves can be spatially valid but old. Do not let
            # those force a fresh bootstrap while the current lock is healthy.
            near_old_lock = any(
                _is_continuous(
                    self._current,
                    self._last_lock_update,
                    candidate,
                    observed_at,
                )
                for candidate in candidates
            )
            if near_old_lock:
                return None

        if (
            self._current is not None
            and observed_at - self._last_lock_update > _LOCK_LIFETIME
        ):
            self.reset()

        self._prune(observed_at)

        for candidate in candidates:
            layout = candidate.layout
            hypothesis = self._hypotheses.get(layout)
            if (
                hypothesis is None
                or observed_at - hypothesis.last_seen > _HYPOTHESIS_LIFETIME
                or not _is_continuous(
                    hypothesis.candidate,
                    hypothesis.last_seen,
                    candidate,
                    observed_at,
                )
            ):
                self._hypotheses[layout] = _Hypothesis(
                    candidate,
                    observed_at,
                    observed_at,
                    1,
                )
                continue

            hypothesis.candidate = candidate
            hypothesis.last_seen = observed_at
            hypothesis.consecutive_hits += 1

        ready = [
            hypothesis
            for hypothesis in self._hypotheses.values()
            if hypothesis.consecutive_hits >= _REQUIRED_CONSECUTIVE_HITS
            and observed_at - hypothesis.first_seen >= _MIN_BOOTSTRAP_DURATION
            and observed_at - hypothesis.last_seen <= _MAX_READY_AGE
        ]
        if ready:
            # Other bit-offsets in the same packet (an acceleration/velocity
            # QuantizedVector, say) can pass every plausibility check just as
            # well as the real location once the player is actually moving
            # and those fields stop being all-zero — that's what was locking
            # onto small, near-(0,0,0) decoys mid-flight in practice. If we
            # know roughly where the player last really was, only trust
            # candidates that could plausibly continue from there; if none
            # do, keep waiting instead of committing to an obvious decoy.
            candidates_pool = ready
            if self._last_known is not None:
                anchored = [
                    hypothesis
                    for hypothesis in ready
                    if _is_continuous(
                        self._last_known, self._last_known_at,
                        hypothesis.candidate, observed_at,
                    )
                ]
                if anchored:
                    candidates_pool = anchored
                else:
                    return None

            # component_bit_count is the strongest signal, and the only one
            # that works with zero prior history (cold start, before there's
            # any _last_known to anchor to): the real location spans this
            # map's full world_bounds (~±600k), which needs ~26 bits to
            # quantize, while decoys (acceleration/velocity or a misaligned
            # window) hold much smaller values and need fewer bits.
            # Confirmed against captured logs: every correct lock read
            # bits=26; every decoy read bits=18-24. client_timestamp/hits
            # only break ties within the same bit-width.
            candidates_pool.sort(
                key=lambda hypothesis: (
                    hypothesis.candidate.component_bit_count,
                    hypothesis.candidate.client_timestamp,
                    hypothesis.consecutive_hits,
                ),
                reverse=True,
            )
            winner = candidates_pool[0]
            self._current = winner.candidate
            self._last_lock_update = observed_at
            self._last_known = winner.candidate
            self._last_known_at = observed_at
            self._hypotheses.clear()
            return self._current

        return None

    def _try_continue(
        self,
        candidates: list[_Candidate],
        observed_at: float,
    ) -> Optional[_Candidate]:
        assert self._current is not None

        elapsed = observed_at - self._last_lock_update
        elapsed_seconds = max(0.0, elapsed)
        ranked: list[tuple[bool, _Candidate]] = []

        for candidate in candidates:
            if not _is_continuous(
                self._current,
                self._last_lock_update,
                candidate,
                observed_at,
            ):
                continue

            timestamp_plausible = _is_plausible_forward_timestamp(
                self._current,
                candidate,
                elapsed_seconds,
            )

            if not (
                timestamp_plausible
                or candidate.client_timestamp + _TIMESTAMP_REGRESSION_TOLERANCE
                >= self._current.client_timestamp
                or elapsed >= _TIMESTAMP_RECOVERY_AGE
            ):
                continue

            ranked.append((timestamp_plausible, candidate))

        if not ranked:
            return None

        ranked.sort(
            key=lambda item: (
                not item[0],
                -(item[1].client_timestamp if item[0] else -1e30),
                _distance(self._current, item[1]),
                item[1].location_bit_offset,
            )
        )
        timestamp_plausible, selected = ranked[0]

        if timestamp_plausible:
            return selected

        return _Candidate(
            selected.x,
            selected.y,
            selected.z,
            selected.yaw,
            self._current.client_timestamp + elapsed_seconds,
            selected.payload_length,
            selected.location_bit_offset,
            selected.component_bit_count,
        )

    def _prune(self, observed_at: float) -> None:
        stale = [
            layout
            for layout, hypothesis in self._hypotheses.items()
            if observed_at - hypothesis.last_seen > _HYPOTHESIS_LIFETIME
        ]
        for layout in stale:
            self._hypotheses.pop(layout, None)


_scapy_async_sniffer = None
_scapy_udp = None


def _load_scapy():
    """Import scapy lazily, on first capture attempt rather than at module
    load. Right after a fresh Npcap install, scapy's import-time driver
    probing can throw if the driver isn't fully ready yet (sometimes a real
    Windows restart is needed even when the installer claims success) — if
    that happened at the top of this module, it would crash the whole app
    before _run()'s try/except ever gets a chance to catch it."""
    global _scapy_async_sniffer, _scapy_udp
    if _scapy_async_sniffer is None:
        from scapy.all import AsyncSniffer, UDP
        _scapy_async_sniffer = AsyncSniffer
        _scapy_udp = UDP
    return _scapy_async_sniffer, _scapy_udp


class LocalMovementSession:
    """Npcap-backed local X/Y/Z/Yaw stream for The Isle.

    on_state receives one of:
      - "npcap_missing"
      - "waiting_game"
      - "waiting_packets"
      - "tracking"
      - "capture_error"
    """

    def __init__(
        self,
        on_sample: Callable[[LocalMovementSample], None],
        on_state: Callable[[str], None],
    ) -> None:
        self._on_sample = on_sample
        self._on_state = on_state
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sniffer: Optional[AsyncSniffer] = None
        self._ports: set[int] = set()
        self._ports_lock = threading.Lock()
        self._tracker = _MovementTracker()
        self._last_publish_at = 0.0
        self._last_published: Optional[tuple[float, float, float, float]] = None
        self._tracking_announced = False

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        sniffer = self._sniffer
        if sniffer is not None:
            try:
                # join=False: this runs on the Tk main thread (app.py's
                # _exit()). scapy's AsyncSniffer.join() has no timeout, and
                # on Windows/Npcap the select()-based wakeup that's supposed
                # to interrupt the sniff loop doesn't always fire promptly,
                # so a blocking join() here can hang the whole UI on exit.
                # The sniff thread is itself daemon=True (sendrecv.py), so
                # it's reaped on process exit regardless of whether it ever
                # notices stop_cb() in time.
                sniffer.stop(join=False)
            except Exception:
                pass
        self._sniffer = None

    def _run(self) -> None:
        if not npcap_installed():
            self._on_state("npcap_missing")
            return

        try:
            async_sniffer, _udp = _load_scapy()
            self._sniffer = async_sniffer(
                filter="udp",
                prn=self._handle_packet,
                store=False,
            )
            self._sniffer.start()
        except Exception:
            self._on_state("capture_error")
            return

        last_pid: Optional[int] = None
        last_ports: set[int] = set()

        try:
            while not self._stop.wait(1.0):
                pid = self._find_game_pid()
                if pid is None:
                    if last_pid is not None:
                        self._tracker.reset()
                        self._tracking_announced = False
                    last_pid = None
                    last_ports = set()
                    with self._ports_lock:
                        self._ports = set()
                    self._on_state("waiting_game")
                    continue

                ports = self._get_udp_ports(pid)
                if pid != last_pid or ports != last_ports:
                    self._tracker.reset()
                    self._tracking_announced = False
                    last_pid = pid
                    last_ports = ports
                    with self._ports_lock:
                        self._ports = set(ports)

                if not ports:
                    self._on_state("waiting_packets")
                elif not self._tracking_announced:
                    self._on_state("waiting_packets")
        finally:
            sniffer = self._sniffer
            self._sniffer = None
            if sniffer is not None:
                try:
                    sniffer.stop(join=False)
                except Exception:
                    pass

    def _handle_packet(self, packet) -> None:
        try:
            _async_sniffer, udp_layer = _load_scapy()
            if udp_layer not in packet:
                return
            udp = packet[udp_layer]

            with self._ports_lock:
                ports = self._ports
                if not ports or int(udp.sport) not in ports:
                    return

            payload = bytes(udp.payload)
            if not payload:
                return

            now = time.monotonic()
            sample = self._tracker.try_track(payload, now)
            if sample is None:
                return

            if not self._tracking_announced:
                self._tracking_announced = True
                self._on_state("tracking")

            signature = (sample.x, sample.y, sample.z, sample.yaw)
            if signature == self._last_published:
                return
            if now - self._last_publish_at < _MIN_PUBLISH_INTERVAL:
                return

            self._last_publish_at = now
            self._last_published = signature
            self._on_sample(
                LocalMovementSample(
                    sample.x,
                    sample.y,
                    sample.z,
                    sample.yaw,
                    now,
                )
            )
        except Exception:
            # Unrelated/malformed UDP packets must never kill the capture loop.
            return

    @staticmethod
    def _find_game_pid() -> Optional[int]:
        for process in psutil.process_iter(["pid", "name"]):
            try:
                if (process.info["name"] or "").lower() == PROCESS_NAME.lower():
                    return int(process.info["pid"])
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
        return None

    @staticmethod
    def _get_udp_ports(pid: int) -> set[int]:
        ports: set[int] = set()
        try:
            connections = psutil.net_connections(kind="udp")
        except (psutil.AccessDenied, OSError):
            return ports

        for connection in connections:
            if connection.pid != pid or not connection.laddr:
                continue
            try:
                ports.add(int(connection.laddr.port))
            except AttributeError:
                try:
                    ports.add(int(connection.laddr[1]))
                except (IndexError, TypeError, ValueError):
                    pass
        return ports
