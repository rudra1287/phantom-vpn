import os
import signal
import asyncio
import hashlib
import shutil
import socket
import subprocess
import time

from dataclasses import dataclass
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
USER_DATA = BASE / "user-data"
RUNTIME = BASE / "desktop-runtime"

CHROMIUM = Path(
    "/home/codespace/.cache/ms-playwright/"
    "chromium-1254/chrome-linux64/chrome"
)

MAX_SESSIONS = 4
SESSION_TTL = 8 * 60 * 60
TICKET_TTL = 45

DISPLAY_RANGE = range(100, 110)
VNC_PORT_RANGE = range(5910, 5920)

sessions = {}
tickets = {}
session_lock = asyncio.Lock()


class ExistingProcess:
    """A safe handle for a process started by an earlier backend instance."""

    def __init__(self, pid):
        self.pid = int(pid)
        info = self._info(self.pid)
        if info is None:
            raise ProcessLookupError(self.pid)
        self.start_time = info["start_time"]

    @staticmethod
    def _info(pid):
        try:
            raw = Path(f"/proc/{pid}/stat").read_text()
            fields = raw[raw.rfind(")") + 2:].split()
            return {
                "state": fields[0],
                "pgid": int(fields[2]),
                "sid": int(fields[3]),
                "start_time": fields[19],
            }
        except (OSError, ValueError, IndexError):
            return None

    def poll(self):
        info = self._info(self.pid)
        if info is None or info["start_time"] != self.start_time:
            return 0
        return None

    def wait(self, timeout=None):
        started = time.monotonic()

        while self.poll() is None:
            if timeout is not None and time.monotonic() - started >= timeout:
                raise subprocess.TimeoutExpired(str(self.pid), timeout)
            time.sleep(0.05)

        return 0


@dataclass
class DesktopSession:
    user_id: str
    display: int
    vnc_port: int
    profile: Path
    xvfb: object
    vnc: object
    chromium: object
    created_at: float
    last_used: float


def user_directory(user_id: str) -> Path:
    safe_id = hashlib.sha256(user_id.encode()).hexdigest()
    path = USER_DATA / safe_id
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def port_available(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def display_available(display: int) -> bool:
    return (
        not Path(f"/tmp/.X11-unix/X{display}").exists()
        and not Path(f"/tmp/.X{display}-lock").exists()
    )


def allocate_resources():
    used_displays = {s.display for s in sessions.values()}
    used_ports = {s.vnc_port for s in sessions.values()}

    for display in DISPLAY_RANGE:
        if display in used_displays or not display_available(display):
            continue

        for port in VNC_PORT_RANGE:
            if port in used_ports or not port_available(port):
                continue

            return display, port

    raise RuntimeError("No isolated desktop resources available")


def _process_arguments(pid):
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        return [x.decode(errors="replace") for x in raw.split(b"\0") if x]
    except OSError:
        return []


def _process_environment(pid):
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
        result = {}
        for item in raw.split(b"\0"):
            if b"=" in item:
                key, value = item.split(b"=", 1)
                result[key.decode(errors="replace")] = value.decode(errors="replace")
        return result
    except OSError:
        return {}


def _managed_process(pid):
    try:
        process = ExistingProcess(pid)
        info = process._info(pid)

        # Only accept original process-group leaders. This ensures that
        # stopping a recovered process cannot terminate unrelated processes.
        if info["pgid"] != pid or info["sid"] != pid:
            return None

        return process
    except (ProcessLookupError, OSError, ValueError):
        return None


def _find_chromium(profile):
    expected_profile = str(profile.resolve())
    matches = []

    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue

        pid = int(entry.name)
        args = _process_arguments(pid)

        if not args or args[0] != str(CHROMIUM):
            continue

        profile_arg = f"--user-data-dir={expected_profile}"
        if profile_arg not in args:
            continue

        env = _process_environment(pid)
        display_value = env.get("DISPLAY", "")

        if not display_value.startswith(":"):
            continue

        try:
            display = int(display_value[1:])
        except ValueError:
            continue

        process = _managed_process(pid)
        if process:
            matches.append((process, display))

    if len(matches) > 1:
        raise RuntimeError(
            f"Multiple Chromium instances found for profile {profile}"
        )

    return matches[0] if matches else None


def _find_xvfb(display):
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue

        pid = int(entry.name)
        args = _process_arguments(pid)

        if (
            args
            and Path(args[0]).name == "Xvfb"
            and len(args) > 1
            and args[1] == f":{display}"
        ):
            process = _managed_process(pid)
            if process:
                return process

    return None


def _find_vnc(display):
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue

        pid = int(entry.name)
        args = _process_arguments(pid)

        if not args or Path(args[0]).name != "x11vnc":
            continue

        if "-display" not in args or "-rfbport" not in args:
            continue

        try:
            display_index = args.index("-display")
            port_index = args.index("-rfbport")

            if args[display_index + 1] != f":{display}":
                continue

            if "-localhost" not in args:
                continue

            port = int(args[port_index + 1])
        except (ValueError, IndexError):
            continue

        process = _managed_process(pid)
        if process:
            return process, port

    return None


def _profile_has_lock(profile):
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        if os.path.lexists(profile / name):
            return True
    return False


async def recover_sessions():
    """Rebuild the in-memory registry without restarting existing desktops."""

    from app.auth import connect

    recovered = 0

    async with session_lock:
        with connect() as db:
            users = db.execute(
                "SELECT id FROM users WHERE active=1"
            ).fetchall()

        for row in users:
            user_id = row["id"]
            profile = USER_DATA / hashlib.sha256(
                user_id.encode()
            ).hexdigest()

            if not profile.is_dir():
                continue

            try:
                chromium_result = _find_chromium(profile)

                if not chromium_result:
                    continue

                chromium, display = chromium_result
                xvfb = _find_xvfb(display)
                vnc_result = _find_vnc(display)

                if not xvfb or not vnc_result:
                    print(
                        f"[DESKTOP RECOVERY] Incomplete processes "
                        f"for user {user_id}, display :{display}"
                    )
                    continue

                vnc, port = vnc_result

                if port not in VNC_PORT_RANGE:
                    print(
                        f"[DESKTOP RECOVERY] Unexpected VNC port {port}"
                    )
                    continue

                if not Path(f"/tmp/.X11-unix/X{display}").exists():
                    continue

                with socket.socket() as sock:
                    sock.settimeout(1)
                    if sock.connect_ex(("127.0.0.1", port)) != 0:
                        continue

                if any(
                    process.poll() is not None
                    for process in (xvfb, vnc, chromium)
                ):
                    continue

                now = time.time()

                sessions[user_id] = DesktopSession(
                    user_id=user_id,
                    display=display,
                    vnc_port=port,
                    profile=profile,
                    xvfb=xvfb,
                    vnc=vnc,
                    chromium=chromium,
                    created_at=now,
                    last_used=now,
                )

                recovered += 1

                print(
                    f"[DESKTOP RECOVERY] Restored user={user_id} "
                    f"display=:{display} vnc={port} "
                    f"chromium_pid={chromium.pid}"
                )

            except Exception as exc:
                print(
                    f"[DESKTOP RECOVERY] Could not restore "
                    f"user={user_id}: {exc}"
                )

    print(f"[DESKTOP RECOVERY] Restored {recovered} desktop(s)")
    return recovered


def start_xvfb(display: int) -> subprocess.Popen:
    process = subprocess.Popen(
        [
            "Xvfb",
            f":{display}",
            "-screen", "0", "1280x800x24",
            "-nolisten", "tcp",
            "-noreset",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    time.sleep(1)

    if process.poll() is not None:
        raise RuntimeError(f"Xvfb failed on display :{display}")

    return process


def start_vnc(display: int, port: int) -> subprocess.Popen:
    process = subprocess.Popen(
        [
            "x11vnc",
            "-display", f":{display}",
            "-localhost",
            "-nopw",
            "-forever",
            "-shared",
            "-rfbport", str(port),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    time.sleep(1)

    if process.poll() is not None:
        raise RuntimeError(f"VNC failed on port {port}")

    return process


def start_chromium(display: int, profile: Path) -> subprocess.Popen:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile.chmod(0o700)

    log_path = RUNTIME / f"chromium-{display}.log"
    log_handle = open(log_path, "a")

    try:
        process = subprocess.Popen(
            [
                str(CHROMIUM),
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={profile}",
                "--window-size=1280,800",
                "about:blank",
            ],
            env={**os.environ, "DISPLAY": f":{display}"},
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_handle.close()

    time.sleep(3)

    if process.poll() is not None:
        details = log_path.read_text(errors="replace")[-4000:]
        raise RuntimeError(
            f"Chromium failed on display :{display}. Details: {details}"
        )

    return process


def stop_process(process) -> None:
    if process is None or process.poll() is not None:
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
    except ProcessLookupError:
        pass


async def create_session(user_id: str) -> DesktopSession:
    async with session_lock:
        if user_id in sessions:
            session = sessions[user_id]

            if all(
                p.poll() is None
                for p in (session.xvfb, session.vnc, session.chromium)
            ):
                session.last_used = time.time()
                return session

            raise RuntimeError(
                "Existing desktop session is incomplete. "
                "Please recover or inspect it before starting another."
            )

        if len(sessions) >= MAX_SESSIONS:
            raise RuntimeError("Maximum desktop sessions reached")

        profile = user_directory(user_id)

        if _profile_has_lock(profile):
            raise RuntimeError(
                "This browser profile is already locked by an existing "
                "Chromium process. Refusing to start a duplicate browser."
            )

        display, port = allocate_resources()

        xvfb = vnc = chromium = None

        try:
            xvfb = start_xvfb(display)
            vnc = start_vnc(display, port)
            chromium = start_chromium(display, profile)

            now = time.time()

            session = DesktopSession(
                user_id=user_id,
                display=display,
                vnc_port=port,
                profile=profile,
                xvfb=xvfb,
                vnc=vnc,
                chromium=chromium,
                created_at=now,
                last_used=now,
            )

            sessions[user_id] = session
            return session

        except Exception:
            stop_process(chromium)
            stop_process(vnc)
            stop_process(xvfb)
            raise


async def stop_session(user_id: str) -> bool:
    async with session_lock:
        session = sessions.pop(user_id, None)

        if session is None:
            return False

        stop_process(session.chromium)
        stop_process(session.vnc)
        stop_process(session.xvfb)

        return True
