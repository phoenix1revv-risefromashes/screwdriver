"""Test passive DRM display-unit discovery."""

from pathlib import Path

from screwdriver.collectors.display import collect_display_units


def _edid_with_name(name: str) -> bytes:
    data = bytearray(128)
    data[:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    # ECR encoded as EISA manufacturer ID.
    manufacturer = ((ord("E") - 64) << 10) | ((ord("C") - 64) << 5) | (ord("R") - 64)
    data[8:10] = manufacturer.to_bytes(2, "big")
    data[10:12] = (0x0500).to_bytes(2, "little")
    data[12:16] = (12345).to_bytes(4, "little")
    descriptor = bytearray(18)
    descriptor[:5] = b"\x00\x00\x00\xfc\x00"
    encoded = name.encode("ascii")[:13]
    descriptor[5 : 5 + len(encoded)] = encoded
    data[54:72] = descriptor
    return bytes(data)


def test_collect_connected_display_unit_from_drm_and_edid(tmp_path: Path) -> None:
    drm_root = tmp_path / "sys/class/drm"
    connector = drm_root / "card0-HDMI-A-1"
    connector.mkdir(parents=True)
    (connector / "status").write_text("connected\n", encoding="utf-8")
    (connector / "enabled").write_text("enabled\n", encoding="utf-8")
    (connector / "modes").write_text("1024x600\n800x600\n", encoding="utf-8")
    (connector / "edid").write_bytes(_edid_with_name("ELECROW 5IN"))

    displays = collect_display_units(drm_root)

    assert len(displays) == 1
    display = displays[0]
    assert display.name == "ELECROW 5IN"
    assert display.details["kind"] == "Display"
    assert display.details["connector"] == "HDMI-A-1"
    assert display.details["resolution"] == "1024x600"
    assert display.details["state"] == "CONNECTED"
    assert display.details["manufacturer"] == "ECR"


def test_disconnected_drm_connector_is_not_reported_as_display_unit(tmp_path: Path) -> None:
    connector = tmp_path / "card0-DP-1"
    connector.mkdir(parents=True)
    (connector / "status").write_text("disconnected\n", encoding="utf-8")

    assert collect_display_units(tmp_path) == []
