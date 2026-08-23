"""Test passive sysfs hardware-bus inventory."""

from pathlib import Path

from screwdriver.collectors.bus import collect_hardware_bus_inventory


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def test_collects_registered_pci_i2c_spi_and_gpio_without_probing(tmp_path: Path) -> None:
    pci_root = tmp_path / "sys/bus/pci/devices"
    i2c_root = tmp_path / "sys/bus/i2c/devices"
    spi_root = tmp_path / "sys/bus/spi/devices"
    gpio_root = tmp_path / "sys/class/gpio"
    dev_root = tmp_path / "dev"

    pci = pci_root / "0000:01:00.0"
    _write(pci / "vendor", "0x10de\n")
    _write(pci / "device", "0x28e0\n")
    _write(pci / "class", "0x030000\n")

    i2c_adapter = i2c_root / "i2c-1"
    _write(i2c_adapter / "name", "Tegra I2C adapter\n")
    i2c_sensor = i2c_root / "1-0068"
    _write(i2c_sensor / "name", "imu-sensor\n")

    spi = spi_root / "spi0.0"
    _write(spi / "modalias", "spi:spidev\n")
    dev_root.mkdir(parents=True)
    (dev_root / "spidev0.0").touch()

    gpio = gpio_root / "gpiochip0"
    _write(gpio / "label", "tegra234-gpio\n")
    _write(gpio / "ngpio", "164\n")
    (dev_root / "gpiochip0").touch()

    items = collect_hardware_bus_inventory(
        pci_root=pci_root,
        i2c_root=i2c_root,
        spi_root=spi_root,
        gpio_root=gpio_root,
        dev_root=dev_root,
    )

    buses = {str(item.details.get("bus")) for item in items}
    assert {"PCI / PCIe", "I²C", "SPI", "GPIO"} <= buses

    pci_item = next(item for item in items if item.details.get("bus") == "PCI / PCIe")
    assert pci_item.details["kind"] == "Display"
    assert pci_item.details["vendor_id"] == "0x10de"

    imu = next(item for item in items if item.name == "imu-sensor")
    assert imu.details["kind"] == "IMU"

    spi_item = next(item for item in items if item.details.get("bus") == "SPI")
    assert spi_item.details["channel"] == str(dev_root / "spidev0.0")

    gpio_item = next(item for item in items if item.details.get("bus") == "GPIO")
    assert gpio_item.details["lines"] == "164"
