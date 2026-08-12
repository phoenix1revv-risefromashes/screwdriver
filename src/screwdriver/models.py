"""Define structured, JSON-compatible inspection data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from screwdriver.report_time import REPORT_TIMEZONE_NAME, report_isoformat


class ComponentStatus(str, Enum):
    """Represent the operational state of an inspected component."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    UNKNOWN = "unknown"


class FindingSeverity(str, Enum):
    """Represent the importance of a diagnostic finding."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True)
class Component:
    """Represent an additional hardware or software component."""

    category: str
    name: str
    status: ComponentStatus = ComponentStatus.UNKNOWN
    details: dict[str, str | int | float | bool | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "name": self.name,
            "status": self.status.value,
            "details": self.details.copy(),
        }


@dataclass(slots=True)
class Finding:
    """Represent one evidence-based diagnostic observation."""

    code: str
    severity: FindingSeverity
    summary: str
    evidence: str | None = None
    recommendation: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "summary": self.summary,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }


@dataclass(slots=True)
class HostIdentity:
    """Identify the computer and the account running Screwdriver."""

    hostname: str
    username: str
    effective_username: str
    uid: int
    gid: int
    groups: list[str] = field(default_factory=list)
    login_shell: str | None = None
    machine_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "hostname": self.hostname,
            "username": self.username,
            "effective_username": self.effective_username,
            "uid": self.uid,
            "gid": self.gid,
            "groups": self.groups.copy(),
            "login_shell": self.login_shell,
            "machine_id": self.machine_id,
        }


@dataclass(slots=True)
class OperatingSystemInfo:
    """Describe the installed OS and current runtime state."""

    distribution: str
    kernel: str
    kernel_build: str
    architecture: str
    boot_mode: str
    init_system: str | None
    package_manager: str | None
    timezone: str
    boot_time: datetime
    uptime_seconds: float
    process_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "distribution": self.distribution,
            "kernel": self.kernel,
            "kernel_build": self.kernel_build,
            "architecture": self.architecture,
            "boot_mode": self.boot_mode,
            "init_system": self.init_system,
            "package_manager": self.package_manager,
            "timezone": self.timezone,
            "boot_time": report_isoformat(self.boot_time),
            "uptime_seconds": self.uptime_seconds,
            "process_count": self.process_count,
        }


@dataclass(slots=True)
class PlatformInfo:
    """Describe the physical board or virtual platform."""

    manufacturer: str | None = None
    product_name: str | None = None
    board_name: str | None = None
    board_version: str | None = None
    firmware_version: str | None = None
    serial_number: str | None = None
    machine_type: str = "physical computer"
    virtualization: str | None = None
    family: str = "generic-linux"
    enrichment_module: str | None = None
    details: dict[str, str | int | float | bool | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "manufacturer": self.manufacturer,
            "product_name": self.product_name,
            "board_name": self.board_name,
            "board_version": self.board_version,
            "firmware_version": self.firmware_version,
            "serial_number": self.serial_number,
            "machine_type": self.machine_type,
            "virtualization": self.virtualization,
            "family": self.family,
            "enrichment_module": self.enrichment_module,
            "details": self.details.copy(),
        }


@dataclass(slots=True)
class CPUInfo:
    """Describe processors and their current operating state."""

    model: str
    vendor: str | None
    sockets: int | None
    physical_cores: int | None
    logical_cpus: int
    online_cpus: int
    current_frequency_mhz: float | None
    minimum_frequency_mhz: float | None
    maximum_frequency_mhz: float | None
    usage_percent: float
    load_average: tuple[float, float, float] | None
    governor: str | None
    caches: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "vendor": self.vendor,
            "sockets": self.sockets,
            "physical_cores": self.physical_cores,
            "logical_cpus": self.logical_cpus,
            "online_cpus": self.online_cpus,
            "current_frequency_mhz": self.current_frequency_mhz,
            "minimum_frequency_mhz": self.minimum_frequency_mhz,
            "maximum_frequency_mhz": self.maximum_frequency_mhz,
            "usage_percent": self.usage_percent,
            "load_average": list(self.load_average) if self.load_average else None,
            "governor": self.governor,
            "caches": self.caches.copy(),
        }


@dataclass(slots=True)
class MemoryInfo:
    """Describe physical memory, shared memory, and swap."""

    total_bytes: int
    used_bytes: int
    available_bytes: int
    usage_percent: float
    shared_bytes: int
    swap_total_bytes: int
    swap_used_bytes: int
    swap_free_bytes: int
    swap_usage_percent: float

    def to_dict(self) -> dict[str, object]:
        return {
            "total_bytes": self.total_bytes,
            "used_bytes": self.used_bytes,
            "available_bytes": self.available_bytes,
            "usage_percent": self.usage_percent,
            "shared_bytes": self.shared_bytes,
            "swap_total_bytes": self.swap_total_bytes,
            "swap_used_bytes": self.swap_used_bytes,
            "swap_free_bytes": self.swap_free_bytes,
            "swap_usage_percent": self.swap_usage_percent,
        }


@dataclass(slots=True)
class StoragePartition:
    """Describe a filesystem hosted by a storage device."""

    path: str
    filesystem: str | None
    mount_point: str | None
    total_bytes: int | None
    used_bytes: int | None
    available_bytes: int | None
    usage_percent: float | None
    read_only: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "filesystem": self.filesystem,
            "mount_point": self.mount_point,
            "total_bytes": self.total_bytes,
            "used_bytes": self.used_bytes,
            "available_bytes": self.available_bytes,
            "usage_percent": self.usage_percent,
            "read_only": self.read_only,
        }


@dataclass(slots=True)
class StorageDevice:
    """Describe one physical or virtual block storage device."""

    name: str
    path: str
    model: str | None
    serial_number: str | None
    connection: str | None
    media_type: str
    capacity_bytes: int
    firmware_version: str | None
    removable: bool
    read_only: bool
    partitions: list[StoragePartition] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": self.path,
            "model": self.model,
            "serial_number": self.serial_number,
            "connection": self.connection,
            "media_type": self.media_type,
            "capacity_bytes": self.capacity_bytes,
            "firmware_version": self.firmware_version,
            "removable": self.removable,
            "read_only": self.read_only,
            "partitions": [partition.to_dict() for partition in self.partitions],
        }


@dataclass(slots=True)
class GPUInfo:
    """Describe one graphics or compute accelerator."""

    vendor: str
    model: str
    driver: str | None = None
    bus_id: str | None = None
    memory_bytes: int | None = None
    usage_percent: float | None = None
    temperature_celsius: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "vendor": self.vendor,
            "model": self.model,
            "driver": self.driver,
            "bus_id": self.bus_id,
            "memory_bytes": self.memory_bytes,
            "usage_percent": self.usage_percent,
            "temperature_celsius": self.temperature_celsius,
        }


@dataclass(slots=True)
class ThermalSensor:
    """Represent a readable thermal sensor."""

    name: str
    temperature_celsius: float
    high_celsius: float | None = None
    critical_celsius: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "temperature_celsius": self.temperature_celsius,
            "high_celsius": self.high_celsius,
            "critical_celsius": self.critical_celsius,
        }


@dataclass(slots=True)
class PowerInfo:
    """Describe the detected power source and battery state."""

    source: str
    battery_present: bool
    battery_percent: float | None = None
    charging: bool | None = None
    seconds_remaining: int | None = None
    details: dict[str, str | int | float | bool | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "battery_present": self.battery_present,
            "battery_percent": self.battery_percent,
            "charging": self.charging,
            "seconds_remaining": self.seconds_remaining,
            "details": self.details.copy(),
        }


@dataclass(slots=True)
class NetworkInterface:
    """Describe one interface without retaining IPv6 addresses."""

    name: str
    interface_type: str = "unknown"
    ipv4_addresses: list[str] = field(default_factory=list)
    mac_address: str | None = None
    state: str = "unknown"
    mtu: int | None = None
    speed_mbps: int | None = None
    duplex: str | None = None
    driver: str | None = None
    is_loopback: bool = False
    is_virtual: bool = False
    is_default_route: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "interface_type": self.interface_type,
            "ipv4_addresses": self.ipv4_addresses.copy(),
            "mac_address": self.mac_address,
            "state": self.state,
            "mtu": self.mtu,
            "speed_mbps": self.speed_mbps,
            "duplex": self.duplex,
            "driver": self.driver,
            "is_loopback": self.is_loopback,
            "is_virtual": self.is_virtual,
            "is_default_route": self.is_default_route,
        }


@dataclass(slots=True)
class NetworkInfo:
    """Describe local interfaces and system routing configuration."""

    interfaces: list[NetworkInterface] = field(default_factory=list)
    default_interface: str | None = None
    default_gateway: str | None = None
    dns_servers: list[str] = field(default_factory=list)
    internet_route_available: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "interfaces": [interface.to_dict() for interface in self.interfaces],
            "default_interface": self.default_interface,
            "default_gateway": self.default_gateway,
            "dns_servers": self.dns_servers.copy(),
            "internet_route_available": self.internet_route_available,
        }


@dataclass(slots=True)
class DeviceNode:
    """Describe a Linux device node associated with hardware."""

    path: str
    node_type: str
    permissions: str
    owner: str | None
    group: str | None
    readable: bool
    writable: bool

    @property
    def access(self) -> str:
        if self.readable and self.writable:
            return "read-write"
        if self.readable:
            return "read-only"
        if self.writable:
            return "write-only"
        return "denied"

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "node_type": self.node_type,
            "permissions": self.permissions,
            "owner": self.owner,
            "group": self.group,
            "readable": self.readable,
            "writable": self.writable,
            "access": self.access,
        }


@dataclass(slots=True)
class USBDevice:
    """Describe one physical USB device."""

    sysfs_name: str
    vendor_id: str
    product_id: str
    manufacturer: str | None = None
    product_name: str | None = None
    serial_number: str | None = None
    bus_number: int | None = None
    device_number: int | None = None
    usb_version: str | None = None
    speed_mbps: float | None = None
    device_class: str | None = None
    device_class_name: str | None = None
    drivers: list[str] = field(default_factory=list)
    device_nodes: list[DeviceNode] = field(default_factory=list)

    @property
    def usb_id(self) -> str:
        return f"{self.vendor_id}:{self.product_id}"

    @property
    def display_name(self) -> str:
        parts = [
            self.manufacturer,
            self.product_name,
        ]
        name = " ".join(part for part in parts if part)
        return name or f"USB device {self.usb_id}"

    def to_dict(self) -> dict[str, object]:
        return {
            "sysfs_name": self.sysfs_name,
            "usb_id": self.usb_id,
            "vendor_id": self.vendor_id,
            "product_id": self.product_id,
            "manufacturer": self.manufacturer,
            "product_name": self.product_name,
            "display_name": self.display_name,
            "serial_number": self.serial_number,
            "bus_number": self.bus_number,
            "device_number": self.device_number,
            "usb_version": self.usb_version,
            "speed_mbps": self.speed_mbps,
            "device_class": self.device_class,
            "device_class_name": self.device_class_name,
            "drivers": self.drivers.copy(),
            "device_nodes": [node.to_dict() for node in self.device_nodes],
        }


@dataclass(slots=True)
class SerialDevice:
    """Describe one hardware-backed Linux serial/TTY port."""

    port: str
    sysfs_name: str
    transport: str
    driver: str | None = None
    stable_id_path: str | None = None
    physical_path: str | None = None
    usb_vendor_id: str | None = None
    usb_product_id: str | None = None
    manufacturer: str | None = None
    product_name: str | None = None
    serial_number: str | None = None
    device_node: DeviceNode | None = None

    @property
    def usb_id(self) -> str | None:
        if self.usb_vendor_id is None or self.usb_product_id is None:
            return None

        return f"{self.usb_vendor_id}:{self.usb_product_id}"

    @property
    def display_name(self) -> str:
        name = " ".join(part for part in (self.manufacturer, self.product_name) if part)
        return name or self.sysfs_name

    @property
    def stable_path_available(self) -> bool:
        return self.stable_id_path is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "port": self.port,
            "sysfs_name": self.sysfs_name,
            "transport": self.transport,
            "driver": self.driver,
            "stable_id_path": self.stable_id_path,
            "physical_path": self.physical_path,
            "stable_path_available": self.stable_path_available,
            "usb_id": self.usb_id,
            "usb_vendor_id": self.usb_vendor_id,
            "usb_product_id": self.usb_product_id,
            "manufacturer": self.manufacturer,
            "product_name": self.product_name,
            "display_name": self.display_name,
            "serial_number": self.serial_number,
            "device_node": self.device_node.to_dict() if self.device_node else None,
        }


@dataclass(slots=True)
class SystemSnapshot:
    """Represent a complete passive inspection of one Linux computer."""

    identity: HostIdentity
    operating_system: OperatingSystemInfo
    platform: PlatformInfo
    cpu: CPUInfo
    memory: MemoryInfo
    storage_devices: list[StorageDevice]
    gpus: list[GPUInfo]
    thermal_sensors: list[ThermalSensor]
    power: PowerInfo
    network: NetworkInfo
    usb_devices: list[USBDevice] = field(default_factory=list)
    serial_devices: list[SerialDevice] = field(default_factory=list)
    software_stack_inventory: list[Component] = field(default_factory=list)
    sensor_inventory: list[Component] = field(default_factory=list)
    actuator_inventory: list[Component] = field(default_factory=list)
    ros_device_inventory: list[Component] = field(default_factory=list)
    ros_runtime_inventory: list[Component] = field(default_factory=list)
    schema_version: str = "3.2"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    components: list[Component] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "created_at": report_isoformat(self.created_at),
            "report_timezone": REPORT_TIMEZONE_NAME,
            "identity": self.identity.to_dict(),
            "operating_system": self.operating_system.to_dict(),
            "platform": self.platform.to_dict(),
            "cpu": self.cpu.to_dict(),
            "memory": self.memory.to_dict(),
            "storage_devices": [device.to_dict() for device in self.storage_devices],
            "gpus": [gpu.to_dict() for gpu in self.gpus],
            "thermal_sensors": [sensor.to_dict() for sensor in self.thermal_sensors],
            "power": self.power.to_dict(),
            "network": self.network.to_dict(),
            "usb_devices": [device.to_dict() for device in self.usb_devices],
            "serial_devices": [device.to_dict() for device in self.serial_devices],
            "software_stack_inventory": [
                component.to_dict() for component in self.software_stack_inventory
            ],
            "sensor_inventory": [component.to_dict() for component in self.sensor_inventory],
            "actuator_inventory": [component.to_dict() for component in self.actuator_inventory],
            "ros_device_inventory": [
                component.to_dict() for component in self.ros_device_inventory
            ],
            "ros_runtime_inventory": [
                component.to_dict() for component in self.ros_runtime_inventory
            ],
            "components": [component.to_dict() for component in self.components],
            "findings": [finding.to_dict() for finding in self.findings],
        }
