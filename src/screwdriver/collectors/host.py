"""Collect universal Linux host information without changing device state."""

from __future__ import annotations

import getpass
import grp
import json
import os
import platform
import pwd
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import psutil

from screwdriver.collectors.serial import (
    collect_serial_devices,
)
from screwdriver.collectors.usb import (
    collect_usb_devices,
)
from screwdriver.models import (
    CPUInfo,
    Finding,
    FindingSeverity,
    GPUInfo,
    HostIdentity,
    MemoryInfo,
    NetworkInfo,
    NetworkInterface,
    OperatingSystemInfo,
    PlatformInfo,
    PowerInfo,
    StorageDevice,
    StoragePartition,
    SystemSnapshot,
    ThermalSensor,
)
from screwdriver.progress import ProgressCallback

_DMI_ROOT = Path("/sys/class/dmi/id")
_DEVICE_TREE_ROOT = Path("/proc/device-tree")


def collect_host(progress: ProgressCallback | None = None) -> SystemSnapshot:
    """Collect a complete, machine-neutral snapshot of the current host."""

    if progress:
        progress(1, "Inspecting host & operating system")
    identity = collect_identity()
    operating_system = collect_operating_system()

    if progress:
        progress(2, "Inspecting compute, memory & storage")
    cpu = collect_cpu()
    platform_info = collect_platform(cpu.vendor)
    memory = collect_memory()
    storage_devices = collect_storage_devices()
    gpus = collect_gpus(platform_info)

    if progress:
        progress(3, "Discovering hardware & device interfaces")
    usb_devices = collect_usb_devices()
    serial_devices = collect_serial_devices()

    if progress:
        progress(4, "Checking network, power & thermals")
    thermal_sensors = collect_thermal_sensors()
    power = collect_power(platform_info)
    network = collect_network()

    snapshot = SystemSnapshot(
        identity=identity,
        operating_system=operating_system,
        platform=platform_info,
        cpu=cpu,
        memory=memory,
        storage_devices=storage_devices,
        gpus=gpus,
        thermal_sensors=thermal_sensors,
        power=power,
        network=network,
        usb_devices=usb_devices,
        serial_devices=serial_devices,
    )

    snapshot.findings.extend(_create_findings(snapshot))
    return snapshot


def collect_identity() -> HostIdentity:
    """Collect hostname and invoking/effective account details."""

    uid = os.getuid()
    gid = os.getgid()
    effective_uid = os.geteuid()

    username = os.environ.get("SUDO_USER") or _username_for_uid(uid) or getpass.getuser()
    effective_username = _username_for_uid(effective_uid) or getpass.getuser()

    login_shell: str | None

    try:
        login_shell = pwd.getpwnam(username).pw_shell
    except KeyError:
        login_shell = os.environ.get("SHELL")

    groups = sorted(
        {
            group.gr_name
            for group_id in os.getgroups()
            if (group := _group_for_gid(group_id)) is not None
        }
    )

    primary_group = _group_for_gid(gid)

    if primary_group is not None:
        groups = sorted(
            {
                *groups,
                primary_group.gr_name,
            }
        )

    return HostIdentity(
        hostname=platform.node() or "unknown",
        username=username,
        effective_username=effective_username,
        uid=uid,
        gid=gid,
        groups=groups,
        login_shell=login_shell,
        machine_id=_read_text(Path("/etc/machine-id")),
    )


def collect_operating_system() -> OperatingSystemInfo:
    """Collect distribution, kernel, boot, and runtime information."""

    try:
        release = platform.freedesktop_os_release()
    except OSError:
        release = {}

    boot_timestamp = psutil.boot_time()
    timezone_name = datetime.now().astimezone().tzname() or "unknown"

    return OperatingSystemInfo(
        distribution=release.get(
            "PRETTY_NAME",
            platform.system(),
        ),
        kernel=platform.release(),
        kernel_build=platform.version(),
        architecture=platform.machine(),
        boot_mode=("UEFI" if Path("/sys/firmware/efi").exists() else "BIOS/legacy"),
        init_system=("systemd" if Path("/run/systemd/system").exists() else None),
        package_manager=_detect_package_manager(),
        timezone=timezone_name,
        boot_time=datetime.fromtimestamp(
            boot_timestamp,
            tz=UTC,
        ),
        uptime_seconds=max(
            0.0,
            time.time() - boot_timestamp,
        ),
        process_count=len(psutil.pids()),
    )


def collect_platform(
    cpu_vendor: str | None = None,
) -> PlatformInfo:
    """Detect the platform and add vendor details only after detection."""

    manufacturer = _first_text(
        _DMI_ROOT / "sys_vendor",
        _DEVICE_TREE_ROOT / "vendor",
    )
    product_name = _first_text(
        _DMI_ROOT / "product_name",
        _DEVICE_TREE_ROOT / "model",
    )
    board_name = _first_text(
        _DMI_ROOT / "board_name",
        _DEVICE_TREE_ROOT / "model",
    )
    compatible = _read_text(_DEVICE_TREE_ROOT / "compatible") or ""
    detection_text = " ".join(
        value
        for value in (
            manufacturer,
            product_name,
            board_name,
            compatible,
        )
        if value
    ).lower()

    family = "generic-linux"
    enrichment_module: str | None = None
    details: dict[
        str,
        str | int | float | bool | None,
    ] = {}

    if "nvidia" in detection_text and ("jetson" in detection_text or "tegra" in detection_text):
        family = "nvidia-jetson"
        enrichment_module = "jetson"
        details = _collect_jetson_details()
    elif "raspberry pi" in detection_text or "raspberrypi" in detection_text:
        family = "raspberry-pi"
        enrichment_module = "raspberry_pi"
        details = _collect_raspberry_pi_details()
    elif platform.machine().lower() in {
        "x86_64",
        "amd64",
        "i386",
        "i686",
    }:
        family = "x86"
        enrichment_module = "x86"

        if cpu_vendor:
            details["cpu_vendor"] = cpu_vendor

    virtualization = _run_command(["systemd-detect-virt"])

    if virtualization in {
        None,
        "none",
    }:
        virtualization = None

    return PlatformInfo(
        manufacturer=manufacturer,
        product_name=product_name,
        board_name=board_name,
        board_version=_read_text(_DMI_ROOT / "board_version"),
        firmware_version=_read_text(_DMI_ROOT / "bios_version"),
        serial_number=_first_text(
            _DMI_ROOT / "product_serial",
            _DEVICE_TREE_ROOT / "serial-number",
        ),
        machine_type=("virtual machine or container" if virtualization else "physical computer"),
        virtualization=virtualization,
        family=family,
        enrichment_module=enrichment_module,
        details=details,
    )


def collect_cpu() -> CPUInfo:
    """Collect processor topology, frequency, load, and cache information."""

    cpu_data = _read_cpuinfo()
    lscpu_data = _read_lscpu()
    frequency = psutil.cpu_freq()
    logical_cpus = psutil.cpu_count(logical=True) or os.cpu_count() or 1
    physical_cores = psutil.cpu_count(logical=False)

    return CPUInfo(
        model=(
            cpu_data.get("model name")
            or cpu_data.get("model")
            or cpu_data.get("hardware")
            or platform.processor()
            or platform.machine()
        ),
        vendor=(
            cpu_data.get("vendor_id")
            or cpu_data.get("cpu implementer")
            or lscpu_data.get("vendor id")
        ),
        sockets=_parse_int(lscpu_data.get("socket(s)")),
        physical_cores=physical_cores,
        logical_cpus=logical_cpus,
        online_cpus=_count_cpu_range(
            _read_text(Path("/sys/devices/system/cpu/online")),
            logical_cpus,
        ),
        current_frequency_mhz=(frequency.current if frequency else None),
        minimum_frequency_mhz=(frequency.min if frequency else None),
        maximum_frequency_mhz=(frequency.max if frequency else None),
        usage_percent=psutil.cpu_percent(interval=0.1),
        load_average=_load_average(),
        governor=_read_text(Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")),
        caches={
            label: value
            for label, key in (
                (
                    "L1 data",
                    "l1d cache",
                ),
                (
                    "L1 instruction",
                    "l1i cache",
                ),
                (
                    "L2",
                    "l2 cache",
                ),
                (
                    "L3",
                    "l3 cache",
                ),
            )
            if (value := lscpu_data.get(key)) is not None
        },
    )


def collect_memory() -> MemoryInfo:
    """Collect physical memory and swap usage."""

    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()

    return MemoryInfo(
        total_bytes=memory.total,
        used_bytes=memory.used,
        available_bytes=memory.available,
        usage_percent=memory.percent,
        shared_bytes=getattr(
            memory,
            "shared",
            0,
        ),
        swap_total_bytes=swap.total,
        swap_used_bytes=swap.used,
        swap_free_bytes=swap.free,
        swap_usage_percent=swap.percent,
    )


def collect_storage_devices() -> list[StorageDevice]:
    """Collect physical disks and the filesystems nested beneath them."""

    output = _run_command(
        [
            "lsblk",
            "--json",
            "--bytes",
            "--output",
            ("NAME,PATH,TYPE,MODEL,SERIAL,TRAN,SIZE,FSTYPE,MOUNTPOINTS,ROTA,RM,RO,REV"),
        ]
    )

    if output is None:
        return []

    try:
        raw = json.loads(output)
    except json.JSONDecodeError:
        return []

    if not isinstance(raw, dict) or not isinstance(
        raw.get("blockdevices"),
        list,
    ):
        return []

    devices: list[StorageDevice] = []

    for item in cast(
        list[object],
        raw["blockdevices"],
    ):
        if not isinstance(item, dict):
            continue

        record = cast(
            dict[str, object],
            item,
        )

        if _as_string(record.get("type")) != "disk":
            continue

        name = _as_string(record.get("name")) or "unknown"
        path = _as_string(record.get("path")) or f"/dev/{name}"
        rotational = _as_bool(record.get("rota"))
        connection = _as_string(record.get("tran"))

        devices.append(
            StorageDevice(
                name=name,
                path=path,
                model=_as_string(record.get("model")),
                serial_number=_as_string(record.get("serial")),
                connection=connection,
                media_type=_storage_media_type(
                    name,
                    connection,
                    rotational,
                ),
                capacity_bytes=(_as_int(record.get("size")) or 0),
                firmware_version=_as_string(record.get("rev")),
                removable=_as_bool(record.get("rm")),
                read_only=_as_bool(record.get("ro")),
                partitions=(_collect_partition_records(record)),
            )
        )

    return devices


def collect_gpus(
    platform_info: PlatformInfo,
) -> list[GPUInfo]:
    """Collect GPUs using vendor tools first, then generic PCI discovery."""

    nvidia_output = _run_command(
        [
            "nvidia-smi",
            (
                "--query-gpu=name,driver_version,"
                "pci.bus_id,memory.total,"
                "utilization.gpu,temperature.gpu"
            ),
            "--format=csv,noheader,nounits",
        ]
    )

    if nvidia_output:
        gpus: list[GPUInfo] = []

        for line in nvidia_output.splitlines():
            fields = [field.strip() for field in line.split(",")]

            if len(fields) != 6:
                continue

            gpus.append(
                GPUInfo(
                    vendor="NVIDIA",
                    model=fields[0],
                    driver=fields[1],
                    bus_id=fields[2],
                    memory_bytes=_mib_to_bytes(fields[3]),
                    usage_percent=_parse_float(fields[4]),
                    temperature_celsius=(_parse_float(fields[5])),
                )
            )

        if gpus:
            return gpus

    pci_output = _run_command(
        [
            "lspci",
            "-D",
            "-nnk",
        ]
    )
    gpus = _parse_lspci_gpus(pci_output or "")

    if not gpus and platform_info.family == "nvidia-jetson":
        gpus.append(
            GPUInfo(
                vendor="NVIDIA",
                model=(f"Integrated GPU ({platform_info.product_name or 'Jetson'})"),
                driver="nvgpu",
            )
        )

    return gpus


def collect_thermal_sensors() -> list[ThermalSensor]:
    """Collect readable temperature sensors without activating hardware."""

    try:
        groups = psutil.sensors_temperatures(fahrenheit=False)
    except (
        AttributeError,
        OSError,
    ):
        return []

    sensors: list[ThermalSensor] = []

    for group_name, entries in groups.items():
        for index, entry in enumerate(entries):
            label = entry.label or f"sensor {index}"

            sensors.append(
                ThermalSensor(
                    name=(f"{group_name}: {label}"),
                    temperature_celsius=(entry.current),
                    high_celsius=entry.high,
                    critical_celsius=(entry.critical),
                )
            )

    return sensors


def collect_power(
    platform_info: PlatformInfo,
) -> PowerInfo:
    """Collect battery or external-power information when Linux exposes it."""

    try:
        battery = psutil.sensors_battery()
    except (
        OSError,
        FileNotFoundError,
    ):
        battery = None

    if battery is None:
        details: dict[
            str,
            str | int | float | bool | None,
        ] = {}

        if platform_info.family == "raspberry-pi":
            throttled = platform_info.details.get("throttled_state")

            if throttled is not None:
                details["throttled_state"] = throttled

        return PowerInfo(
            source="external or unknown",
            battery_present=False,
            details=details,
        )

    seconds_remaining: int | None = battery.secsleft

    if seconds_remaining in {
        psutil.POWER_TIME_UNKNOWN,
        psutil.POWER_TIME_UNLIMITED,
    }:
        seconds_remaining = None

    return PowerInfo(
        source=("AC power" if battery.power_plugged else "battery"),
        battery_present=True,
        battery_percent=battery.percent,
        charging=battery.power_plugged,
        seconds_remaining=seconds_remaining,
    )


def collect_network() -> NetworkInfo:
    """Collect IPv4 interfaces, route, gateway, DNS, driver, and link data."""

    (
        default_interface,
        default_gateway,
    ) = _collect_default_route()

    interfaces = collect_network_interfaces(default_interface)

    return NetworkInfo(
        interfaces=interfaces,
        default_interface=default_interface,
        default_gateway=default_gateway,
        dns_servers=_collect_dns_servers(),
        internet_route_available=(default_interface is not None),
    )


def collect_network_interfaces(
    default_interface: str | None = None,
) -> list[NetworkInterface]:
    """Collect network interfaces; IPv6 is intentionally excluded."""

    output = _run_command(
        [
            "ip",
            "-j",
            "address",
            "show",
        ]
    )

    if output is None:
        return []

    try:
        raw = json.loads(output)
    except json.JSONDecodeError:
        return []

    if not isinstance(raw, list):
        return []

    interfaces: list[NetworkInterface] = []

    for item in cast(
        list[object],
        raw,
    ):
        if not isinstance(item, dict):
            continue

        record = cast(
            dict[str, object],
            item,
        )
        name = _as_string(record.get("ifname"))

        if not name:
            continue

        flags = _as_string_list(record.get("flags"))
        kind = _network_kind(record)
        is_loopback = kind == "loopback" or "LOOPBACK" in flags
        is_virtual = not Path(f"/sys/class/net/{name}/device").exists()

        if kind in {
            "ethernet",
            "wifi",
        }:
            is_virtual = False

        addresses: list[str] = []

        for address in _as_records(record.get("addr_info")):
            if _as_string(address.get("family")) != "inet":
                continue

            local = _as_string(address.get("local"))
            prefix = _as_int(address.get("prefixlen"))

            if local:
                addresses.append(f"{local}/{prefix}" if prefix is not None else local)

        operating_state = _as_string(record.get("operstate"))
        state = "up" if "UP" in flags else (operating_state or "unknown").lower()

        interfaces.append(
            NetworkInterface(
                name=name,
                interface_type=kind,
                ipv4_addresses=addresses,
                mac_address=_as_string(record.get("address")),
                state=state,
                mtu=_as_int(record.get("mtu")),
                speed_mbps=_read_positive_int(Path(f"/sys/class/net/{name}/speed")),
                duplex=_read_text(Path(f"/sys/class/net/{name}/duplex")),
                driver=_driver_name(Path(f"/sys/class/net/{name}/device/driver")),
                is_loopback=is_loopback,
                is_virtual=is_virtual,
                is_default_route=(name == default_interface),
            )
        )

    return interfaces


def _create_findings(
    snapshot: SystemSnapshot,
) -> list[Finding]:
    findings: list[Finding] = []

    if snapshot.cpu.usage_percent >= 90:
        findings.append(
            Finding(
                code="CPU_HIGH_USAGE",
                severity=FindingSeverity.WARNING,
                summary=("CPU usage is above 90%."),
                evidence=(f"Measured usage: {snapshot.cpu.usage_percent:.1f}%"),
            )
        )

    if snapshot.memory.usage_percent >= 90:
        findings.append(
            Finding(
                code="MEMORY_HIGH_USAGE",
                severity=FindingSeverity.WARNING,
                summary=("Physical memory usage is above 90%."),
                evidence=(f"Measured usage: {snapshot.memory.usage_percent:.1f}%"),
            )
        )

    for device in snapshot.storage_devices:
        for partition in device.partitions:
            if partition.usage_percent is not None and partition.usage_percent >= 90:
                findings.append(
                    Finding(
                        code="FILESYSTEM_LOW_SPACE",
                        severity=(FindingSeverity.WARNING),
                        summary=(
                            f"Filesystem {partition.mount_point or partition.path} is nearly full."
                        ),
                        evidence=(f"Measured usage: {partition.usage_percent:.1f}%"),
                        recommendation=("Free space before logs or application data exhaust it."),
                    )
                )

    for sensor in snapshot.thermal_sensors:
        limit = sensor.critical_celsius or 90.0

        if sensor.temperature_celsius >= limit:
            findings.append(
                Finding(
                    code="THERMAL_CRITICAL",
                    severity=FindingSeverity.ERROR,
                    summary=(f"{sensor.name} reached a critical temperature."),
                    evidence=(f"Measured temperature: {sensor.temperature_celsius:.1f}°C"),
                )
            )

    for serial_device in snapshot.serial_devices:
        node = serial_device.device_node

        if node is None:
            findings.append(
                Finding(
                    code=("SERIAL_DEVICE_NODE_MISSING"),
                    severity=(FindingSeverity.WARNING),
                    summary=(f"Serial port {serial_device.port} has no usable device node."),
                    evidence=(f"sysfs entry: {serial_device.sysfs_name}"),
                    recommendation=("Check udev, the bound driver, and kernel logs."),
                )
            )
        elif not (node.readable and node.writable):
            findings.append(
                Finding(
                    code="SERIAL_ACCESS_INCOMPLETE",
                    severity=(FindingSeverity.WARNING),
                    summary=(f"Current user lacks read-write access to {serial_device.port}."),
                    evidence=(
                        f"permissions={node.permissions}, "
                        f"owner={node.owner or 'unknown'}:"
                        f"{node.group or 'unknown'}, "
                        f"access={node.access}"
                    ),
                    recommendation=(
                        "Add the user to the "
                        f"{node.group or 'device-owner'} "
                        "group or apply an approved "
                        "udev rule; Screwdriver will "
                        "not change permissions."
                    ),
                )
            )

        if serial_device.transport.startswith("usb-") and not (serial_device.stable_path_available):
            findings.append(
                Finding(
                    code=("SERIAL_STABLE_PATH_MISSING"),
                    severity=(FindingSeverity.WARNING),
                    summary=(f"USB serial port {serial_device.port} has no stable by-id path."),
                    evidence=(f"Current kernel-assigned name: {serial_device.sysfs_name}"),
                    recommendation=(
                        "Use /dev/serial/by-id when "
                        "available, or create an "
                        "approved udev rule instead "
                        "of depending on a changing "
                        "ttyUSB/ttyACM number."
                    ),
                )
            )

    if not findings:
        findings.append(
            Finding(
                code="HOST_RESOURCES_HEALTHY",
                severity=FindingSeverity.INFO,
                summary=("No host-resource warnings were detected."),
            )
        )

    return findings


def _collect_partition_records(
    record: dict[str, object],
) -> list[StoragePartition]:
    partitions: list[StoragePartition] = []
    children = _as_records(record.get("children"))

    for child in children:
        path = _as_string(child.get("path")) or "unknown"
        filesystem = _as_string(child.get("fstype"))
        mount_points: list[str | None] = [
            point for point in _as_string_list(child.get("mountpoints")) if point
        ]

        if not mount_points:
            mount_points = [None]

        for mount_point in mount_points:
            total: int | None = None
            used: int | None = None
            free: int | None = None
            percent: float | None = None

            if mount_point:
                try:
                    usage = psutil.disk_usage(mount_point)
                except (
                    OSError,
                    PermissionError,
                ):
                    pass
                else:
                    (
                        total,
                        used,
                        free,
                        percent,
                    ) = (
                        usage.total,
                        usage.used,
                        usage.free,
                        usage.percent,
                    )

            if filesystem or mount_point:
                partitions.append(
                    StoragePartition(
                        path=path,
                        filesystem=filesystem,
                        mount_point=mount_point,
                        total_bytes=total,
                        used_bytes=used,
                        available_bytes=free,
                        usage_percent=percent,
                        read_only=_as_bool(child.get("ro")),
                    )
                )

        partitions.extend(_collect_partition_records(child))

    return partitions


def _read_cpuinfo() -> dict[str, str]:
    text = (
        _read_text(
            Path("/proc/cpuinfo"),
            strip_nulls=False,
        )
        or ""
    )
    data: dict[str, str] = {}

    for line in text.splitlines():
        if ":" not in line:
            continue

        key, value = line.split(
            ":",
            1,
        )
        data.setdefault(
            key.strip().lower(),
            value.strip(),
        )

    return data


def _read_lscpu() -> dict[str, str]:
    output = _run_command(
        [
            "lscpu",
            "--json",
        ]
    )

    if output is None:
        return {}

    try:
        raw = json.loads(output)
    except json.JSONDecodeError:
        return {}

    if not isinstance(raw, dict) or not isinstance(
        raw.get("lscpu"),
        list,
    ):
        return {}

    data: dict[str, str] = {}

    for item in cast(
        list[object],
        raw["lscpu"],
    ):
        if not isinstance(item, dict):
            continue

        field = _as_string(item.get("field"))
        value = _as_string(item.get("data"))

        if field and value:
            data[field.rstrip(":").lower()] = value

    return data


def _collect_jetson_details() -> dict[
    str,
    str | int | float | bool | None,
]:
    details: dict[
        str,
        str | int | float | bool | None,
    ] = {}

    release = _read_text(Path("/etc/nv_tegra_release"))

    if release:
        match = re.search(
            (
                r"R(\d+)\s*\(release\).*"
                r"REVISION:\s*([\d.]+)"
            ),
            release,
        )
        details["l4t"] = (
            (f"{match.group(1)}.{match.group(2)}") if match else release.splitlines()[0]
        )

    jetpack = _run_command(
        [
            "dpkg-query",
            "-W",
            "-f=${Version}",
            "nvidia-jetpack",
        ]
    )

    if jetpack:
        details["jetpack"] = jetpack

    cuda_version = _read_cuda_version()

    if cuda_version:
        details["cuda"] = cuda_version

    power_mode = _run_command(
        [
            "nvpmodel",
            "-q",
        ]
    )

    if power_mode:
        details["power_mode"] = " | ".join(power_mode.splitlines())

    return details


def _collect_raspberry_pi_details() -> dict[
    str,
    str | int | float | bool | None,
]:
    details: dict[
        str,
        str | int | float | bool | None,
    ] = {}

    revision = _read_cpuinfo().get("revision")

    if revision:
        details["board_revision"] = revision

    throttled = _run_command(
        [
            "vcgencmd",
            "get_throttled",
        ]
    )

    if throttled:
        details["throttled_state"] = throttled.split(
            "=",
            1,
        )[-1]

    firmware = _run_command(
        [
            "vcgencmd",
            "version",
        ]
    )

    if firmware:
        details["firmware"] = " | ".join(firmware.splitlines())

    return details


def _read_cuda_version() -> str | None:
    version_file = Path("/usr/local/cuda/version.json")
    text = _read_text(version_file)

    if text:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(raw, dict):
                cuda = raw.get("cuda")

                if isinstance(cuda, dict):
                    return _as_string(cuda.get("version"))

    output = _run_command(
        [
            "nvcc",
            "--version",
        ]
    )

    if output:
        match = re.search(
            r"release\s+([\d.]+)",
            output,
        )

        if match:
            return match.group(1)

    return None


def _parse_lspci_gpus(
    output: str,
) -> list[GPUInfo]:
    gpus: list[GPUInfo] = []
    current: GPUInfo | None = None

    for line in output.splitlines():
        if line and not line[0].isspace():
            current = None
            match = re.match(
                (
                    r"(\S+)\s+"
                    r"(.+?(?:VGA|3D|Display).+?):"
                    r"\s+(.+)"
                ),
                line,
            )

            if match:
                description = match.group(3).strip()
                vendor = description.split()[0] if description else "unknown"
                current = GPUInfo(
                    vendor=vendor,
                    model=description,
                    bus_id=match.group(1),
                )
                gpus.append(current)

        elif current is not None:
            stripped = line.strip()

            if stripped.startswith("Kernel driver in use:"):
                current.driver = stripped.split(
                    ":",
                    1,
                )[1].strip()

    return gpus


def _collect_default_route() -> tuple[
    str | None,
    str | None,
]:
    output = _run_command(
        [
            "ip",
            "-j",
            "route",
            "show",
            "default",
        ]
    )

    if output is None:
        return None, None

    try:
        raw = json.loads(output)
    except json.JSONDecodeError:
        return None, None

    if not isinstance(raw, list):
        return None, None

    for item in cast(
        list[object],
        raw,
    ):
        if isinstance(item, dict):
            return (
                _as_string(item.get("dev")),
                _as_string(item.get("gateway")),
            )

    return None, None


def _collect_dns_servers() -> list[str]:
    text = (
        _read_text(
            Path("/etc/resolv.conf"),
            strip_nulls=False,
        )
        or ""
    )
    servers: list[str] = []

    for line in text.splitlines():
        fields = line.split()

        if len(fields) == 2 and fields[0] == "nameserver":
            servers.append(fields[1])

    return servers


def _network_kind(
    record: dict[str, object],
) -> str:
    name = _as_string(record.get("ifname")) or ""
    link_type = _as_string(record.get("link_type"))

    if link_type == "loopback" or name == "lo":
        return "loopback"

    linkinfo = record.get("linkinfo")
    info_kind: str | None = None

    if isinstance(linkinfo, dict):
        info_kind = _as_string(linkinfo.get("info_kind"))

    if re.fullmatch(
        r"usb\d+",
        name,
    ) or name.startswith("l4tbr"):
        return "USB-gadget network"

    if info_kind:
        return info_kind

    if name.startswith(
        (
            "docker",
            "br-",
            "veth",
            "virbr",
            "tun",
            "tap",
        )
    ):
        return "virtual"

    if Path(f"/sys/class/net/{name}/wireless").exists() or name.startswith(
        (
            "wl",
            "wlan",
        )
    ):
        return "wifi"

    if link_type == "ether":
        return "ethernet"

    if Path(f"/sys/class/net/{name}/device").exists():
        return "ethernet"

    return "virtual"


def _detect_package_manager() -> str | None:
    for manager in (
        "apt",
        "dnf",
        "yum",
        "pacman",
        "zypper",
        "apk",
    ):
        if shutil.which(manager):
            return manager

    return None


def _storage_media_type(
    name: str,
    connection: str | None,
    rotational: bool,
) -> str:
    if name.startswith("nvme"):
        return "NVMe SSD"

    if name.startswith("mmcblk"):
        return "eMMC/SD"

    if connection == "usb":
        return "USB HDD" if rotational else "USB flash/SSD"

    return "HDD" if rotational else "SSD/flash"


def _run_command(
    arguments: list[str],
    timeout: float = 3.0,
) -> str | None:
    try:
        completed = subprocess.run(
            arguments,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return None

    return completed.stdout.strip()


def _read_text(
    path: Path,
    *,
    strip_nulls: bool = True,
) -> str | None:
    try:
        value = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except (
        OSError,
        PermissionError,
    ):
        return None

    if strip_nulls:
        value = value.replace(
            "\x00",
            ",",
        )

    value = value.strip(" \t\r\n,")

    return value or None


def _first_text(
    *paths: Path,
) -> str | None:
    for path in paths:
        value = _read_text(path)

        if value is not None:
            return value

    return None


def _username_for_uid(
    uid: int,
) -> str | None:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return None


def _group_for_gid(
    gid: int,
) -> grp.struct_group | None:
    try:
        return grp.getgrgid(gid)
    except KeyError:
        return None


def _driver_name(
    path: Path,
) -> str | None:
    try:
        return path.resolve(strict=True).name
    except (
        OSError,
        RuntimeError,
    ):
        return None


def _read_positive_int(
    path: Path,
) -> int | None:
    value = _parse_int(_read_text(path))

    return value if (value is not None and value >= 0) else None


def _load_average() -> (
    tuple[
        float,
        float,
        float,
    ]
    | None
):
    try:
        return os.getloadavg()
    except OSError:
        return None


def _count_cpu_range(
    value: str | None,
    fallback: int,
) -> int:
    if not value:
        return fallback

    count = 0

    try:
        for part in value.split(","):
            if "-" in part:
                start, end = (
                    int(item)
                    for item in part.split(
                        "-",
                        1,
                    )
                )
                count += end - start + 1
            else:
                int(part)
                count += 1
    except (
        ValueError,
        TypeError,
    ):
        return fallback

    return count or fallback


def _mib_to_bytes(
    value: str,
) -> int | None:
    number = _parse_float(value)

    return int(number * 1024 * 1024) if number is not None else None


def _parse_int(
    value: object,
) -> int | None:
    if isinstance(value, bool):
        return int(value)

    if isinstance(value, int):
        return value

    if isinstance(value, str):
        match = re.search(
            r"-?\d+",
            value,
        )

        if match:
            return int(match.group())

    return None


def _parse_float(
    value: object,
) -> float | None:
    if isinstance(
        value,
        (
            int,
            float,
        ),
    ) and not isinstance(value, bool):
        return float(value)

    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None

    return None


def _as_string(
    value: object,
) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None

    return None


def _as_int(
    value: object,
) -> int | None:
    if isinstance(value, bool):
        return int(value)

    if isinstance(value, int):
        return value

    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None

    return None


def _as_bool(
    value: object,
) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value != 0

    if isinstance(value, str):
        return value.lower() in {
            "1",
            "true",
            "yes",
        }

    return False


def _as_string_list(
    value: object,
) -> list[str]:
    if not isinstance(value, list):
        return []

    return [
        item
        for item in cast(
            list[object],
            value,
        )
        if isinstance(item, str)
    ]


def _as_records(
    value: object,
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []

    return [
        cast(
            dict[str, object],
            item,
        )
        for item in cast(
            list[object],
            value,
        )
        if isinstance(item, dict)
    ]
