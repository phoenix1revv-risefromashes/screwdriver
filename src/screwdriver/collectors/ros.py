"""Passively inspect ROS and common robotics software components."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import shutil
from pathlib import Path

from screwdriver.models import (
    Component,
    ComponentStatus,
    Finding,
    FindingSeverity,
)

_ROS_ROOT = Path("/opt/ros")

_ROBOTICS_STACKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Navigation2", ("nav2_bringup", "nav2_controller")),
    ("MoveIt", ("moveit_ros_move_group", "moveit_core")),
    ("ros2_control", ("controller_manager", "hardware_interface")),
    ("SLAM Toolbox", ("slam_toolbox",)),
    ("RViz", ("rviz2", "rviz")),
    ("Robot State Publisher", ("robot_state_publisher",)),
    ("Gazebo ROS integration", ("ros_gz_bridge", "gazebo_ros")),
    ("Camera drivers", ("usb_cam", "v4l2_camera", "realsense2_camera")),
    (
        "LiDAR drivers",
        (
            "rplidar_ros",
            "rplidar_ros2",
            "urg_node",
            "velodyne_driver",
            "ouster_ros",
        ),
    ),
    ("micro-ROS", ("micro_ros_agent", "micro_ros_setup")),
)

_TOOLS: tuple[tuple[str, str, str], ...] = (
    ("ROS 2 CLI", "ros2", "ROS tool"),
    ("ROS 1 master", "roscore", "ROS tool"),
    ("colcon", "colcon", "build tool"),
    ("rosdep", "rosdep", "dependency tool"),
    ("vcstool", "vcs", "source-management tool"),
    ("RViz 2", "rviz2", "visualization tool"),
    ("Gazebo", "gz", "simulator"),
    ("Docker", "docker", "container runtime"),
)

_PYTHON_LIBRARIES: tuple[
    tuple[str, str, tuple[str, ...]],
    ...,
] = (
    (
        "OpenCV",
        "cv2",
        (
            "opencv-python",
            "opencv-contrib-python",
        ),
    ),
    ("PyTorch", "torch", ("torch",)),
    ("TensorRT", "tensorrt", ("tensorrt",)),
    (
        "Ultralytics",
        "ultralytics",
        ("ultralytics",),
    ),
)


def collect_robotics_software() -> tuple[
    list[Component],
    list[Finding],
]:
    """Return passive ROS/software inventory and evidence-based findings."""

    findings: list[Finding] = []
    installed_distributions = _installed_ros_distributions()
    active_distribution = _environment_value("ROS_DISTRO")
    raw_ros_version = _environment_value("ROS_VERSION")
    ros_version = _environment_integer("ROS_VERSION")
    ros2_path = shutil.which("ros2")
    roscore_path = shutil.which("roscore")

    if raw_ros_version is not None and ros_version not in {1, 2}:
        findings.append(
            Finding(
                code="ROS_VERSION_INVALID",
                severity=FindingSeverity.ERROR,
                summary="ROS_VERSION must be 1 or 2.",
                evidence=(f"ROS_VERSION={os.environ.get('ROS_VERSION', '')}"),
                recommendation=("Open a clean shell and source the intended ROS setup file."),
            )
        )

    detected = bool(
        installed_distributions
        or active_distribution
        or ros_version in {1, 2}
        or ros2_path
        or roscore_path
    )
    environment_sourced = bool(active_distribution and ros_version in {1, 2})
    prefix_paths = _collect_prefix_paths(ros_version)
    inspection_prefixes = _inspection_prefixes(
        prefix_paths,
        active_distribution,
        installed_distributions,
    )
    invalid_prefix_paths = [path for path in prefix_paths if not Path(path).is_dir()]
    packages = _collect_package_names(
        inspection_prefixes,
        ros_version,
    )
    active_prefix_distributions = _active_prefix_distributions(prefix_paths)
    workspaces = _workspace_paths(prefix_paths)
    rmw_implementation = _environment_value("RMW_IMPLEMENTATION")
    domain_id = _diagnose_domain_id(
        detected,
        findings,
    )
    localhost_only = _diagnose_localhost_only(findings)
    dds_configuration = _diagnose_dds_configuration(findings)

    _diagnose_environment(
        installed_distributions=(installed_distributions),
        active_distribution=active_distribution,
        ros_version=ros_version,
        environment_sourced=environment_sourced,
        ros2_path=ros2_path,
        roscore_path=roscore_path,
        invalid_prefix_paths=(invalid_prefix_paths),
        active_prefix_distributions=(active_prefix_distributions),
        packages=packages,
        rmw_implementation=rmw_implementation,
        findings=findings,
    )

    components: list[Component] = [
        Component(
            category="ROS environment",
            name=("ROS installation and environment"),
            status=_environment_status(
                findings,
                detected,
            ),
            details={
                "detected": detected,
                "environment_sourced": (environment_sourced),
                "ros_version": ros_version,
                "active_distribution": (active_distribution),
                "installed_distributions": (", ".join(installed_distributions) or None),
                "ros2_executable": ros2_path,
                "roscore_executable": (roscore_path),
                "ros_domain_id": domain_id,
                "ros_localhost_only": (localhost_only),
                "rmw_implementation": (rmw_implementation),
                "indexed_package_count": (len(packages)),
                "prefix_paths": (os.pathsep.join(prefix_paths) or None),
                "workspaces": (os.pathsep.join(workspaces) or None),
                "dds_configuration": (
                    "; ".join(f"{name}={value}" for name, value in dds_configuration.items())
                    or None
                ),
            },
        )
    ]

    stack_components = [
        _package_component(
            name,
            candidates,
            packages,
        )
        for name, candidates in _ROBOTICS_STACKS
    ]
    tool_components = [
        _executable_component(
            name,
            executable,
            category,
        )
        for name, executable, category in _TOOLS
    ]
    compute_components = [
        _python_component(
            name,
            module,
            distributions,
        )
        for name, module, distributions in _PYTHON_LIBRARIES
    ]
    compute_components.append(_cuda_component())

    components.extend(stack_components)
    components.extend(tool_components)
    components.extend(compute_components)

    if not detected:
        findings.append(
            Finding(
                code="ROS_NOT_DETECTED",
                severity=FindingSeverity.INFO,
                summary=("ROS was not detected on this computer."),
                recommendation=(
                    "This is informational unless the computer is expected to run ROS."
                ),
            )
        )
    elif not _has_problem(findings):
        version_label = f"ROS {ros_version}" if ros_version else "ROS"
        distro_label = f" {active_distribution}" if active_distribution else ""
        findings.append(
            Finding(
                code="ROS_ENVIRONMENT_HEALTHY",
                severity=FindingSeverity.INFO,
                summary=(f"[OK] {version_label}{distro_label} configuration is consistent."),
                evidence=(f"Indexed packages: {len(packages)}"),
            )
        )

    installed_stacks = [component.name for component in stack_components if _is_ok(component)]
    if installed_stacks:
        findings.append(
            Finding(
                code="ROBOTICS_STACKS_DETECTED",
                severity=FindingSeverity.INFO,
                summary=("[OK] Detected robotics stacks: " + ", ".join(installed_stacks) + "."),
            )
        )

    missing_stacks = [component.name for component in stack_components if not _is_ok(component)]
    if detected and missing_stacks:
        findings.append(
            Finding(
                code=("OPTIONAL_ROBOTICS_STACKS_NOT_DETECTED"),
                severity=FindingSeverity.INFO,
                summary=(
                    "Optional robotics stacks not detected: " + ", ".join(missing_stacks) + "."
                ),
                recommendation=("No action is required unless this robot needs one of them."),
            )
        )

    installed_tools = [component.name for component in tool_components if _is_ok(component)]
    if installed_tools:
        findings.append(
            Finding(
                code="ROBOTICS_TOOLS_DETECTED",
                severity=FindingSeverity.INFO,
                summary=("[OK] Available robotics tools: " + ", ".join(installed_tools) + "."),
            )
        )

    installed_compute = [component.name for component in compute_components if _is_ok(component)]
    if installed_compute:
        findings.append(
            Finding(
                code=("ROBOTICS_COMPUTE_STACK_DETECTED"),
                severity=FindingSeverity.INFO,
                summary=("[OK] Available compute stack: " + ", ".join(installed_compute) + "."),
            )
        )

    return components, findings


def _diagnose_environment(
    *,
    installed_distributions: list[str],
    active_distribution: str | None,
    ros_version: int | None,
    environment_sourced: bool,
    ros2_path: str | None,
    roscore_path: str | None,
    invalid_prefix_paths: list[str],
    active_prefix_distributions: list[str],
    packages: set[str],
    rmw_implementation: str | None,
    findings: list[Finding],
) -> None:
    if installed_distributions and not environment_sourced:
        findings.append(
            Finding(
                code="ROS_ENVIRONMENT_NOT_SOURCED",
                severity=FindingSeverity.WARNING,
                summary=("ROS is installed, but the current shell is not sourced."),
                evidence=("Installed distributions: " + ", ".join(installed_distributions)),
                recommendation=("Run: source /opt/ros/<distribution>/setup.bash"),
            )
        )

    if ros_version == 2 and not ros2_path:
        findings.append(
            Finding(
                code="ROS2_EXECUTABLE_MISSING",
                severity=FindingSeverity.ERROR,
                summary=("ROS 2 is active, but the ros2 executable is unavailable."),
                evidence=(f"ROS_DISTRO={active_distribution or 'unknown'}"),
                recommendation=("Check PATH and source the correct ROS 2 setup file."),
            )
        )

    if ros_version == 1 and not roscore_path:
        findings.append(
            Finding(
                code="ROS1_EXECUTABLE_MISSING",
                severity=FindingSeverity.ERROR,
                summary=("ROS 1 is active, but the roscore executable is unavailable."),
                evidence=(f"ROS_DISTRO={active_distribution or 'unknown'}"),
                recommendation=("Check PATH and source the correct ROS 1 setup file."),
            )
        )

    if invalid_prefix_paths:
        findings.append(
            Finding(
                code="ROS_PREFIX_PATH_INVALID",
                severity=FindingSeverity.WARNING,
                summary=("ROS environment paths contain missing directories."),
                evidence=", ".join(invalid_prefix_paths),
                recommendation=("Remove stale paths or source the intended workspace again."),
            )
        )

    if len(active_prefix_distributions) > 1:
        findings.append(
            Finding(
                code="ROS_DISTRIBUTIONS_MIXED",
                severity=FindingSeverity.WARNING,
                summary=("Paths from multiple ROS distributions are active."),
                evidence=", ".join(active_prefix_distributions),
                recommendation=("Open a clean shell and source only one ROS distribution."),
            )
        )

    if (
        active_distribution
        and installed_distributions
        and active_distribution not in installed_distributions
        and active_distribution not in active_prefix_distributions
    ):
        findings.append(
            Finding(
                code="ROS_ACTIVE_DISTRO_NOT_FOUND",
                severity=FindingSeverity.ERROR,
                summary=("ROS_DISTRO identifies a distribution that could not be found."),
                evidence=(f"ROS_DISTRO={active_distribution}"),
                recommendation=("Source an installed distribution from /opt/ros."),
            )
        )

    if rmw_implementation and rmw_implementation not in packages:
        findings.append(
            Finding(
                code="ROS_RMW_NOT_INSTALLED",
                severity=FindingSeverity.ERROR,
                summary=("The selected ROS middleware package is not installed."),
                evidence=(f"RMW_IMPLEMENTATION={rmw_implementation}"),
                recommendation=("Install that RMW package or remove the override."),
            )
        )

    if environment_sourced and not packages:
        findings.append(
            Finding(
                code="ROS_PACKAGE_INDEX_EMPTY",
                severity=FindingSeverity.ERROR,
                summary=("The active ROS environment exposes no package index."),
                evidence=("No packages were found in the active prefix paths."),
                recommendation=("Source the correct underlay and workspace setup files."),
            )
        )
    elif ros_version == 2 and packages and not ({"rclcpp", "rclpy"} & packages):
        findings.append(
            Finding(
                code="ROS2_CLIENT_LIBRARY_MISSING",
                severity=FindingSeverity.WARNING,
                summary=("No standard ROS 2 client library was found in the package index."),
                evidence=("Neither rclcpp nor rclpy was indexed."),
            )
        )


def _diagnose_domain_id(
    detected: bool,
    findings: list[Finding],
) -> int | None:
    raw = _environment_value("ROS_DOMAIN_ID")

    if raw is None:
        return 0 if detected else None

    try:
        domain_id = int(raw)
    except ValueError:
        domain_id = -1

    if not 0 <= domain_id <= 232:
        findings.append(
            Finding(
                code="ROS_DOMAIN_ID_INVALID",
                severity=FindingSeverity.ERROR,
                summary="ROS_DOMAIN_ID is invalid.",
                evidence=f"ROS_DOMAIN_ID={raw}",
                recommendation=("Use an integer from 0 through 232."),
            )
        )
        return None

    return domain_id


def _diagnose_localhost_only(
    findings: list[Finding],
) -> str | None:
    value = _environment_value("ROS_LOCALHOST_ONLY")

    if value is None:
        return None

    if value.lower() not in {
        "0",
        "1",
        "false",
        "true",
    }:
        findings.append(
            Finding(
                code=("ROS_LOCALHOST_ONLY_INVALID"),
                severity=FindingSeverity.WARNING,
                summary=("ROS_LOCALHOST_ONLY has an unrecognized value."),
                evidence=(f"ROS_LOCALHOST_ONLY={value}"),
                recommendation="Use 0 or 1.",
            )
        )

    return value


def _diagnose_dds_configuration(
    findings: list[Finding],
) -> dict[str, str]:
    configuration: dict[str, str] = {}

    for variable in (
        "CYCLONEDDS_URI",
        "FASTRTPS_DEFAULT_PROFILES_FILE",
        "FASTDDS_DEFAULT_PROFILES_FILE",
    ):
        value = _environment_value(variable)

        if value is None:
            continue

        configuration[variable] = value
        path = _dds_file_path(value)

        if path is not None and not path.is_file():
            findings.append(
                Finding(
                    code=("DDS_CONFIGURATION_MISSING"),
                    severity=FindingSeverity.ERROR,
                    summary=("A configured DDS file does not exist."),
                    evidence=f"{variable}={value}",
                    recommendation=("Correct the path or remove the stale variable."),
                )
            )

    return configuration


def _installed_ros_distributions() -> list[str]:
    try:
        entries = list(_ROS_ROOT.iterdir())
    except OSError:
        return []

    return sorted(
        entry.name for entry in entries if (entry.is_dir() and (entry / "setup.bash").is_file())
    )


def _collect_prefix_paths(
    ros_version: int | None,
) -> list[str]:
    variables = ["CMAKE_PREFIX_PATH"]

    if ros_version != 1:
        variables.extend(
            (
                "AMENT_PREFIX_PATH",
                "COLCON_PREFIX_PATH",
            )
        )

    if ros_version != 2:
        variables.append("ROS_PACKAGE_PATH")

    paths: list[str] = []

    for variable in variables:
        for raw_path in os.environ.get(
            variable,
            "",
        ).split(os.pathsep):
            path = raw_path.strip()

            if path and path not in paths:
                paths.append(path)

    return paths


def _inspection_prefixes(
    prefix_paths: list[str],
    active_distribution: str | None,
    installed_distributions: list[str],
) -> list[str]:
    prefixes = prefix_paths.copy()
    distributions = [active_distribution] if active_distribution else installed_distributions

    for distribution in distributions:
        path = str(_ROS_ROOT / distribution)

        if Path(path).is_dir() and path not in prefixes:
            prefixes.append(path)

    return prefixes


def _collect_package_names(
    prefixes: list[str],
    ros_version: int | None,
) -> set[str]:
    packages: set[str] = set()

    for prefix_text in prefixes:
        prefix = Path(prefix_text)
        ament_index = prefix / "share" / "ament_index" / "resource_index" / "packages"

        try:
            packages.update(entry.name for entry in ament_index.iterdir() if entry.is_file())
        except OSError:
            pass

        if ros_version != 2:
            share = prefix if prefix.name == "share" else prefix / "share"

            try:
                entries = list(share.iterdir())
            except OSError:
                continue

            for entry in entries:
                if not entry.is_dir():
                    continue

                if (entry / "package.xml").is_file() or (entry / "manifest.xml").is_file():
                    packages.add(entry.name)

    return packages


def _active_prefix_distributions(
    prefix_paths: list[str],
) -> list[str]:
    distributions: set[str] = set()

    for value in prefix_paths:
        parts = Path(value).parts

        for index in range(len(parts) - 2):
            if parts[index : index + 2] == ("opt", "ros"):
                distributions.add(parts[index + 2])
                break

    return sorted(distributions)


def _workspace_paths(
    prefix_paths: list[str],
) -> list[str]:
    workspaces: list[str] = []

    for value in prefix_paths:
        if value.startswith("/opt/ros/"):
            continue

        path = Path(value)

        if path.name == "share" and path.parent.name == "install":
            workspace = path.parent.parent
        elif path.name == "install":
            workspace = path.parent
        else:
            workspace = path

        text = str(workspace)

        if text not in workspaces:
            workspaces.append(text)

    return workspaces


def _package_component(
    name: str,
    candidates: tuple[str, ...],
    packages: set[str],
) -> Component:
    matches = sorted(set(candidates) & packages)

    return Component(
        category="robotics stack",
        name=name,
        status=(ComponentStatus.OK if matches else ComponentStatus.UNKNOWN),
        details={
            "installed": bool(matches),
            "detected_packages": (", ".join(matches) or None),
            "package_candidates": (", ".join(candidates)),
            "optional": True,
        },
    )


def _executable_component(
    name: str,
    executable: str,
    category: str,
) -> Component:
    path = shutil.which(executable)

    return Component(
        category=category,
        name=name,
        status=(ComponentStatus.OK if path else ComponentStatus.UNKNOWN),
        details={
            "installed": path is not None,
            "executable": path,
        },
    )


def _python_component(
    name: str,
    module: str,
    distributions: tuple[str, ...],
) -> Component:
    try:
        installed = importlib.util.find_spec(module) is not None
    except (
        ImportError,
        ModuleNotFoundError,
        ValueError,
    ):
        installed = False

    version: str | None = None

    if installed:
        for distribution in distributions:
            try:
                version = importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError:
                continue

            break

    return Component(
        category="compute library",
        name=name,
        status=(ComponentStatus.OK if installed else ComponentStatus.UNKNOWN),
        details={
            "installed": installed,
            "module": module,
            "version": version,
        },
    )


def _cuda_component() -> Component:
    executable = shutil.which("nvcc")
    toolkit_root = Path("/usr/local/cuda")
    installed = bool(executable or toolkit_root.exists())

    return Component(
        category="compute library",
        name="CUDA Toolkit",
        status=(ComponentStatus.OK if installed else ComponentStatus.UNKNOWN),
        details={
            "installed": installed,
            "executable": executable,
            "toolkit_root": (str(toolkit_root) if toolkit_root.exists() else None),
        },
    )


def _environment_status(
    findings: list[Finding],
    detected: bool,
) -> ComponentStatus:
    if any(finding.severity is FindingSeverity.ERROR for finding in findings):
        return ComponentStatus.ERROR

    if any(finding.severity is FindingSeverity.WARNING for finding in findings):
        return ComponentStatus.WARNING

    return ComponentStatus.OK if detected else ComponentStatus.UNKNOWN


def _has_problem(
    findings: list[Finding],
) -> bool:
    return any(
        finding.severity
        in {
            FindingSeverity.WARNING,
            FindingSeverity.ERROR,
        }
        for finding in findings
    )


def _is_ok(component: Component) -> bool:
    return component.status is ComponentStatus.OK


def _dds_file_path(
    value: str,
) -> Path | None:
    stripped = value.strip()

    if stripped.startswith("<"):
        return None

    if stripped.startswith("file://"):
        return Path(stripped.removeprefix("file://")).expanduser()

    if "://" in stripped:
        return None

    return Path(stripped).expanduser()


def _environment_value(
    name: str,
) -> str | None:
    value = os.environ.get(name)

    if value is None:
        return None

    cleaned = value.strip()
    return cleaned or None


def _environment_integer(
    name: str,
) -> int | None:
    value = _environment_value(name)

    if value is None:
        return None

    try:
        return int(value)
    except ValueError:
        return None
