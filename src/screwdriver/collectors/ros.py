"""Passively inspect ROS and common robotics software components."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import re
import shutil
from pathlib import Path

from screwdriver.models import (
    Component,
    ComponentStatus,
    Finding,
    FindingSeverity,
)

_ROS_ROOT = Path("/opt/ros")

_ROBOTICS_STACKS: tuple[
    tuple[str, str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...
] = (
    (
        "Navigation2",
        "navigation and localization",
        "autonomous navigation",
        ("nav2_bringup", "nav2_controller", "nav2_planner", "nav2_bt_navigator"),
        ("localization", "odometry", "TF", "sensor data"),
        ("/cmd_vel", "navigation actions", "costmaps"),
    ),
    (
        "AMCL",
        "navigation and localization",
        "localization",
        ("nav2_amcl", "amcl"),
        ("/scan", "/map", "TF", "odometry"),
        ("pose estimate", "map-to-odom TF"),
    ),
    (
        "Robot Localization",
        "navigation and localization",
        "state estimation",
        ("robot_localization",),
        ("odometry", "IMU", "GNSS"),
        ("filtered odometry", "TF"),
    ),
    (
        "SLAM Toolbox",
        "SLAM and mapping",
        "mapping",
        ("slam_toolbox",),
        ("/scan", "odometry", "TF"),
        ("/map", "pose", "map-to-odom TF"),
    ),
    (
        "Cartographer",
        "SLAM and mapping",
        "mapping",
        ("cartographer_ros", "cartographer_ros_msgs"),
        ("range data", "IMU", "odometry", "TF"),
        ("submaps", "/map", "pose"),
    ),
    (
        "RTAB-Map",
        "SLAM and mapping",
        "visual or RGB-D mapping",
        ("rtabmap_ros", "rtabmap_slam", "rtabmap_odom"),
        ("camera", "depth", "odometry", "TF"),
        ("map", "pose", "point cloud"),
    ),
    (
        "ros2_control",
        "motion and control",
        "motion control",
        ("controller_manager", "hardware_interface", "joint_state_broadcaster"),
        ("command interfaces", "hardware interfaces"),
        ("joint state", "controller state"),
    ),
    (
        "MoveIt",
        "manipulation",
        "motion planning and manipulation",
        ("moveit_ros_move_group", "moveit_core", "moveit_ros_planning"),
        ("robot description", "joint state", "planning request"),
        ("trajectory", "planning scene"),
    ),
    (
        "Camera drivers",
        "perception and AI",
        "visual perception",
        ("usb_cam", "v4l2_camera", "realsense2_camera", "zed_wrapper"),
        ("camera device",),
        ("image", "camera info", "depth"),
    ),
    (
        "LiDAR drivers",
        "perception and AI",
        "range perception",
        ("rplidar_ros", "rplidar_ros2", "urg_node", "velodyne_driver", "ouster_ros"),
        ("LiDAR device",),
        ("/scan", "point cloud"),
    ),
    (
        "Audio and speech",
        "speech and interaction",
        "speech interaction",
        ("audio_common", "audio_capture", "audio_play", "tts", "speech_to_text"),
        ("microphone", "audio stream"),
        ("transcript", "speech audio"),
    ),
    (
        "micro-ROS",
        "MCU and embedded bridges",
        "embedded controller integration",
        ("micro_ros_agent", "micro_ros_setup"),
        ("serial, UDP, or CAN transport",),
        ("ROS entities",),
    ),
    (
        "Gazebo ROS integration",
        "simulation, sandbox, and visualization",
        "simulation",
        ("ros_gz_bridge", "ros_gz_sim", "gazebo_ros"),
        ("simulation world", "robot description"),
        ("virtual sensors", "simulated hardware"),
    ),
    (
        "Isaac ROS",
        "simulation, sandbox, and visualization",
        "GPU-accelerated perception",
        ("isaac_ros_common", "isaac_ros_nitros", "isaac_ros_visual_slam"),
        ("camera or sensor data", "GPU runtime"),
        ("accelerated ROS perception outputs",),
    ),
    (
        "Webots ROS integration",
        "simulation, sandbox, and visualization",
        "simulation",
        ("webots_ros2", "webots_ros2_driver"),
        ("simulation world", "robot description"),
        ("virtual sensors", "simulated hardware"),
    ),
    (
        "RViz",
        "simulation, sandbox, and visualization",
        "visualization",
        ("rviz2", "rviz"),
        ("ROS graph data", "TF"),
        ("operator visualization",),
    ),
    (
        "Robot State Publisher",
        "simulation, sandbox, and visualization",
        "robot-state visualization",
        ("robot_state_publisher",),
        ("robot description", "joint states"),
        ("TF",),
    ),
    (
        "Teleoperation",
        "teleoperation",
        "teleoperation",
        ("teleop_twist_keyboard", "teleop_twist_joy", "joy"),
        ("keyboard, joystick, or remote command",),
        ("/cmd_vel",),
    ),
    (
        "Rosbag",
        "recording, monitoring, and telemetry",
        "recording and playback",
        ("rosbag2", "rosbag2_transport"),
        ("ROS topics",),
        ("bag storage or replayed topics",),
    ),
    (
        "Diagnostics",
        "recording, monitoring, and telemetry",
        "health monitoring",
        ("diagnostic_aggregator", "diagnostic_updater"),
        ("diagnostic status",),
        ("aggregated diagnostics",),
    ),
)

_TOOLS: tuple[tuple[str, str, str], ...] = (
    ("ROS 2 CLI", "ros2", "ROS tool"),
    ("ROS 1 master", "roscore", "ROS tool"),
    ("colcon", "colcon", "build tool"),
    ("rosdep", "rosdep", "dependency tool"),
    ("vcstool", "vcs", "source-management tool"),
    ("RViz 2", "rviz2", "visualization tool"),
    ("Gazebo", "gz", "simulator"),
    ("Webots", "webots", "simulator"),
    ("Isaac Sim", "isaac-sim", "simulation sandbox"),
    ("Docker", "docker", "container runtime"),
    ("Podman", "podman", "container runtime"),
    ("Apptainer", "apptainer", "container runtime"),
)

_PYTHON_LIBRARIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("OpenCV", "cv2", ("opencv-python", "opencv-contrib-python")),
    ("PyTorch", "torch", ("torch",)),
    ("TensorRT", "tensorrt", ("tensorrt",)),
    ("Ultralytics", "ultralytics", ("ultralytics",)),
)


def collect_robotics_software() -> tuple[list[Component], list[Finding]]:
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
                evidence=f"ROS_VERSION={os.environ.get('ROS_VERSION', '')}",
                recommendation="Open a clean shell and source the intended ROS setup file.",
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
    packages = _collect_package_names(inspection_prefixes, ros_version)
    package_versions = _collect_package_versions(inspection_prefixes, packages)
    package_configurations = _collect_package_configurations(inspection_prefixes, packages)
    active_prefix_distributions = _active_prefix_distributions(prefix_paths)
    workspaces = _workspace_paths(prefix_paths)
    rmw_implementation = _environment_value("RMW_IMPLEMENTATION")
    domain_id = _diagnose_domain_id(detected, findings)
    localhost_only = _diagnose_localhost_only(findings)
    dds_configuration = _diagnose_dds_configuration(findings)

    _diagnose_environment(
        installed_distributions=installed_distributions,
        active_distribution=active_distribution,
        ros_version=ros_version,
        environment_sourced=environment_sourced,
        ros2_path=ros2_path,
        roscore_path=roscore_path,
        invalid_prefix_paths=invalid_prefix_paths,
        active_prefix_distributions=active_prefix_distributions,
        packages=packages,
        rmw_implementation=rmw_implementation,
        findings=findings,
    )

    components: list[Component] = [
        Component(
            category="ROS environment",
            name="ROS installation and environment",
            status=_environment_status(findings, detected),
            details={
                "detected": detected,
                "environment_sourced": environment_sourced,
                "ros_version": ros_version,
                "active_distribution": active_distribution,
                "installed_distributions": ", ".join(installed_distributions) or None,
                "ros2_executable": ros2_path,
                "roscore_executable": roscore_path,
                "ros_domain_id": domain_id,
                "ros_localhost_only": localhost_only,
                "rmw_implementation": rmw_implementation,
                "indexed_package_count": len(packages),
                "prefix_paths": os.pathsep.join(prefix_paths) or None,
                "workspaces": os.pathsep.join(workspaces) or None,
                "dds_configuration": "; ".join(
                    f"{name}={value}" for name, value in dds_configuration.items()
                )
                or None,
            },
        )
    ]

    stack_components = [
        _package_component(
            name,
            category,
            capability,
            candidates,
            inputs,
            outputs,
            packages,
            package_versions,
            package_configurations,
        )
        for name, category, capability, candidates, inputs, outputs in _ROBOTICS_STACKS
    ]
    tool_components = [
        _executable_component(name, executable, category) for name, executable, category in _TOOLS
    ]
    compute_components = [
        _python_component(name, module, distributions)
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
                summary="ROS was not detected on this computer.",
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
                summary=f"[OK] {version_label}{distro_label} configuration is consistent.",
                evidence=f"Indexed packages: {len(packages)}",
            )
        )

    installed_stacks = [component.name for component in stack_components if _is_ok(component)]
    if installed_stacks:
        findings.append(
            Finding(
                code="ROBOTICS_STACKS_DETECTED",
                severity=FindingSeverity.INFO,
                summary="[OK] Detected robotics stacks: " + ", ".join(installed_stacks) + ".",
            )
        )

    installed_tools = [component.name for component in tool_components if _is_ok(component)]
    if installed_tools:
        findings.append(
            Finding(
                code="ROBOTICS_TOOLS_DETECTED",
                severity=FindingSeverity.INFO,
                summary="[OK] Available robotics tools: " + ", ".join(installed_tools) + ".",
            )
        )

    installed_compute = [component.name for component in compute_components if _is_ok(component)]
    if installed_compute:
        findings.append(
            Finding(
                code="ROBOTICS_COMPUTE_STACK_DETECTED",
                severity=FindingSeverity.INFO,
                summary="[OK] Available compute stack: " + ", ".join(installed_compute) + ".",
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
                summary="ROS is installed, but the current shell is not sourced.",
                evidence="Installed distributions: " + ", ".join(installed_distributions),
                recommendation="Run: source /opt/ros/<distribution>/setup.bash",
            )
        )

    if ros_version == 2 and not ros2_path:
        findings.append(
            Finding(
                code="ROS2_EXECUTABLE_MISSING",
                severity=FindingSeverity.ERROR,
                summary="ROS 2 is active, but the ros2 executable is unavailable.",
                evidence=f"ROS_DISTRO={active_distribution or 'unknown'}",
                recommendation="Check PATH and source the correct ROS 2 setup file.",
            )
        )

    if ros_version == 1 and not roscore_path:
        findings.append(
            Finding(
                code="ROS1_EXECUTABLE_MISSING",
                severity=FindingSeverity.ERROR,
                summary="ROS 1 is active, but the roscore executable is unavailable.",
                evidence=f"ROS_DISTRO={active_distribution or 'unknown'}",
                recommendation="Check PATH and source the correct ROS 1 setup file.",
            )
        )

    if invalid_prefix_paths:
        findings.append(
            Finding(
                code="ROS_PREFIX_PATH_INVALID",
                severity=FindingSeverity.WARNING,
                summary="ROS environment paths contain missing directories.",
                evidence=", ".join(invalid_prefix_paths),
                recommendation="Remove stale paths or source the intended workspace again.",
            )
        )

    if len(active_prefix_distributions) > 1:
        findings.append(
            Finding(
                code="ROS_DISTRIBUTIONS_MIXED",
                severity=FindingSeverity.WARNING,
                summary="Paths from multiple ROS distributions are active.",
                evidence=", ".join(active_prefix_distributions),
                recommendation="Open a clean shell and source only one ROS distribution.",
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
                summary="ROS_DISTRO identifies a distribution that could not be found.",
                evidence=f"ROS_DISTRO={active_distribution}",
                recommendation="Source an installed distribution from /opt/ros.",
            )
        )

    if rmw_implementation and rmw_implementation not in packages:
        findings.append(
            Finding(
                code="ROS_RMW_NOT_INSTALLED",
                severity=FindingSeverity.ERROR,
                summary="The selected ROS middleware package is not installed.",
                evidence=f"RMW_IMPLEMENTATION={rmw_implementation}",
                recommendation="Install that RMW package or remove the override.",
            )
        )

    if environment_sourced and not packages:
        findings.append(
            Finding(
                code="ROS_PACKAGE_INDEX_EMPTY",
                severity=FindingSeverity.ERROR,
                summary="The active ROS environment exposes no package index.",
                evidence="No packages were found in the active prefix paths.",
                recommendation="Source the correct underlay and workspace setup files.",
            )
        )
    elif ros_version == 2 and packages and not ({"rclcpp", "rclpy"} & packages):
        findings.append(
            Finding(
                code="ROS2_CLIENT_LIBRARY_MISSING",
                severity=FindingSeverity.WARNING,
                summary="No standard ROS 2 client library was found in the package index.",
                evidence="Neither rclcpp nor rclpy was indexed.",
            )
        )


def _diagnose_domain_id(detected: bool, findings: list[Finding]) -> int | None:
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
                recommendation="Use an integer from 0 through 232.",
            )
        )
        return None

    return domain_id


def _diagnose_localhost_only(findings: list[Finding]) -> str | None:
    value = _environment_value("ROS_LOCALHOST_ONLY")
    if value is None:
        return None
    if value.lower() not in {"0", "1", "false", "true"}:
        findings.append(
            Finding(
                code="ROS_LOCALHOST_ONLY_INVALID",
                severity=FindingSeverity.WARNING,
                summary="ROS_LOCALHOST_ONLY has an unrecognized value.",
                evidence=f"ROS_LOCALHOST_ONLY={value}",
                recommendation="Use 0 or 1.",
            )
        )
    return value


def _diagnose_dds_configuration(findings: list[Finding]) -> dict[str, str]:
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
                    code="DDS_CONFIGURATION_MISSING",
                    severity=FindingSeverity.ERROR,
                    summary="A configured DDS file does not exist.",
                    evidence=f"{variable}={value}",
                    recommendation="Correct the path or remove the stale variable.",
                )
            )
    return configuration


def _installed_ros_distributions() -> list[str]:
    try:
        entries = list(_ROS_ROOT.iterdir())
    except OSError:
        return []
    return sorted(
        entry.name for entry in entries if entry.is_dir() and (entry / "setup.bash").is_file()
    )


def _collect_prefix_paths(ros_version: int | None) -> list[str]:
    variables = ["CMAKE_PREFIX_PATH"]
    if ros_version != 1:
        variables.extend(("AMENT_PREFIX_PATH", "COLCON_PREFIX_PATH"))
    if ros_version != 2:
        variables.append("ROS_PACKAGE_PATH")

    paths: list[str] = []
    for variable in variables:
        for raw_path in os.environ.get(variable, "").split(os.pathsep):
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


def _collect_package_names(prefixes: list[str], ros_version: int | None) -> set[str]:
    packages: set[str] = set()
    for prefix_text in prefixes:
        prefix = Path(prefix_text)
        ament_index = prefix / "share/ament_index/resource_index/packages"
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


def _collect_package_versions(prefixes: list[str], packages: set[str]) -> dict[str, str]:
    """Read package.xml versions for only the stack packages Screwdriver recognizes."""

    candidates = {
        candidate
        for _, _, _, stack_candidates, _, _ in _ROBOTICS_STACKS
        for candidate in stack_candidates
    }
    versions: dict[str, str] = {}
    for package in sorted(packages & candidates):
        for prefix_text in prefixes:
            manifest = Path(prefix_text) / "share" / package / "package.xml"
            try:
                content = manifest.read_text(encoding="utf-8", errors="replace")[:65536]
            except OSError:
                continue
            match = re.search(r"<version(?:\s[^>]*)?>([^<]+)</version>", content)
            if match:
                versions[package] = match.group(1).strip()
                break
    return versions


def _collect_package_configurations(
    prefixes: list[str], packages: set[str]
) -> dict[str, list[str]]:
    """Find bounded launch/config evidence without reading or changing configuration."""

    candidates = {
        candidate
        for _, _, _, stack_candidates, _, _ in _ROBOTICS_STACKS
        for candidate in stack_candidates
    }
    configurations: dict[str, list[str]] = {}
    for package in sorted(packages & candidates):
        found: list[str] = []
        for prefix_text in prefixes:
            package_root = Path(prefix_text) / "share" / package
            for directory_name in ("launch", "config", "params"):
                directory = package_root / directory_name
                try:
                    paths = sorted(path for path in directory.rglob("*") if path.is_file())
                except OSError:
                    continue
                for path in paths:
                    if path.suffix.lower() in {".py", ".xml", ".yaml", ".yml", ".json"}:
                        found.append(str(path))
                    if len(found) >= 12:
                        break
                if len(found) >= 12:
                    break
            if len(found) >= 12:
                break
        if found:
            configurations[package] = found
    return configurations


def _active_prefix_distributions(prefix_paths: list[str]) -> list[str]:
    distributions: set[str] = set()
    for value in prefix_paths:
        parts = Path(value).parts
        for index in range(len(parts) - 2):
            if parts[index : index + 2] == ("opt", "ros"):
                distributions.add(parts[index + 2])
                break
    return sorted(distributions)


def _workspace_paths(prefix_paths: list[str]) -> list[str]:
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
    stack_category: str,
    capability: str,
    candidates: tuple[str, ...],
    required_inputs: tuple[str, ...],
    expected_outputs: tuple[str, ...],
    packages: set[str],
    package_versions: dict[str, str],
    package_configurations: dict[str, list[str]],
) -> Component:
    matches = sorted(set(candidates) & packages)
    versions = [
        f"{package} {package_versions[package]}"
        for package in matches
        if package in package_versions
    ]
    configuration_sources = [
        path for package in matches for path in package_configurations.get(package, [])
    ]
    return Component(
        category="robotics software stack",
        name=name,
        status=ComponentStatus.OK if matches else ComponentStatus.UNKNOWN,
        details={
            "installed": bool(matches),
            "configured": True if configuration_sources else None,
            "running": False,
            "connected": None,
            "integrated": None,
            "state": "INSTALLED_NOT_EVALUATED" if matches else "NOT_INSTALLED",
            "stack_category": stack_category,
            "capability": capability,
            "required_inputs": ", ".join(required_inputs),
            "expected_outputs": ", ".join(expected_outputs),
            "runtime_owner": None,
            "version": ", ".join(versions) or None,
            "configuration_source": ", ".join(configuration_sources) or None,
            "detected_packages": ", ".join(matches) or None,
            "package_candidates": ", ".join(candidates),
            "optional": True,
        },
    )


def _executable_component(name: str, executable: str, category: str) -> Component:
    path = shutil.which(executable)
    return Component(
        category=category,
        name=name,
        status=ComponentStatus.OK if path else ComponentStatus.UNKNOWN,
        details={"installed": path is not None, "executable": path},
    )


def _python_component(
    name: str,
    module: str,
    distributions: tuple[str, ...],
) -> Component:
    try:
        installed = importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
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
        status=ComponentStatus.OK if installed else ComponentStatus.UNKNOWN,
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
        status=ComponentStatus.OK if installed else ComponentStatus.UNKNOWN,
        details={
            "installed": installed,
            "executable": executable,
            "toolkit_root": str(toolkit_root) if toolkit_root.exists() else None,
        },
    )


def _environment_status(findings: list[Finding], detected: bool) -> ComponentStatus:
    if any(finding.severity is FindingSeverity.ERROR for finding in findings):
        return ComponentStatus.ERROR
    if any(finding.severity is FindingSeverity.WARNING for finding in findings):
        return ComponentStatus.WARNING
    return ComponentStatus.OK if detected else ComponentStatus.UNKNOWN


def _has_problem(findings: list[Finding]) -> bool:
    return any(
        finding.severity in {FindingSeverity.WARNING, FindingSeverity.ERROR} for finding in findings
    )


def _is_ok(component: Component) -> bool:
    return component.status is ComponentStatus.OK


def _dds_file_path(value: str) -> Path | None:
    stripped = value.strip()
    if stripped.startswith("<"):
        return None
    if stripped.startswith("file://"):
        return Path(stripped.removeprefix("file://")).expanduser()
    if "://" in stripped:
        return None
    return Path(stripped).expanduser()


def _environment_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _environment_integer(name: str) -> int | None:
    value = _environment_value(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
