"""Expose Screwdriver's passive system collectors."""

from screwdriver.collectors.host import (
    collect_host,
    collect_network_info,
    collect_network_interfaces,
)

__all__ = [
    "collect_host",
    "collect_network_info",
    "collect_network_interfaces",
]
