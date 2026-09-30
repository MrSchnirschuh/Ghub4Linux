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
        from ghub4linux.core.hid import _deduplicate, _resolve_product_ids

        # hidraw15 answered on a later scan; the receiver path gave the name.
        devices = [
            self._device(
                0x407F, "Logitech G502", node="/dev/hidraw15", index=0xFF, identified=False
            ),
            self._device(
                0xC53A,
                "G502 LIGHTSPEED Wireless Gaming Mouse",
                node="/dev/hidraw7",
                index=0x01,
                identified=True,
            ),
            self._device(
                0x407F,
                "G502 LIGHTSPEED Wireless Gaming Mouse",
                node="/dev/hidraw15",
                index=0xFF,
                identified=True,
            ),
        ]
        # enumerate_devices runs both steps in this order.
        resolved = _deduplicate(_resolve_product_ids(devices))
        assert len(resolved) == 1
        assert resolved[0].product_id == 0x407F
        assert resolved[0].product == "G502 LIGHTSPEED Wireless Gaming Mouse"

    def test_anonymous_node_survives_without_a_named_twin(self):
        from ghub4linux.core.hid import _resolve_product_ids

        devices = [
            self._device(
                0x405F, "Logitech Candy", node="/dev/hidraw16", index=0xFF, identified=False
            )
        ]
        assert len(_resolve_product_ids(devices)) == 1
