"""Collect passive information about the local Linux computer."""

from __future__ import annotations

import getpass
import grp
import json
import os
import platform
import pwd
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from screwdriver.models import (
    CPUInfo,
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


def collect_host() -> SystemSnapshot:
    """Collect a complete passive snapshot of the current Linux computer."""

    return SystemSnapshot(
        identity=_collect_identity(),
        operating_system=_collect_operating_system(),
        platform=_collect_platform(),
        cpu=_collect_cpu(),
        memory=_collect_memory(),
        storage_devices=_collect_storage_devices(),
        gpus=_collect_gpus(),
        thermal_sensors=_collect_thermal_sensors(),
        power=_collect_power(),
        network=collect_network_info(),
    )


def _collect_identity() -> HostIdentity:
    """Collect host and current-account identity."""

    uid = os.getuid()
    gid = os.getgid()

    try:
        username = pwd.getpwuid(uid).pw_name
        login_shell = pwd.getpwuid(uid).pw_shell or None
    except KeyError:
        username = getpass.getuser()
        login_shell = None

    try:
        effective_username = pwd.getpwuid(os.geteuid()).pw_name
    except KeyError:
        effective_username = getpass.getuser()

    groups: list[str] = []

    for group_id in os.getgroups():
        try:
            groups.append(grp.getgrgid(group_id).gr_name)
        except KeyError:
            groups.append(str(group_id))

    primary_group = _group_name(gid)

    if primary_group not in groups:
        groups.append(primary_group)

    return HostIdentity(
        hostname=platform.node(),
        username=username,
        effective_username=effective_username,
        uid=uid,
        gid=gid,
        groups=sorted(set(groups)),
        login_shell=login_shell,
        machine_id=_read_text(Path("/etc/machine-id")),
    )


def _group_name(group_id: int) -> str:
    """Return a group name, falling back to its numeric ID."""

    try:
        return grp.getgrgid(group_id).gr_name
    except KeyError:
        return str(group_id)


def _collect_operating_system() -> OperatingSystemInfo:
    """Collect operating-system and runtime information."""

    try:
        distribution = platform.freedesktop_os_release().get(
            "PRETTY_NAME",
            platform.system(),
        )
    except OSError:
        distribution = platform.system()

    boot_timestamp = psutil.boot_time()
    boot_time = datetime.fromtimestamp(boot_timestamp, tz=UTC)
    uptime_seconds = max(0.0, datetime.now(UTC).timestamp() - boot_timestamp)

    return OperatingSystemInfo(
        distribution=distribution,
        kernel=platform.release(),
        kernel_build=platform.version(),
        architecture=platform.machine(),
        boot_mode=("UEFI" if Path("/sys/firmware/efi").exists() else "legacy or device-tree"),
        init_system=_detect_init_system(),
        package_manager=_detect_package_manager(),
        timezone=datetime.now().astimezone().tzname() or "unknown",
        boot_time=boot_time,
        uptime_seconds=round(uptime_seconds, 2),
        process_count=len(psutil.pids()),
    )


def _detect_init_system() -> str | None:
    """Detect the active init system without changing system state."""

    if Path("/run/systemd/system").exists():
        return "systemd"

    if Path("/run/openrc").exists():
        return "OpenRC"

    process_name = _read_text(Path("/proc/1/comm"))

    return process_name or None


def _detect_package_manager() -> str | None:
    """Return the first recognized package manager."""

    package_managers = (
        "apt",
        "dnf",
        "yum",
        "pacman",
        "zypper",
        "apk",
        "emerge",
    )

    for manager in package_managers:
        if shutil.which(manager):
            return manager

    return None


def _collect_platform() -> PlatformInfo:
    """Collect board, firmware, virtualization, and platform-family data."""

    manufacturer = _first_text(
        Path("/sys/class/dmi/id/sys_vendor"),
        Path("/sys/firmware/devicetree/base/vendor"),
    )
    product_name = _first_text(
        Path("/sys/class/dmi/id/product_name"),
        Path("/sys/firmware/devicetree/base/model"),
    )
    board_name = _first_text(
        Path("/sys/class/dmi/id/board_name"),
        Path("/sys/firmware/devicetree/base/model"),
    )
    board_version = _read_text(Path("/sys/class/dmi/id/board_version"))
    firmware_version = _first_text(
        Path("/sys/class/dmi/id/bios_version"),
        Path("/sys/firmware/devicetree/base/firmware-version"),
    )
    serial_number = _first_text(
        Path("/sys/class/dmi/id/product_serial"),
        Path("/sys/firmware/devicetree/base/serial-number"),
    )

    virtualization = _detect_virtualization()
    machine_type = "virtual machine" if virtualization is not None else "physical computer"

    family, enrichment_module, details = _identify_platform_family(
        manufacturer=manufacturer,
        product_name=product_name,
        board_name=board_name,
    )

    return PlatformInfo(
        manufacturer=manufacturer,
        product_name=product_name,
        board_name=board_name,
        board_version=board_version,
        firmware_version=firmware_version,
        serial_number=serial_number,
        machine_type=machine_type,
        virtualization=virtualization,
        family=family,
        enrichment_module=enrichment_module,
        details=details,
    )


def _detect_virtualization() -> str | None:
    """Detect a virtualized runtime using systemd when available."""

    result = _run_command(["systemd-detect-virt"])

    if result is None:
        return None

    value = result.strip()

    if not value or value == "none":
        return None

    return value


def _identify_platform_family(
    manufacturer: str | None,
    product_name: str | None,
    board_name: str | None,
) -> tuple[
    str,
    str | None,
    dict[str, str | int | float | bool | None],
]:
    """Identify known robotics-computer families and add local enrichment."""

    combined_name = " ".join(
        value or "" for value in (manufacturer, product_name, board_name)
    ).lower()

    details: dict[str, str | int | float | bool | None] = {}

    jetson_release = _read_text(Path("/etc/nv_tegra_release"))

    if jetson_release or "jetson" in combined_name:
        if jetson_release:
            details["l4t_release"] = jetson_release

        jetpack_version = _read_jetpack_version()

        if jetpack_version:
            details["jetpack_package"] = jetpack_version

        power_mode = _run_command(["nvpmodel", "-q"])

        if power_mode:
            details["power_mode"] = " ".join(power_mode.splitlines())

        return "nvidia-jetson", "jetson", details

    if "raspberry pi" in combined_name:
        revision = _read_cpu_information_value("Revision")

        if revision:
            details["board_revision"] = revision

        return "raspberry-pi", "raspberry-pi", details

    if virtualization := _detect_virtualization():
        details["virtualization"] = virtualization
        return "virtual-machine", "virtualization", details

    return "generic-linux", None, details


def _read_jetpack_version() -> str | None:
    """Read the installed JetPack metapackage when dpkg is available."""

    result = _run_command(
        [
            "dpkg-query",
            "-W",
            "-f=${Version}",
            "nvidia-jetpack",
        ]
    )

    return result.strip() if result else None


def _collect_cpu() -> CPUInfo:
    """Collect CPU topology, frequency, load, and cache information."""

    model = (
        _read_cpu_information_value("model name")
        or _read_cpu_information_value("Model")
        or _read_cpu_information_value("Hardware")
        or platform.processor()
        or platform.machine()
    )

    vendor = _read_cpu_information_value("vendor_id") or _read_cpu_information_value(
        "CPU implementer"
    )

    logical_cpus = psutil.cpu_count(logical=True) or 1
    physical_cores = psutil.cpu_count(logical=False)

    try:
        online_cpus = int(os.sysconf("SC_NPROCESSORS_ONLN"))
    except (ValueError, OSError):
        online_cpus = logical_cpus

    frequency = psutil.cpu_freq()

    try:
        load_average: tuple[float, float, float] | None = os.getloadavg()
    except OSError:
        load_average = None

    return CPUInfo(
        model=model,
        vendor=vendor,
        sockets=_read_lscpu_integer("Socket(s)"),
        physical_cores=physical_cores,
        logical_cpus=logical_cpus,
        online_cpus=online_cpus,
        current_frequency_mhz=(round(frequency.current, 2) if frequency is not None else None),
        minimum_frequency_mhz=(
            round(frequency.min, 2) if frequency is not None and frequency.min > 0 else None
        ),
        maximum_frequency_mhz=(
            round(frequency.max, 2) if frequency is not None and frequency.max > 0 else None
        ),
        usage_percent=round(psutil.cpu_percent(interval=0.1), 2),
        load_average=(
            tuple(round(value, 2) for value in load_average) if load_average is not None else None
        ),
        governor=_read_text(Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")),
        caches=_collect_cpu_caches(),
    )


def _read_cpu_information_value(key: str) -> str | None:
    """Read the first matching field from /proc/cpuinfo."""

    cpu_information = _read_text(Path("/proc/cpuinfo"))

    if cpu_information is None:
        return None

    expected_key = key.lower()

    for line in cpu_information.splitlines():
        if ":" not in line:
            continue

        current_key, value = line.split(":", 1)

        if current_key.strip().lower() == expected_key:
            cleaned_value = value.strip()

            if cleaned_value:
                return cleaned_value

    return None


def _read_lscpu_integer(field_name: str) -> int | None:
    """Read one integer field from lscpu JSON output."""

    fields = _read_lscpu_fields()
    value = fields.get(field_name)

    if value is None:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def _collect_cpu_caches() -> dict[str, str]:
    """Collect human-readable CPU cache sizes."""

    fields = _read_lscpu_fields()
    caches: dict[str, str] = {}

    for key in ("L1d cache", "L1i cache", "L2 cache", "L3 cache"):
        value = fields.get(key)

        if value:
            caches[key] = value

    return caches


def _read_lscpu_fields() -> dict[str, str]:
    """Convert lscpu JSON output into a field-value mapping."""

    raw_data = _run_json_command(["lscpu", "--json"])

    if not isinstance(raw_data, dict):
        return {}

    records = raw_data.get("lscpu")

    if not isinstance(records, list):
        return {}

    fields: dict[str, str] = {}

    for record in records:
        if not isinstance(record, dict):
            continue

        field = record.get("field")
        data = record.get("data")

        if isinstance(field, str) and isinstance(data, str):
            fields[field.rstrip(":")] = data.strip()

    return fields


def _collect_memory() -> MemoryInfo:
    """Collect physical-memory and swap usage."""

    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()

    return MemoryInfo(
        total_bytes=memory.total,
        used_bytes=memory.used,
        available_bytes=memory.available,
        usage_percent=round(memory.percent, 2),
        shared_bytes=getattr(memory, "shared", 0),
        swap_total_bytes=swap.total,
        swap_used_bytes=swap.used,
        swap_free_bytes=swap.free,
        swap_usage_percent=round(swap.percent, 2),
    )


def _collect_storage_devices() -> list[StorageDevice]:
    """Collect block devices and mounted filesystems using lsblk."""

    raw_data = _run_json_command(
        [
            "lsblk",
            "--json",
            "--bytes",
            "--output",
            ("NAME,PATH,TYPE,SIZE,MODEL,SERIAL,TRAN,ROTA,RM,RO,FSTYPE,MOUNTPOINTS,REV"),
        ]
    )

    if not isinstance(raw_data, dict):
        return []

    raw_devices = raw_data.get("blockdevices")

    if not isinstance(raw_devices, list):
        return []

    devices: list[StorageDevice] = []

    for raw_device in raw_devices:
        if not isinstance(raw_device, dict):
            continue

        if raw_device.get("type") != "disk":
            continue

        device = _parse_storage_device(raw_device)

        if device is not None:
            devices.append(device)

    return devices


def _parse_storage_device(
    raw_device: dict[str, Any],
) -> StorageDevice | None:
    """Convert one lsblk disk record into a storage model."""

    name = _optional_string(raw_device.get("name"))
    path = _optional_string(raw_device.get("path"))

    if name is None or path is None:
        return None

    rotational = _as_bool(raw_device.get("rota"))
    connection = _optional_string(raw_device.get("tran"))

    if rotational:
        media_type = "HDD"
    elif connection == "nvme" or name.startswith("nvme"):
        media_type = "NVMe SSD"
    else:
        media_type = "SSD or flash storage"

    partitions: list[StoragePartition] = []
    children = raw_device.get("children")

    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                partitions.extend(_parse_storage_node(child))

    return StorageDevice(
        name=name,
        path=path,
        model=_optional_string(raw_device.get("model")),
        serial_number=_optional_string(raw_device.get("serial")),
        connection=connection,
        media_type=media_type,
        capacity_bytes=_as_int(raw_device.get("size")) or 0,
        firmware_version=_optional_string(raw_device.get("rev")),
        removable=_as_bool(raw_device.get("rm")),
        read_only=_as_bool(raw_device.get("ro")),
        partitions=partitions,
    )


def _parse_storage_node(
    raw_node: dict[str, Any],
) -> list[StoragePartition]:
    """Recursively collect partitions and mounted logical volumes."""

    partitions: list[StoragePartition] = []

    path = _optional_string(raw_node.get("path"))
    filesystem = _optional_string(raw_node.get("fstype"))
    mount_points = _string_list(raw_node.get("mountpoints"))
    read_only = _as_bool(raw_node.get("ro"))

    if path is not None and (filesystem is not None or mount_points):
        if not mount_points:
            mount_points = [None]

        for mount_point in mount_points:
            usage = _read_disk_usage(mount_point)

            partitions.append(
                StoragePartition(
                    path=path,
                    filesystem=filesystem,
                    mount_point=mount_point,
                    total_bytes=usage[0],
                    used_bytes=usage[1],
                    available_bytes=usage[2],
                    usage_percent=usage[3],
                    read_only=read_only,
                )
            )

    children = raw_node.get("children")

    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                partitions.extend(_parse_storage_node(child))

    return partitions


def _read_disk_usage(
    mount_point: str | None,
) -> tuple[int | None, int | None, int | None, float | None]:
    """Read filesystem usage while tolerating inaccessible mount points."""

    if mount_point is None:
        return None, None, None, None

    try:
        usage = psutil.disk_usage(mount_point)
    except (FileNotFoundError, PermissionError, OSError):
        return None, None, None, None

    return (
        usage.total,
        usage.used,
        usage.free,
        round(usage.percent, 2),
    )


def _collect_gpus() -> list[GPUInfo]:
    """Collect PCI graphics devices and integrated Jetson GPUs."""

    output = _run_command(["lspci", "-Dnnk"])
    gpus: list[GPUInfo] = []

    if output:
        for block in output.split("\n\n"):
            first_line = block.splitlines()[0] if block.splitlines() else ""

            if not any(
                device_class in first_line
                for device_class in (
                    "VGA compatible controller",
                    "3D controller",
                    "Display controller",
                )
            ):
                continue

            bus_id = first_line.split(maxsplit=1)[0]
            model = first_line.split(":", 2)[-1].strip()
            driver = _extract_kernel_driver(block)
            vendor = _identify_gpu_vendor(model)

            gpus.append(
                GPUInfo(
                    vendor=vendor,
                    model=model,
                    driver=driver,
                    bus_id=bus_id,
                )
            )

    device_model = _read_text(Path("/sys/firmware/devicetree/base/model")) or ""

    if "jetson" in device_model.lower() and not any(gpu.vendor == "NVIDIA" for gpu in gpus):
        gpus.append(
            GPUInfo(
                vendor="NVIDIA",
                model=f"{device_model} integrated GPU",
                driver=_detect_loaded_driver(("nvgpu", "nouveau")),
            )
        )

    _enrich_nvidia_gpus(gpus)

    return gpus


def _extract_kernel_driver(block: str) -> str | None:
    """Extract the active kernel driver from one lspci record."""

    prefix = "Kernel driver in use:"

    for line in block.splitlines():
        stripped_line = line.strip()

        if stripped_line.startswith(prefix):
            return stripped_line.removeprefix(prefix).strip() or None

    return None


def _identify_gpu_vendor(model: str) -> str:
    """Infer the accelerator vendor from its PCI description."""

    lowered_model = model.lower()

    if "nvidia" in lowered_model:
        return "NVIDIA"

    if "amd" in lowered_model or "advanced micro devices" in lowered_model:
        return "AMD"

    if "intel" in lowered_model:
        return "Intel"

    if "qualcomm" in lowered_model:
        return "Qualcomm"

    return "Unknown"


def _detect_loaded_driver(candidates: tuple[str, ...]) -> str | None:
    """Return the first candidate listed in /proc/modules."""

    modules = _read_text(Path("/proc/modules"))

    if modules is None:
        return None

    loaded_modules = {line.split(maxsplit=1)[0] for line in modules.splitlines() if line.strip()}

    for candidate in candidates:
        if candidate in loaded_modules:
            return candidate

    return None


def _enrich_nvidia_gpus(gpus: list[GPUInfo]) -> None:
    """Add safe runtime data from nvidia-smi when it is available."""

    output = _run_command(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
        ]
    )

    if not output:
        return

    runtime_records = [line.strip() for line in output.splitlines() if line.strip()]

    nvidia_gpus = [gpu for gpu in gpus if gpu.vendor == "NVIDIA"]

    for gpu, record in zip(nvidia_gpus, runtime_records, strict=False):
        values = [value.strip() for value in record.split(",")]

        if len(values) != 4:
            continue

        gpu.model = values[0] or gpu.model
        gpu.memory_bytes = _mib_to_bytes(values[1])
        gpu.usage_percent = _as_float(values[2])
        gpu.temperature_celsius = _as_float(values[3])


def _mib_to_bytes(value: object) -> int | None:
    """Convert a MiB value to bytes."""

    parsed_value = _as_float(value)

    if parsed_value is None:
        return None

    return int(parsed_value * 1024 * 1024)


def _collect_thermal_sensors() -> list[ThermalSensor]:
    """Collect all readable temperature sensors."""

    try:
        temperatures = psutil.sensors_temperatures(fahrenheit=False)
    except (AttributeError, OSError):
        return []

    sensors: list[ThermalSensor] = []

    for group_name, entries in temperatures.items():
        for index, entry in enumerate(entries, start=1):
            label = entry.label or f"sensor-{index}"

            sensors.append(
                ThermalSensor(
                    name=f"{group_name}/{label}",
                    temperature_celsius=round(entry.current, 2),
                    high_celsius=(round(entry.high, 2) if entry.high is not None else None),
                    critical_celsius=(
                        round(entry.critical, 2) if entry.critical is not None else None
                    ),
                )
            )

    return sensors


def _collect_power() -> PowerInfo:
    """Collect battery and power-source information."""

    try:
        battery = psutil.sensors_battery()
    except (AttributeError, OSError):
        battery = None

    if battery is None:
        return PowerInfo(
            source="external or unknown",
            battery_present=False,
        )

    seconds_remaining = battery.secsleft

    if seconds_remaining < 0:
        seconds_remaining = None

    return PowerInfo(
        source="external power" if battery.power_plugged else "battery",
        battery_present=True,
        battery_percent=round(battery.percent, 2),
        charging=battery.power_plugged,
        seconds_remaining=seconds_remaining,
    )


def collect_network_info() -> NetworkInfo:
    """Collect interfaces, IPv4 routing, and DNS configuration."""

    interfaces = collect_network_interfaces()
    default_interface, default_gateway = _collect_default_route()

    for interface in interfaces:
        interface.is_default_route = interface.name == default_interface

    dns_servers = _collect_dns_servers()

    return NetworkInfo(
        interfaces=interfaces,
        default_interface=default_interface,
        default_gateway=default_gateway,
        dns_servers=dns_servers,
        internet_route_available=default_interface is not None,
    )


def collect_network_interfaces() -> list[NetworkInterface]:
    """Collect local interfaces while intentionally omitting IPv6."""

    raw_data = _run_json_command(["ip", "-j", "address", "show"])

    if not isinstance(raw_data, list):
        return []

    interfaces: list[NetworkInterface] = []

    for raw_interface in raw_data:
        if not isinstance(raw_interface, dict):
            continue

        name = _optional_string(raw_interface.get("ifname"))

        if name is None:
            continue

        flags = _string_list(raw_interface.get("flags"))
        link_type = _optional_string(raw_interface.get("link_type"))
        operating_state = _optional_string(raw_interface.get("operstate"))
        address_records = raw_interface.get("addr_info")
        ipv4_addresses: list[str] = []

        if isinstance(address_records, list):
            for address_record in address_records:
                if not isinstance(address_record, dict):
                    continue

                if address_record.get("family") != "inet":
                    continue

                address = _optional_string(address_record.get("local"))

                if address:
                    prefix_length = _as_int(address_record.get("prefixlen"))

                    if prefix_length is not None:
                        address = f"{address}/{prefix_length}"

                    ipv4_addresses.append(address)

        interface_path = Path("/sys/class/net") / name

        interfaces.append(
            NetworkInterface(
                name=name,
                interface_type=_classify_interface(
                    name=name,
                    link_type=link_type,
                ),
                ipv4_addresses=ipv4_addresses,
                mac_address=_optional_string(raw_interface.get("address")),
                state=_determine_interface_state(
                    flags=flags,
                    operating_state=operating_state,
                ),
                mtu=_as_int(raw_interface.get("mtu")),
                speed_mbps=_read_integer_file(interface_path / "speed"),
                duplex=_read_text(interface_path / "duplex"),
                driver=_read_interface_driver(interface_path),
                is_loopback=(link_type == "loopback" or "LOOPBACK" in flags),
                is_virtual=_is_virtual_interface(name),
            )
        )

    return interfaces


def _collect_default_route() -> tuple[str | None, str | None]:
    """Collect the default IPv4 route."""

    raw_routes = _run_json_command(["ip", "-j", "-4", "route", "show", "default"])

    if not isinstance(raw_routes, list):
        return None, None

    for route in raw_routes:
        if not isinstance(route, dict):
            continue

        interface = _optional_string(route.get("dev"))
        gateway = _optional_string(route.get("gateway"))

        if interface is not None:
            return interface, gateway

    return None, None


def _collect_dns_servers() -> list[str]:
    """Collect configured DNS server addresses."""

    resolv_conf = _read_text(Path("/etc/resolv.conf"))

    if resolv_conf is None:
        return []

    servers: list[str] = []

    for line in resolv_conf.splitlines():
        stripped_line = line.strip()

        if not stripped_line.startswith("nameserver "):
            continue

        parts = stripped_line.split()

        if len(parts) >= 2 and ":" not in parts[1]:
            servers.append(parts[1])

    return servers


def _classify_interface(name: str, link_type: str | None) -> str:
    """Classify an interface from its conventional Linux name."""

    if link_type == "loopback" or name == "lo":
        return "loopback"

    if name.startswith(("wl", "wlan")):
        return "wireless"

    if name.startswith(("en", "eth")):
        return "ethernet"

    if name.startswith(("ww", "usb")):
        return "cellular or USB network"

    if name.startswith(("can", "vcan")):
        return "CAN"

    if name.startswith(("docker", "br-", "virbr", "veth")):
        return "virtual bridge"

    if name.startswith(("tun", "tap", "tailscale", "wg")):
        return "tunnel"

    return link_type or "unknown"


def _determine_interface_state(
    flags: list[str],
    operating_state: str | None,
) -> str:
    """Determine the current administrative interface state."""

    if "UP" in flags:
        return "up"

    if operating_state:
        return operating_state.lower()

    return "unknown"


def _read_interface_driver(interface_path: Path) -> str | None:
    """Resolve the kernel driver bound to an interface."""

    driver_path = interface_path / "device" / "driver"

    try:
        return driver_path.resolve(strict=True).name
    except (FileNotFoundError, OSError):
        return None


def _is_virtual_interface(name: str) -> bool:
    """Determine whether the interface exists only in virtual sysfs."""

    physical_device = Path("/sys/class/net") / name / "device"

    if physical_device.exists():
        return False

    return name != "lo"


def _run_command(command: list[str]) -> str | None:
    """Run a passive command and return stdout on success."""

    try:
        completed_process = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (
        FileNotFoundError,
        PermissionError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        OSError,
    ):
        return None

    output = completed_process.stdout.strip()

    return output or None


def _run_json_command(command: list[str]) -> object:
    """Run a command and decode its JSON output."""

    output = _run_command(command)

    if output is None:
        return None

    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return None


def _read_text(path: Path) -> str | None:
    """Read and clean a small Linux metadata file."""

    try:
        value = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except (FileNotFoundError, PermissionError, IsADirectoryError, OSError):
        return None

    cleaned_value = value.replace("\x00", "").strip()

    return cleaned_value or None


def _first_text(*paths: Path) -> str | None:
    """Return the first readable nonempty value from several paths."""

    for path in paths:
        value = _read_text(path)

        if value is not None:
            return value

    return None


def _read_integer_file(path: Path) -> int | None:
    """Read an integer from a sysfs file."""

    value = _read_text(path)

    if value is None:
        return None

    try:
        parsed_value = int(value)
    except ValueError:
        return None

    return parsed_value if parsed_value >= 0 else None


def _optional_string(value: object) -> str | None:
    """Return a clean string when possible."""

    if not isinstance(value, str):
        return None

    cleaned_value = value.strip()

    return cleaned_value or None


def _string_list(value: object) -> list[str]:
    """Return only usable strings from an unknown list value."""

    if not isinstance(value, list):
        return []

    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _as_int(value: object) -> int | None:
    """Safely convert a JSON value into an integer."""

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, (int, float)):
        return int(value)

    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None

    return None


def _as_float(value: object) -> float | None:
    """Safely convert a value into a float."""

    if isinstance(value, bool):
        return float(value)

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None

    return None


def _as_bool(value: object) -> bool:
    """Interpret common bool-like values."""

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value != 0

    if isinstance(value, str):
        return value.strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    return False
