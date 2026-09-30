class TestAnonymousDirectNodeDropping:
    """A sleeping mouse must not appear twice."""

    def _device(self, pid, name, *, node, index, identified):
        from ghub4linux.core.hid import HIDDevice

        return HIDDevice(
            vendor_id=0x046D,
            product_id=pid,
            serial_number="ser" if identified else "",
            manufacturer="Logitech",
            product=name,
            path=node.encode(),
            interface_number=index,
            usage_page=0xFF00,
            usage=0x0001,
            node=node,
            device_index=index,
            identified=identified,
        )

    def test_silent_direct_node_is_dropped_when_a_named_one_exists(self):
        from ghub4linux.core.hid import _resolve_product_ids

        # The device just woke: its own node is present but silent, while the
        # receiver path answered and carries the real product ID (0x407f).
        devices = [
            self._device(
                0x407F, "Logitech G502", node="/dev/hidraw15", index=0xFF, identified=False
            ),
            self._device(
                0x407F,
                "G502 LIGHTSPEED Wireless Gaming Mouse",
                node="/dev/hidraw7",
                index=0x01,
                identified=True,
            ),
        ]
        resolved = _resolve_product_ids(devices)
        assert len(resolved) == 1
        assert resolved[0].identified is True
        assert resolved[0].product == "G502 LIGHTSPEED Wireless Gaming Mouse"

    def test_anonymous_node_survives_without_a_named_twin(self):
        from ghub4linux.core.hid import _resolve_product_ids

        devices = [
            self._device(
                0x405F, "Logitech Candy", node="/dev/hidraw16", index=0xFF, identified=False
            )
        ]
        assert len(_resolve_product_ids(devices)) == 1


class TestBothPathsAnswer:
    """An awake mouse is reachable twice; only the receiver path should stay."""

    def _device(self, pid, name, *, node, index, identified):
        from ghub4linux.core.hid import HIDDevice

        return HIDDevice(
            vendor_id=0x046D,
            product_id=pid,
            serial_number="",
            manufacturer="Logitech",
            product=name,
            path=node.encode(),
            interface_number=index,
            usage_page=0xFF00,
            usage=0x0001,
            node=node,
            device_index=index,
            identified=identified,
        )

    def test_the_receiver_path_wins_over_the_direct_node(self):
        from ghub4linux.core.hid import _deduplicate

        name = "G502 LIGHTSPEED Wireless Gaming Mouse"
        devices = [
            self._device(0x407F, name, node="/dev/hidraw15", index=0xFF, identified=True),
            self._device(0x407F, name, node="/dev/hidraw7", index=0x01, identified=True),
        ]
        resolved = _deduplicate(devices)
        assert len(resolved) == 1
        assert resolved[0].node == "/dev/hidraw7"
        assert resolved[0].is_receiver_endpoint is True
