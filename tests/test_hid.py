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


class TestPhysicalDeviceGrouping:
    """Which hidraw nodes belong to the same piece of hardware.

    This is the basis for probing safely in parallel: nodes of one device must
    be probed one after another, because concurrent HID++ conversations on them
    steal each other's replies.  Measured on this host: probing all nine nodes
    at once made the device list swing between 0 and 3 entries, while grouping
    by USB device kept it at a stable count in every run — so a wrong grouping
    is not a slow scan, it is a wrong one.
    """

    @staticmethod
    def _node(usb_path: str):
        from ghub4linux.core.hidpp import HidrawDevice

        return HidrawDevice(
            node="/dev/hidrawX",
            name="Logitech USB Receiver",
            vendor_id=0x046D,
            product_id=0xC53A,
            hid_id="0003:0000046D:0000C53A",
            usb_path=usb_path,
            interface="0003:046D:C53A.0008",
            serial="",
        )

    def test_the_interfaces_of_one_receiver_share_a_group(self):
        """A receiver exposes one node per interface, all one device."""
        from ghub4linux.core.hid import _physical_device

        assert _physical_device(self._node("1-10.4:1.0")) == "1-10.4"
        assert _physical_device(self._node("1-10.4:1.1")) == "1-10.4"
        assert _physical_device(self._node("1-10.4:1.2")) == "1-10.4"

    def test_different_receivers_are_different_groups(self):
        """Otherwise two receivers would be probed at once, which is fine."""
        from ghub4linux.core.hid import _physical_device

        assert _physical_device(self._node("1-10.4:1.0")) != _physical_device(
            self._node("1-10.2.2:1.0")
        )

    def test_a_devices_own_node_groups_with_itself(self):
        """A direct node carries no interface suffix and is already per-device."""
        from ghub4linux.core.hid import _physical_device

        assert _physical_device(self._node("0003:046D:C53A.0008")) == "0003:046D:C53A.0008"

    def test_a_deeper_interface_suffix_is_still_stripped(self):
        """The suffix is ':config.interface', not the first colon."""
        from ghub4linux.core.hid import _physical_device

        assert _physical_device(self._node("3-1.4.2:1.1")) == "3-1.4.2"


class TestParallelProbingStaysWithinADevice:
    """The scan probes several devices at once, but never one device twice."""

    def test_each_physical_device_is_probed_by_exactly_one_task(self):
        """Two tasks on one device is what loses replies."""
        from ghub4linux.core.hid import _physical_device
        from ghub4linux.core.hidpp import HidrawDevice

        nodes = [
            HidrawDevice(
                node=f"/dev/hidraw{i}",
                name="n",
                vendor_id=0x046D,
                product_id=0xC53A,
                hid_id="x",
                usb_path=path,
                interface="x",
                serial="",
            )
            for i, path in enumerate(["1-10.4:1.0", "1-10.4:1.1", "1-10.4:1.2", "1-10.2.2:1.0"])
        ]

        groups: dict[str, list[HidrawDevice]] = {}
        for node in nodes:
            groups.setdefault(_physical_device(node), []).append(node)

        assert len(groups) == 2
        assert sorted(len(members) for members in groups.values()) == [1, 3]
        # Every node is covered, and none appears twice.
        probed = [node.node for members in groups.values() for node in members]
        assert sorted(probed) == sorted(n.node for n in nodes)

    def test_a_group_is_probed_in_order(self):
        """The task walks its nodes sequentially, not concurrently."""
        import inspect

        from ghub4linux.core.hid import HIDManager

        source = inspect.getsource(HIDManager._probe_group)
        assert "for node in members" in source
        assert "ThreadPool" not in source
