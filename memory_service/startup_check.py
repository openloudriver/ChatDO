"""
Startup checks for Memory Service to prevent duplicate instances.
"""
import socket
import sys
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# PID file location
PID_FILE = Path.home() / ".chatdo" / "memory_service.pid"
LOCK_FILE = Path.home() / ".chatdo" / "memory_service.lock"


def check_port_available(host: str, port: int) -> bool:
    """Check if a port is available for binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False


def check_existing_instance(host: str, port: int) -> tuple[bool, str]:
    """
    Check if another Memory Service instance is already running.
    
    Returns:
        Tuple of (is_running: bool, message: str)
    """
    # Method 1: Check if port is already bound
    if not check_port_available(host, port):
        # Try to connect to see if it's actually Memory Service
        try:
            import requests
            response = requests.get(f"http://{host}:{port}/health", timeout=1)
            if response.status_code == 200:
                return True, f"Memory Service is already running on {host}:{port}"
        except Exception:
            # Port is bound but not responding - might be a different service
            return True, f"Port {port} is already in use (may not be Memory Service)"
    
    # Method 2: Check PID file
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            # Check if process is still running
            try:
                os.kill(pid, 0)  # Signal 0 doesn't kill, just checks if process exists
                # Process exists - check if it's actually Memory Service
                try:
                    import psutil
                    proc = psutil.Process(pid)
                    cmdline = " ".join(proc.cmdline())
                    if "memory_service.api" in cmdline or "uvicorn" in cmdline:
                        return True, f"Memory Service process {pid} is already running (found via PID file)"
                except ImportError:
                    # psutil not available - skip process check
                    pass
                except Exception:
                    pass
            except ProcessLookupError:
                # PID file exists but process is dead - stale file
                PID_FILE.unlink(missing_ok=True)
        except (ValueError, FileNotFoundError):
            # Invalid PID file - remove it
            PID_FILE.unlink(missing_ok=True)
    
    return False, ""


def create_pid_file() -> bool:
    """Create PID file for current process."""
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))
        return True
    except Exception as e:
        logger.warning(f"Failed to create PID file: {e}")
        return False


def remove_pid_file():
    """Remove PID file."""
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except Exception as e:
        logger.warning(f"Failed to remove PID file: {e}")


def acquire_lock() -> bool:
    """
    Acquire a file lock to prevent multiple instances.
    Uses a simple file-based lock mechanism.
    """
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Try to create lock file exclusively
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            # Lock file exists - check if process is still alive
            try:
                pid = int(LOCK_FILE.read_text().strip())
                os.kill(pid, 0)  # Check if process exists
                return False  # Process is alive, can't acquire lock
            except (ValueError, ProcessLookupError, FileNotFoundError):
                # Stale lock file - remove it and try again
                LOCK_FILE.unlink(missing_ok=True)
                return acquire_lock()
    except Exception as e:
        logger.warning(f"Failed to acquire lock: {e}")
        return False


def release_lock():
    """Release the file lock."""
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except Exception as e:
        logger.warning(f"Failed to release lock: {e}")

