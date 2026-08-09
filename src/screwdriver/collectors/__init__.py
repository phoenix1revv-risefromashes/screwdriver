"""Expose passive Screwdriver collectors."""

from screwdriver.collectors.host import (
    collect_host,
    collect_network_interfaces,
)
from screwdriver.collectors.serial import collect_serial_devices
from screwdriver.collectors.usb import collect_usb_devices

__all__ = [
    "collect_host",
    "collect_network_interfaces",
    "collect_serial_devices",
    "collect_usb_devices",
]
