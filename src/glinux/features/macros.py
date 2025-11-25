"""Macro system for GLinux.

Provides macro recording, playback, and management functionality
with support for key sequences, delays, and mouse actions.
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from threading import Event, Thread
from typing import Callable

from ..core.config import Macro, MacroAction

logger = logging.getLogger(__name__)


class MacroActionType(Enum):
    """Types of macro actions."""

    KEY_PRESS = "keypress"
    KEY_DOWN = "keydown"
    KEY_UP = "keyup"
    DELAY = "delay"
    MOUSE_CLICK = "mouse_click"
    MOUSE_MOVE = "mouse_move"
    MOUSE_SCROLL = "mouse_scroll"


# Key code mapping (subset of common keys)
KEY_CODES = {
    "a": 0x04,
    "b": 0x05,
    "c": 0x06,
    "d": 0x07,
    "e": 0x08,
    "f": 0x09,
    "g": 0x0A,
    "h": 0x0B,
    "i": 0x0C,
    "j": 0x0D,
    "k": 0x0E,
    "l": 0x0F,
    "m": 0x10,
    "n": 0x11,
    "o": 0x12,
    "p": 0x13,
    "q": 0x14,
    "r": 0x15,
    "s": 0x16,
    "t": 0x17,
    "u": 0x18,
    "v": 0x19,
    "w": 0x1A,
    "x": 0x1B,
    "y": 0x1C,
    "z": 0x1D,
    "1": 0x1E,
    "2": 0x1F,
    "3": 0x20,
    "4": 0x21,
    "5": 0x22,
    "6": 0x23,
    "7": 0x24,
    "8": 0x25,
    "9": 0x26,
    "0": 0x27,
    "enter": 0x28,
    "escape": 0x29,
    "backspace": 0x2A,
    "tab": 0x2B,
    "space": 0x2C,
    "f1": 0x3A,
    "f2": 0x3B,
    "f3": 0x3C,
    "f4": 0x3D,
    "f5": 0x3E,
    "f6": 0x3F,
    "f7": 0x40,
    "f8": 0x41,
    "f9": 0x42,
    "f10": 0x43,
    "f11": 0x44,
    "f12": 0x45,
    "ctrl": 0xE0,
    "shift": 0xE1,
    "alt": 0xE2,
    "meta": 0xE3,
}

# Modifier key masks
MODIFIER_MASKS = {
    "ctrl": 0x01,
    "shift": 0x02,
    "alt": 0x04,
    "meta": 0x08,
}


@dataclass
class MacroPlaybackState:
    """State of a macro playback."""

    macro: Macro
    current_action: int
    repeat_count: int
    is_running: bool
    stop_event: Event


class MacroPlayer:
    """Plays back macros by simulating input events."""

    def __init__(self, input_sender: Callable[[MacroAction], None] | None = None):
        """Initialize macro player.

        Args:
            input_sender: Function to send input events. If None, events are logged.
        """
        self._input_sender = input_sender or self._default_sender
        self._active_playbacks: dict[str, MacroPlaybackState] = {}
        self._threads: dict[str, Thread] = {}

    def _default_sender(self, action: MacroAction) -> None:
        """Default action sender that just logs the action."""
        logger.debug(f"Macro action: {action.action_type} = {action.value}")

    def play_macro(
        self, macro: Macro, blocking: bool = False, hold_key: bool = False  # noqa: ARG002
    ) -> str | None:
        """Play a macro.

        Args:
            macro: The macro to play
            blocking: If True, wait for macro to complete
            hold_key: If True, repeat while this method's caller holds

        Returns:
            Playback ID for non-blocking calls, None for blocking
        """
        playback_id = f"{macro.name}_{time.time()}"
        stop_event = Event()

        state = MacroPlaybackState(
            macro=macro,
            current_action=0,
            repeat_count=0,
            is_running=True,
            stop_event=stop_event,
        )

        self._active_playbacks[playback_id] = state

        if blocking:
            self._play_macro_thread(state)
            del self._active_playbacks[playback_id]
            return None
        else:
            thread = Thread(
                target=self._play_macro_thread, args=(state,), daemon=True
            )
            self._threads[playback_id] = thread
            thread.start()
            return playback_id

    def _play_macro_thread(self, state: MacroPlaybackState) -> None:
        """Thread function to play a macro."""
        macro = state.macro
        repeat_count = macro.repeat_count if not macro.repeat_while_held else 1000000

        for _ in range(repeat_count):
            if state.stop_event.is_set():
                break

            for action in macro.actions:
                if state.stop_event.is_set():
                    break

                self._execute_action(action, state.stop_event)
                state.current_action += 1

            state.repeat_count += 1
            state.current_action = 0

        state.is_running = False

    def _execute_action(self, action: MacroAction, stop_event: Event | None = None) -> None:
        """Execute a single macro action."""
        if action.action_type == "delay":
            # Delay value is in milliseconds
            delay_ms = action.value if isinstance(action.value, int) else 0
            # Use stop_event.wait() for interruptible delays
            if stop_event:
                stop_event.wait(delay_ms / 1000.0)
            else:
                time.sleep(delay_ms / 1000.0)
        else:
            self._input_sender(action)

    def stop_macro(self, playback_id: str) -> bool:
        """Stop a running macro playback.

        Args:
            playback_id: The playback ID returned by play_macro

        Returns:
            True if stopped, False if not found
        """
        if playback_id in self._active_playbacks:
            self._active_playbacks[playback_id].stop_event.set()
            return True
        return False

    def stop_all(self) -> None:
        """Stop all running macro playbacks."""
        for state in self._active_playbacks.values():
            state.stop_event.set()

    def is_playing(self, playback_id: str) -> bool:
        """Check if a macro is still playing."""
        if playback_id in self._active_playbacks:
            return self._active_playbacks[playback_id].is_running
        return False


class MacroRecorder:
    """Records macros from user input."""

    def __init__(self):
        """Initialize macro recorder."""
        self._recording = False
        self._actions: list[MacroAction] = []
        self._last_action_time: float | None = None
        self._record_delays = True

    def start_recording(self, record_delays: bool = True) -> None:
        """Start recording a macro.

        Args:
            record_delays: If True, record delays between actions
        """
        self._recording = True
        self._actions = []
        self._last_action_time = time.time()
        self._record_delays = record_delays
        logger.info("Macro recording started")

    def stop_recording(self, name: str = "New Macro") -> Macro:
        """Stop recording and return the recorded macro.

        Args:
            name: Name for the recorded macro

        Returns:
            The recorded macro
        """
        self._recording = False
        macro = Macro(name=name, actions=self._actions)
        self._actions = []
        self._last_action_time = None
        logger.info(f"Macro recording stopped: {len(macro.actions)} actions")
        return macro

    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._recording

    def record_action(self, action: MacroAction) -> None:
        """Record an action.

        Args:
            action: The action to record
        """
        if not self._recording:
            return

        current_time = time.time()

        # Add delay action if enabled
        if self._record_delays and self._last_action_time:
            delay_ms = int((current_time - self._last_action_time) * 1000)
            if delay_ms > 10:  # Only record delays > 10ms
                delay_action = MacroAction(action_type="delay", value=delay_ms)
                self._actions.append(delay_action)

        self._actions.append(action)
        self._last_action_time = current_time

    def record_keypress(
        self, key: str, modifiers: list[str] | None = None
    ) -> None:
        """Record a key press.

        Args:
            key: The key pressed
            modifiers: Any modifier keys held
        """
        action = MacroAction(
            action_type="keypress", value=key, modifiers=modifiers or []
        )
        self.record_action(action)

    def record_mouse_click(self, button: int, x: int = 0, y: int = 0) -> None:
        """Record a mouse click.

        Args:
            button: Mouse button (1=left, 2=middle, 3=right)
            x: X coordinate (0 for current position)
            y: Y coordinate (0 for current position)
        """
        action = MacroAction(
            action_type="mouse_click", value={"button": button, "x": x, "y": y}
        )
        self.record_action(action)


class MacroManager:
    """Manages macros for devices."""

    def __init__(self):
        """Initialize macro manager."""
        self._macros: dict[str, list[Macro]] = {}  # device_id -> macros
        self._player = MacroPlayer()
        self._recorder = MacroRecorder()

    def get_macros(self, device_id: str) -> list[Macro]:
        """Get macros for a device."""
        return self._macros.get(device_id, [])

    def add_macro(self, device_id: str, macro: Macro) -> None:
        """Add a macro for a device."""
        if device_id not in self._macros:
            self._macros[device_id] = []
        self._macros[device_id].append(macro)

    def remove_macro(self, device_id: str, macro_name: str) -> bool:
        """Remove a macro by name."""
        if device_id in self._macros:
            for i, macro in enumerate(self._macros[device_id]):
                if macro.name == macro_name:
                    del self._macros[device_id][i]
                    return True
        return False

    def get_macro(self, device_id: str, macro_name: str) -> Macro | None:
        """Get a macro by name."""
        for macro in self.get_macros(device_id):
            if macro.name == macro_name:
                return macro
        return None

    def play_macro(self, device_id: str, macro_name: str) -> str | None:
        """Play a macro by name."""
        macro = self.get_macro(device_id, macro_name)
        if macro:
            return self._player.play_macro(macro)
        return None

    def stop_macro(self, playback_id: str) -> bool:
        """Stop a macro playback."""
        return self._player.stop_macro(playback_id)

    def start_recording(self, device_id: str) -> None:  # noqa: ARG002
        """Start recording a macro."""
        self._recorder.start_recording()

    def stop_recording(self, device_id: str, name: str) -> Macro:
        """Stop recording and save macro."""
        macro = self._recorder.stop_recording(name)
        self.add_macro(device_id, macro)
        return macro

    def is_recording(self) -> bool:
        """Check if recording."""
        return self._recorder.is_recording()
