"""Tests for GLinux macro system."""

import time
from unittest.mock import MagicMock

import pytest

from glinux.core.config import Macro, MacroAction
from glinux.features.macros import MacroManager, MacroPlayer, MacroRecorder


class TestMacroPlayer:
    """Tests for MacroPlayer class."""

    def test_play_macro_blocking(self):
        """Test blocking macro playback."""
        actions_executed = []

        def track_action(action: MacroAction):
            actions_executed.append(action)

        player = MacroPlayer(input_sender=track_action)

        actions = [
            MacroAction(action_type="keypress", value="a"),
            MacroAction(action_type="keypress", value="b"),
        ]
        macro = Macro(name="Test", actions=actions)

        result = player.play_macro(macro, blocking=True)

        assert result is None  # Blocking returns None
        assert len(actions_executed) == 2
        assert actions_executed[0].value == "a"
        assert actions_executed[1].value == "b"

    def test_play_macro_with_delay(self):
        """Test macro with delay action."""
        actions_executed = []

        def track_action(action: MacroAction):
            actions_executed.append((action, time.time()))

        player = MacroPlayer(input_sender=track_action)

        actions = [
            MacroAction(action_type="keypress", value="a"),
            MacroAction(action_type="delay", value=100),  # 100ms delay
            MacroAction(action_type="keypress", value="b"),
        ]
        macro = Macro(name="Test", actions=actions)

        start_time = time.time()
        player.play_macro(macro, blocking=True)
        elapsed = time.time() - start_time

        assert elapsed >= 0.1  # At least 100ms elapsed
        assert len(actions_executed) == 2  # Delays aren't sent to input_sender

    def test_play_macro_repeat(self):
        """Test macro repeat."""
        actions_executed = []

        def track_action(action: MacroAction):
            actions_executed.append(action)

        player = MacroPlayer(input_sender=track_action)

        actions = [MacroAction(action_type="keypress", value="x")]
        macro = Macro(name="Test", actions=actions, repeat_count=3)

        player.play_macro(macro, blocking=True)

        assert len(actions_executed) == 3

    def test_play_macro_async(self):
        """Test async macro playback."""
        player = MacroPlayer()

        actions = [
            MacroAction(action_type="delay", value=50),
            MacroAction(action_type="keypress", value="a"),
        ]
        macro = Macro(name="Test", actions=actions)

        playback_id = player.play_macro(macro, blocking=False)

        assert playback_id is not None
        assert player.is_playing(playback_id)

        # Wait for completion
        time.sleep(0.1)
        assert not player.is_playing(playback_id)

    def test_stop_macro(self):
        """Test stopping a macro."""
        player = MacroPlayer()

        actions = [
            MacroAction(action_type="delay", value=1000),  # Long delay
            MacroAction(action_type="keypress", value="a"),
        ]
        macro = Macro(name="Test", actions=actions, repeat_count=10)

        playback_id = player.play_macro(macro, blocking=False)
        assert playback_id is not None

        # Stop immediately
        result = player.stop_macro(playback_id)
        assert result is True

        time.sleep(0.05)
        assert not player.is_playing(playback_id)


class TestMacroRecorder:
    """Tests for MacroRecorder class."""

    def test_start_stop_recording(self):
        """Test starting and stopping recording."""
        recorder = MacroRecorder()

        assert not recorder.is_recording()

        recorder.start_recording()
        assert recorder.is_recording()

        macro = recorder.stop_recording("Test Macro")
        assert not recorder.is_recording()
        assert macro.name == "Test Macro"
        assert len(macro.actions) == 0

    def test_record_keypress(self):
        """Test recording keypresses."""
        recorder = MacroRecorder()
        recorder.start_recording(record_delays=False)

        recorder.record_keypress("a")
        recorder.record_keypress("b", modifiers=["ctrl"])

        macro = recorder.stop_recording("Test")

        assert len(macro.actions) == 2
        assert macro.actions[0].action_type == "keypress"
        assert macro.actions[0].value == "a"
        assert macro.actions[1].modifiers == ["ctrl"]

    def test_record_with_delays(self):
        """Test recording with delays."""
        recorder = MacroRecorder()
        recorder.start_recording(record_delays=True)

        recorder.record_keypress("a")
        time.sleep(0.05)  # 50ms delay
        recorder.record_keypress("b")

        macro = recorder.stop_recording("Test")

        # Should have delay action between keypresses
        assert len(macro.actions) >= 2
        # Check if there's a delay action
        has_delay = any(a.action_type == "delay" for a in macro.actions)
        assert has_delay

    def test_record_mouse_click(self):
        """Test recording mouse clicks."""
        recorder = MacroRecorder()
        recorder.start_recording(record_delays=False)

        recorder.record_mouse_click(button=1, x=100, y=200)

        macro = recorder.stop_recording("Test")

        assert len(macro.actions) == 1
        assert macro.actions[0].action_type == "mouse_click"
        assert macro.actions[0].value["button"] == 1
        assert macro.actions[0].value["x"] == 100

    def test_no_recording_when_stopped(self):
        """Test that actions aren't recorded when not recording."""
        recorder = MacroRecorder()

        recorder.record_keypress("a")
        recorder.record_keypress("b")

        recorder.start_recording()
        macro = recorder.stop_recording("Test")

        assert len(macro.actions) == 0


class TestMacroManager:
    """Tests for MacroManager class."""

    def test_add_get_macro(self):
        """Test adding and getting macros."""
        manager = MacroManager()
        device_id = "test:123"

        macro = Macro(name="Test Macro", actions=[])
        manager.add_macro(device_id, macro)

        result = manager.get_macro(device_id, "Test Macro")
        assert result is not None
        assert result.name == "Test Macro"

    def test_get_nonexistent_macro(self):
        """Test getting nonexistent macro."""
        manager = MacroManager()

        result = manager.get_macro("device", "nonexistent")
        assert result is None

    def test_remove_macro(self):
        """Test removing a macro."""
        manager = MacroManager()
        device_id = "test:123"

        macro = Macro(name="Test", actions=[])
        manager.add_macro(device_id, macro)

        result = manager.remove_macro(device_id, "Test")
        assert result is True

        result = manager.get_macro(device_id, "Test")
        assert result is None

    def test_get_macros(self):
        """Test getting all macros for a device."""
        manager = MacroManager()
        device_id = "test:123"

        manager.add_macro(device_id, Macro(name="Macro1", actions=[]))
        manager.add_macro(device_id, Macro(name="Macro2", actions=[]))

        macros = manager.get_macros(device_id)
        assert len(macros) == 2

    def test_recording_integration(self):
        """Test macro recording through manager."""
        manager = MacroManager()
        device_id = "test:123"

        manager.start_recording(device_id)
        assert manager.is_recording()

        macro = manager.stop_recording(device_id, "Recorded Macro")
        assert not manager.is_recording()
        assert macro.name == "Recorded Macro"

        # Verify macro was added
        result = manager.get_macro(device_id, "Recorded Macro")
        assert result is not None
