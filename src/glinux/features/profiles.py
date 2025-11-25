"""Application profile manager for GLinux.

Automatically switches device profiles based on the active application.
"""

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from threading import Event, Thread
from typing import Callable

from ..core.config import ApplicationProfile, DeviceConfig

logger = logging.getLogger(__name__)


@dataclass
class ActiveWindow:
    """Information about the currently active window."""

    window_id: str
    window_name: str
    process_name: str
    executable_path: str


class ApplicationMonitor:
    """Monitors the active application and triggers profile switches."""

    def __init__(
        self,
        on_app_change: Callable[[ActiveWindow], None] | None = None,
        poll_interval: float = 1.0,
    ):
        """Initialize application monitor.

        Args:
            on_app_change: Callback when active application changes
            poll_interval: Seconds between checking active window
        """
        self._on_app_change = on_app_change
        self._poll_interval = poll_interval
        self._running = False
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._last_window: ActiveWindow | None = None

    def start(self) -> None:
        """Start monitoring active application."""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self._thread = Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("Application monitor started")

    def stop(self) -> None:
        """Stop monitoring."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("Application monitor stopped")

    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while not self._stop_event.is_set():
            try:
                current = self._get_active_window()
                if current and (
                    not self._last_window
                    or current.process_name != self._last_window.process_name
                ):
                    self._last_window = current
                    if self._on_app_change:
                        self._on_app_change(current)
            except Exception as e:
                logger.debug(f"Error getting active window: {e}")

            self._stop_event.wait(self._poll_interval)

    def _get_active_window(self) -> ActiveWindow | None:
        """Get information about the active window."""
        # Try different methods based on desktop environment
        window = self._get_window_x11()
        if not window:
            window = self._get_window_wayland()
        return window

    def _get_window_x11(self) -> ActiveWindow | None:
        """Get active window info using X11/xdotool."""
        try:
            # Get active window ID
            window_id = subprocess.check_output(
                ["xdotool", "getactivewindow"], stderr=subprocess.DEVNULL, text=True
            ).strip()

            # Get window name
            window_name = subprocess.check_output(
                ["xdotool", "getwindowname", window_id],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()

            # Get PID
            pid = subprocess.check_output(
                ["xdotool", "getwindowpid", window_id],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()

            # Get process name and executable
            exe_path = os.readlink(f"/proc/{pid}/exe")
            process_name = os.path.basename(exe_path)

            return ActiveWindow(
                window_id=window_id,
                window_name=window_name,
                process_name=process_name,
                executable_path=exe_path,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            return None

    def _get_window_wayland(self) -> ActiveWindow | None:
        """Get active window info on Wayland (limited support)."""
        # Wayland doesn't have a standard way to get active window
        # This is a placeholder for compositor-specific implementations
        try:
            # Try using wlrctl for wlroots-based compositors
            output = subprocess.check_output(
                ["wlrctl", "toplevel", "focus"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()

            # Parse output (format varies by compositor)
            if output:
                return ActiveWindow(
                    window_id="wayland",
                    window_name=output,
                    process_name=output.split()[0] if output else "",
                    executable_path="",
                )
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        return None

    def get_current_window(self) -> ActiveWindow | None:
        """Get the current active window without waiting for a change."""
        return self._last_window or self._get_active_window()


class ProfileSwitcher:
    """Manages automatic profile switching based on active application."""

    def __init__(self, device_configs: dict[str, DeviceConfig]):
        """Initialize profile switcher.

        Args:
            device_configs: Dictionary of device configurations
        """
        self._device_configs = device_configs
        self._monitor = ApplicationMonitor(on_app_change=self._on_app_change)
        self._profile_change_callbacks: list[
            Callable[[str, str, int], None]
        ] = []  # (device_id, app_name, profile_index)

    def start(self) -> None:
        """Start automatic profile switching."""
        self._monitor.start()

    def stop(self) -> None:
        """Stop automatic profile switching."""
        self._monitor.stop()

    def add_callback(self, callback: Callable[[str, str, int], None]) -> None:
        """Add a callback for profile changes.

        Args:
            callback: Function(device_id, app_name, profile_index)
        """
        self._profile_change_callbacks.append(callback)

    def _on_app_change(self, window: ActiveWindow) -> None:
        """Handle application change."""
        logger.debug(f"Active app changed: {window.process_name}")

        for device_id, config in self._device_configs.items():
            profile_index = self._find_matching_profile(config, window)
            if profile_index is not None:
                logger.info(
                    f"Switching {device_id} to profile {profile_index} "
                    f"for {window.process_name}"
                )
                for callback in self._profile_change_callbacks:
                    callback(device_id, window.process_name, profile_index)

    def _find_matching_profile(
        self, config: DeviceConfig, window: ActiveWindow
    ) -> int | None:
        """Find a matching application profile.

        Args:
            config: Device configuration
            window: Active window info

        Returns:
            Profile index if found, None otherwise
        """
        for app_profile in config.app_profiles:
            # Check if executable matches
            if self._matches_app(app_profile, window):
                # Find profile index by name
                for i, profile in enumerate(config.profiles):
                    if profile.name == app_profile.profile_name:
                        return i
        return None

    def _matches_app(
        self, app_profile: ApplicationProfile, window: ActiveWindow
    ) -> bool:
        """Check if an application profile matches the current window."""
        exe_name = app_profile.executable_name.lower()
        process = window.process_name.lower()

        # Exact match
        if exe_name == process:
            return True

        # Pattern match (simple glob)
        pattern = exe_name.replace("*", ".*").replace("?", ".")
        if re.match(pattern, process):
            return True

        return False

    def add_app_profile(
        self, device_id: str, app_name: str, executable: str, profile_name: str
    ) -> bool:
        """Add an application profile.

        Args:
            device_id: Device ID
            app_name: Display name for the application
            executable: Executable name or pattern
            profile_name: Name of the profile to use

        Returns:
            True if added successfully
        """
        if device_id not in self._device_configs:
            return False

        config = self._device_configs[device_id]

        # Verify profile exists
        profile_exists = any(p.name == profile_name for p in config.profiles)
        if not profile_exists:
            return False

        app_profile = ApplicationProfile(
            app_name=app_name,
            executable_name=executable,
            profile_name=profile_name,
        )
        config.app_profiles.append(app_profile)
        return True

    def remove_app_profile(self, device_id: str, app_name: str) -> bool:
        """Remove an application profile.

        Args:
            device_id: Device ID
            app_name: Application name to remove

        Returns:
            True if removed
        """
        if device_id not in self._device_configs:
            return False

        config = self._device_configs[device_id]
        for i, app_profile in enumerate(config.app_profiles):
            if app_profile.app_name == app_name:
                del config.app_profiles[i]
                return True
        return False

    def get_app_profiles(self, device_id: str) -> list[ApplicationProfile]:
        """Get application profiles for a device."""
        if device_id not in self._device_configs:
            return []
        return self._device_configs[device_id].app_profiles
