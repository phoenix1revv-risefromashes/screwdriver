"""Build passive runtime inventories for a Linux robotics computer."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from screwdriver.models import (
    Component,
    ComponentStatus,
    Finding,
    FindingSeverity,
    SerialDevice,
    USBDevice,
)

_COMMAND_TIMEOUT_SECONDS = 6.0
_DETAIL_TIMEOUT_SECONDS = 2.0
_TOTAL_BUDGET_SECONDS = 45.0
_MAX_NODE_DETAILS = 24
_MAX_DEVICE_TOPIC_DETAILS = 40
_MAX_PARAMETER_PROBES = 16

_ROS_ENVIRONMENT_VARIABLES = (
    "ROS_VERSION",
    "ROS_DISTRO",
    "ROS_DOMAIN_ID",
    "ROS_LOCALHOST_ONLY",
    "RMW_IMPLEMENTATION",
    "AMENT_PREFIX_PATH",
    "COLCON_PREFIX_PATH",
    "CMAKE_PREFIX_PATH",
    "PYTHONPATH",
    "LD_LIBRARY_PATH",
    "PATH",
    "CYCLONEDDS_URI",
    "FASTRTPS_DEFAULT_PROFILES_FILE",
    "FASTDDS_DEFAULT_PROFILES_FILE",
)

_HARDWARE_PARAMETER_TOKENS = (
    "port",
    "device",
    "serial",
    "baud",
    "frame_id",
    "sensor",
    "model",
    "interface",
    "camera_name",
    "audio",
    "alsa",
    "card",
    "sink",
    "source",
    "speaker",
    "display",
    "screen",
    "framebuffer",
    "drm",
    "gpio",
    "pwm",
    "can",
    "i2c",
    "spi",
)

_SENSOR_MESSAGE_TYPES = {
    "sensor_msgs/msg/Image": "camera",
    "sensor_msgs/msg/CompressedImage": "camera",
    "sensor_msgs/msg/CameraInfo": "camera",
    "sensor_msgs/msg/LaserScan": "lidar",
    "sensor_msgs/msg/PointCloud2": "point-cloud sensor",
    "sensor_msgs/msg/Imu": "IMU",
    "sensor_msgs/msg/NavSatFix": "GPS/GNSS",
    "sensor_msgs/msg/Range": "range sensor",
    "sensor_msgs/msg/JointState": "joint-state feedback",
    "sensor_msgs/msg/MagneticField": "magnetometer",
    "sensor_msgs/msg/FluidPressure": "pressure sensor",
    "sensor_msgs/msg/Temperature": "temperature sensor",
    "sensor_msgs/msg/RelativeHumidity": "humidity sensor",
    "sensor_msgs/msg/Illuminance": "light sensor",
    "sensor_msgs/msg/BatteryState": "battery monitor",
    "geometry_msgs/msg/WrenchStamped": "force/torque sensor",
}

_ACTUATOR_MESSAGE_TYPES = {
    "geometry_msgs/msg/Twist",
    "geometry_msgs/msg/TwistStamped",
    "trajectory_msgs/msg/JointTrajectory",
    "std_msgs/msg/Float64",
    "std_msgs/msg/Float64MultiArray",
    "ackermann_msgs/msg/AckermannDrive",
    "ackermann_msgs/msg/AckermannDriveStamped",
}

_ACTUATOR_ACTION_TYPES = {
    "control_msgs/action/FollowJointTrajectory": "joint/motor controller",
    "control_msgs/action/GripperCommand": "gripper",
    "nav2_msgs/action/NavigateToPose": "mobile base drive",
    "nav2_msgs/action/FollowPath": "mobile base drive",
}

_AUDIO_MESSAGE_TYPES = {
    "audio_common_msgs/msg/AudioData",
    "audio_common_msgs/msg/AudioDataStamped",
    "audio_msgs/msg/Audio",
    "audio_msgs/msg/AudioInfo",
}

_DEVICE_TOPIC_TOKENS = (
    "audio",
    "speaker",
    "sound",
    "tts",
    "voice",
    "display",
    "screen",
    "hmi",
    "face",
    "lcd",
    "oled",
    "motor",
    "servo",
    "gripper",
    "drive",
    "wheel",
    "joint",
    "trajectory",
    "cmd_vel",
    "battery",
    "power",
    "bms",
    "gpio",
    "pwm",
    "relay",
    "led",
    "light",
    "can",
    "ethercat",
    "modbus",
    "serial",
    "uart",
    "camera",
    "image",
    "scan",
    "lidar",
    "imu",
    "gps",
    "gnss",
    "radar",
    "range",
)

_RUNNING_HINTS = {
    "Navigation2": ("nav2", "planner_server", "controller_server", "bt_navigator"),
    "AMCL": ("amcl",),
    "Robot Localization": ("ekf_node", "ukf_node", "navsat_transform"),
    "MoveIt": ("move_group", "moveit"),
    "ros2_control": ("controller_manager", "ros2_control_node"),
    "SLAM Toolbox": ("slam_toolbox",),
    "Cartographer": ("cartographer",),
    "RTAB-Map": ("rtabmap",),
    "RViz": ("rviz", "rviz2"),
    "Robot State Publisher": ("robot_state_publisher",),
    "Gazebo ROS integration": ("gazebo", "gzserver", "gz_sim", "ros_gz"),
    "Isaac ROS": ("isaac_ros", "nitros"),
    "Webots ROS integration": ("webots",),
    "Camera drivers": ("camera", "usb_cam", "v4l2", "realsense"),
    "LiDAR drivers": ("lidar", "laser", "rplidar", "velodyne", "ouster"),
    "micro-ROS": ("micro_ros",),
    "Audio and speech": ("audio_capture", "audio_play", "speech", "whisper", "tts"),
    "Teleoperation": ("teleop", "joy_node"),
    "Rosbag": ("ros2 bag", "rosbag2"),
    "Diagnostics": ("diagnostic_aggregator", "diagnostic_updater"),
    "Docker": ("dockerd", "docker"),
    "Podman": ("podman",),
    "Apptainer": ("apptainer", "singularity"),
    "Webots": ("webots",),
    "Isaac Sim": ("isaac-sim", "isaac sim"),
}

_STACK_ENDPOINT_PROFILES: dict[str, dict[str, tuple[str, ...]]] = {
    "Navigation2": {
        "inputs": ("scan", "map", "odom"),
        "outputs": ("cmd_vel", "navigate_to_pose", "follow_path"),
    },
    "AMCL": {
        "inputs": ("scan", "map", "odom"),
        "outputs": ("amcl_pose", "particlecloud"),
    },
    "Robot Localization": {
        "inputs": ("imu", "odom", "gps", "gnss"),
        "outputs": ("odometry/filtered",),
    },
    "SLAM Toolbox": {
        "inputs": ("scan", "odom"),
        "outputs": ("map", "pose"),
    },
    "Cartographer": {
        "inputs": ("scan", "points", "imu", "odom"),
        "outputs": ("map", "submap"),
    },
    "RTAB-Map": {
        "inputs": ("image", "depth", "odom"),
        "outputs": ("map", "cloud", "pose"),
    },
    "ros2_control": {
        "inputs": ("cmd_vel", "joint_trajectory"),
        "outputs": ("joint_states", "controller_state"),
    },
    "MoveIt": {
        "inputs": ("joint_states", "planning_scene"),
        "outputs": ("follow_joint_trajectory", "display_planned_path"),
    },
}


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Represent one bounded command without raising collection errors."""

    state: str
    stdout: str = ""
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.state == "ok"


@dataclass(slots=True)
class RuntimeInventory:
    """Hold every inventory produced by passive runtime inspection."""

    software_stacks: list[Component] = field(default_factory=list)
    sensors: list[Component] = field(default_factory=list)
    actuators: list[Component] = field(default_factory=list)
    devices: list[Component] = field(default_factory=list)
    ros_runtime: list[Component] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


@dataclass(slots=True)
class GraphDiscovery:
    """Hold one ROS graph probe and the environment that discovered it."""

    executable: str
    environment: dict[str, str]
    results: dict[str, CommandResult]
    nodes: list[str]
    topics: list[tuple[str, str]]
    services: list[tuple[str, str]]
    actions: list[tuple[str, str]]
    mode: str
    environment_recovered: bool


def collect_runtime_inventory(
    static_components: list[Component],
    usb_devices: list[USBDevice],
    serial_devices: list[SerialDevice],
) -> RuntimeInventory:
    """Collect live software and ROS metadata without opening or driving hardware."""

    process_text = _running_process_text()
    sensors = _physical_sensor_inventory(usb_devices, serial_devices)
    actuators = _physical_actuator_inventory(usb_devices, serial_devices)
    deadline = time.monotonic() + _TOTAL_BUDGET_SECONDS
    environments = _ros_environment_candidates()
    discovery = _discover_ros_graph(environments, deadline)

    if discovery is None:
        ros_installed = _ros_installation_detected(static_components)
        runtime_state = "UNAVAILABLE" if ros_installed else "NOT_INSTALLED"
        finding_code = "ROS_RUNTIME_UNAVAILABLE" if ros_installed else "ROS_RUNTIME_NOT_INSTALLED"
        finding_summary = (
            "Live ROS 2 inspection was skipped because ros2 is unavailable in this shell."
            if ros_installed
            else "Live ROS 2 inspection was skipped because ROS 2 was not detected."
        )
        return RuntimeInventory(
            software_stacks=_software_inventory(
                static_components,
                process_text=process_text,
                ros_graph_running=False,
            ),
            sensors=sensors,
            actuators=actuators,
            devices=[],
            ros_runtime=[_ros_summary(runtime_state)],
            findings=[
                Finding(
                    code=finding_code,
                    severity=FindingSeverity.INFO,
                    summary=finding_summary,
                    recommendation=(
                        "Source the ROS 2 environment before inspection when live graph "
                        "inventory is required."
                    ),
                )
            ],
        )

    ros2_path = discovery.executable
    environment = discovery.environment
    results = discovery.results
    nodes = discovery.nodes
    topics = discovery.topics
    services = discovery.services
    actions = discovery.actions
    publishers: dict[str, list[str]] = {}
    subscribers: dict[str, list[str]] = {}
    node_results: dict[str, CommandResult] = {}
    node_details: dict[str, dict[str, list[str]] | None] = {}

    for node in nodes[:_MAX_NODE_DETAILS]:
        result = _run_ros2(
            ros2_path,
            ("node", "info", node),
            deadline=deadline,
            timeout=_DETAIL_TIMEOUT_SECONDS,
            environment=environment,
            no_daemon=discovery.mode != "daemon",
        )
        details = _parse_node_info(result.stdout) if result.succeeded else None
        node_results[node] = result
        node_details[node] = details

        if details is not None:
            for topic in details["publishers"]:
                publishers.setdefault(topic, []).append(node)
            for topic in details["subscribers"]:
                subscribers.setdefault(topic, []).append(node)

    device_topics = [
        (topic, message_type)
        for topic, message_type in topics
        if _is_device_relevant_topic(topic, message_type)
    ]
    for topic, _message_type in device_topics[:_MAX_DEVICE_TOPIC_DETAILS]:
        result = _run_ros2(
            ros2_path,
            ("topic", "info", topic, "--verbose"),
            deadline=deadline,
            timeout=_DETAIL_TIMEOUT_SECONDS,
            environment=environment,
            no_daemon=discovery.mode != "daemon",
        )
        if result.succeeded:
            topic_publishers, topic_subscribers = _parse_topic_info(result.stdout)
            if topic_publishers:
                publishers[topic] = topic_publishers
            if topic_subscribers:
                subscribers[topic] = topic_subscribers

    hardware_nodes = _hardware_relevant_nodes(
        device_topics,
        publishers,
        subscribers,
        nodes,
    )
    node_parameters = _probe_hardware_parameters(
        ros2_path,
        hardware_nodes,
        environment=environment,
        deadline=deadline,
    )
    node_components = [
        _node_component(
            node,
            node_results.get(node, CommandResult("not_probed")),
            node_details.get(node),
            node_parameters.get(node),
        )
        for node in nodes
    ]

    graph_state, graph_status = _graph_state(results, nodes, topics)
    graph_running = graph_state == "RUNNING"
    ros_runtime = [
        _ros_summary(
            graph_state,
            status=graph_status,
            nodes=len(nodes),
            topics=len(topics),
            services=len(services),
            actions=len(actions),
            detailed_nodes=min(len(nodes), _MAX_NODE_DETAILS),
            environment=environment,
            discovery_mode=discovery.mode,
            environment_recovered=discovery.environment_recovered,
        ),
        *node_components,
        *_endpoint_components("ROS topic", topics),
        *_endpoint_components("ROS service", services),
        *_endpoint_components("ROS action", actions),
    ]

    controller_components: list[Component] = []
    controller_hardware: list[Component] = []
    if any(node.rstrip("/").endswith("controller_manager") for node in nodes):
        controller_result = _run_ros2(
            ros2_path,
            ("control", "list_controllers"),
            deadline=deadline,
            environment=environment,
        )
        interface_result = _run_ros2(
            ros2_path,
            ("control", "list_hardware_interfaces"),
            deadline=deadline,
            environment=environment,
        )
        hardware_result = _run_ros2(
            ros2_path,
            ("control", "list_hardware_components", "--verbose"),
            deadline=deadline,
            environment=environment,
        )
        if controller_result.succeeded:
            controller_components = _controller_components(controller_result.stdout)
        if hardware_result.succeeded:
            controller_hardware = _controller_hardware_components(hardware_result.stdout)
        if interface_result.succeeded and interface_result.stdout.strip():
            ros_runtime.append(
                Component(
                    category="ros2_control hardware",
                    name="Hardware interfaces",
                    status=ComponentStatus.OK,
                    details={
                        "state": "AVAILABLE",
                        "interfaces": _compact(interface_result.stdout),
                        "evidence": "ros2 control list_hardware_interfaces",
                    },
                )
            )

    ros_sensors = _ros_sensor_inventory(
        topics,
        publishers,
        subscribers,
        node_parameters,
    )
    physical_usage = _ros_physical_sensor_usage(
        ros_sensors,
        usb_devices,
        serial_devices,
        node_parameters,
        process_text,
    )
    sensors = [*physical_usage, *sensors, *ros_sensors]
    ros_actuators = _ros_actuator_inventory(
        topics,
        actions,
        publishers,
        subscribers,
        controller_components,
    )
    actuators.extend(ros_actuators)
    actuators.extend(controller_hardware)
    _correlate_physical_and_ros(sensors)
    _correlate_physical_and_ros(actuators)
    devices = _ros_device_inventory(
        nodes=nodes,
        topics=topics,
        actions=actions,
        node_details=node_details,
        node_parameters=node_parameters,
        sensors=ros_sensors,
        actuators=ros_actuators,
        controller_hardware=controller_hardware,
    )
    _correlate_ros_devices_with_physical(devices, usb_devices, serial_devices)

    findings = _command_findings(results)
    if discovery.mode != "daemon":
        findings.append(
            Finding(
                code="ROS_RUNTIME_DISCOVERY_RECOVERED",
                severity=FindingSeverity.INFO,
                summary="[OK] ROS 2 graph discovery recovered using a direct DDS probe.",
                evidence=_environment_evidence(environment),
            )
        )
    if discovery.environment_recovered:
        findings.append(
            Finding(
                code="ROS_RUNTIME_ENVIRONMENT_RECOVERED",
                severity=FindingSeverity.INFO,
                summary=(
                    "[OK] Live ROS 2 graph was found using the environment of an "
                    "already-running ROS process."
                ),
                evidence=_environment_evidence(environment),
                recommendation=(
                    "Source the same ROS underlay/workspace and domain settings before "
                    "running Screwdriver for deterministic discovery."
                ),
            )
        )
    if graph_running:
        findings.append(
            Finding(
                code="ROS_RUNTIME_DISCOVERED",
                severity=FindingSeverity.INFO,
                summary=(
                    f"[OK] Live ROS 2 graph: {len(nodes)} nodes, {len(topics)} topics, "
                    f"{len(services)} services, and {len(actions)} actions."
                ),
            )
        )
    elif graph_state == "NOT_RUNNING":
        findings.append(
            Finding(
                code="ROS_RUNTIME_NOT_RUNNING",
                severity=FindingSeverity.INFO,
                summary="ROS 2 is available, but no active graph was discovered.",
            )
        )

    return RuntimeInventory(
        software_stacks=_software_inventory(
            static_components,
            process_text=process_text,
            ros_graph_running=graph_running,
            nodes=nodes,
            topics=topics,
            actions=actions,
            hardware_endpoints=_hardware_endpoints(devices),
        ),
        sensors=_deduplicate(sensors),
        actuators=_deduplicate(actuators),
        devices=_deduplicate(devices),
        ros_runtime=_deduplicate(ros_runtime),
        findings=findings,
    )


def _discover_ros_graph(
    environments: list[dict[str, str]],
    deadline: float,
) -> GraphDiscovery | None:
    commands = {
        "nodes": ("node", "list"),
        "topics": ("topic", "list", "-t"),
        "services": ("service", "list", "-t"),
        "actions": ("action", "list", "-t"),
    }
    best: GraphDiscovery | None = None
    best_score = -1

    for environment_index, environment in enumerate(environments):
        executable = _ros2_executable(environment, prefer_shutil=environment_index == 0)
        if executable is None:
            continue

        for no_daemon in (False, True):
            results = {
                name: _run_ros2(
                    executable,
                    arguments,
                    deadline=deadline,
                    environment=environment,
                    no_daemon=no_daemon,
                )
                for name, arguments in commands.items()
            }
            nodes = _lines(results["nodes"].stdout) if results["nodes"].succeeded else []
            topics = (
                _parse_typed_names(results["topics"].stdout) if results["topics"].succeeded else []
            )
            services = (
                _parse_typed_names(results["services"].stdout)
                if results["services"].succeeded
                else []
            )
            actions = (
                _parse_typed_names(results["actions"].stdout)
                if results["actions"].succeeded
                else []
            )
            discovery = GraphDiscovery(
                executable=executable,
                environment=environment,
                results=results,
                nodes=nodes,
                topics=topics,
                services=services,
                actions=actions,
                mode="direct DDS" if no_daemon else "daemon",
                environment_recovered=environment_index > 0,
            )
            score = (
                (1000 if nodes or topics else 0)
                + len(nodes)
                + len(topics)
                + sum(result.succeeded for result in results.values())
            )
            if score > best_score:
                best = discovery
                best_score = score
            if nodes or topics:
                return discovery

            if time.monotonic() >= deadline:
                return best

    return best


def _run_ros2(
    executable: str,
    arguments: tuple[str, ...],
    *,
    deadline: float,
    timeout: float = _COMMAND_TIMEOUT_SECONDS,
    environment: dict[str, str] | None = None,
    no_daemon: bool = False,
) -> CommandResult:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return CommandResult("budget_exhausted", error="Runtime inspection budget exhausted.")

    bounded_timeout = max(0.05, min(timeout, remaining))
    command = [executable, *arguments]
    if no_daemon and arguments[0] in {"node", "topic", "service", "action"}:
        command.append("--no-daemon")
    command_environment = (environment or os.environ).copy()
    command_environment["PYTHONUNBUFFERED"] = "1"

    try:
        completed = subprocess.run(
            command,
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=bounded_timeout,
            env=command_environment,
        )
    except subprocess.TimeoutExpired as exception:
        return CommandResult(
            "timeout",
            stdout=_decode_output(exception.stdout),
            error=f"Timed out after {bounded_timeout:.2f} seconds.",
        )
    except (OSError, UnicodeError) as exception:
        return CommandResult("unavailable", error=str(exception))

    if completed.returncode != 0:
        return CommandResult(
            "failed",
            stdout=completed.stdout,
            error=completed.stderr.strip() or f"Exit status {completed.returncode}.",
        )
    return CommandResult("ok", stdout=completed.stdout)


def _ros_environment_candidates() -> list[dict[str, str]]:
    """Return current and passively recovered ROS process environments."""

    current = os.environ.copy()
    candidates = [current]
    seen = {_environment_key(current)}

    try:
        processes = psutil.process_iter(["name", "cmdline"])
    except (psutil.Error, OSError):
        return candidates

    for process in processes:
        try:
            command = " ".join(str(value) for value in (process.info.get("cmdline") or []))
            name = str(process.info.get("name") or "")
            environment = process.environ()
        except (psutil.Error, OSError, TypeError, AttributeError):
            continue

        looks_like_ros = bool(
            environment.get("ROS_VERSION") == "2"
            or environment.get("ROS_DISTRO")
            or "ros2" in command.lower()
            or any(token in name.lower() for token in ("component_container", "rosout"))
        )
        if not looks_like_ros:
            continue

        recovered = current.copy()
        for variable in _ROS_ENVIRONMENT_VARIABLES:
            value = environment.get(variable)
            if value:
                recovered[variable] = value

        key = _environment_key(recovered)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(recovered)

        if len(candidates) >= 4:
            break

    return candidates


def _environment_key(environment: dict[str, str]) -> tuple[str, ...]:
    return tuple(environment.get(variable, "") for variable in _ROS_ENVIRONMENT_VARIABLES)


def _ros2_executable(
    environment: dict[str, str],
    *,
    prefer_shutil: bool,
) -> str | None:
    if prefer_shutil:
        executable = shutil.which("ros2")
        if executable:
            return executable

    for directory in environment.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = os.path.join(directory, "ros2")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _environment_evidence(environment: dict[str, str]) -> str:
    return ", ".join(
        (
            f"ROS_DISTRO={environment.get('ROS_DISTRO', 'unknown')}",
            f"ROS_DOMAIN_ID={environment.get('ROS_DOMAIN_ID', '0')}",
            f"RMW_IMPLEMENTATION={environment.get('RMW_IMPLEMENTATION', 'default')}",
        )
    )


def _graph_state(
    results: dict[str, CommandResult],
    nodes: list[str],
    topics: list[tuple[str, str]],
) -> tuple[str, ComponentStatus]:
    if nodes or topics:
        return "RUNNING", ComponentStatus.OK
    if results["nodes"].succeeded and results["topics"].succeeded:
        return "NOT_RUNNING", ComponentStatus.UNKNOWN
    if any(result.state in {"timeout", "budget_exhausted"} for result in results.values()):
        return "UNAVAILABLE", ComponentStatus.WARNING
    return "UNAVAILABLE", ComponentStatus.UNKNOWN


def _ros_summary(
    state: str,
    *,
    status: ComponentStatus = ComponentStatus.UNKNOWN,
    nodes: int = 0,
    topics: int = 0,
    services: int = 0,
    actions: int = 0,
    detailed_nodes: int = 0,
    environment: dict[str, str] | None = None,
    discovery_mode: str = "unavailable",
    environment_recovered: bool = False,
) -> Component:
    active_environment = environment or os.environ
    return Component(
        category="ROS runtime",
        name="ROS 2 graph",
        status=status,
        details={
            "state": state,
            "nodes": nodes,
            "topics": topics,
            "services": services,
            "actions": actions,
            "detailed_nodes": detailed_nodes,
            "domain_id": active_environment.get("ROS_DOMAIN_ID", "0"),
            "middleware": active_environment.get("RMW_IMPLEMENTATION", "default"),
            "ros_distro": active_environment.get("ROS_DISTRO"),
            "discovery_mode": discovery_mode,
            "environment_recovered": environment_recovered,
            "probe": "metadata only; no publications or hardware commands",
        },
    )


def _node_component(
    node: str,
    result: CommandResult,
    details: dict[str, list[str]] | None,
    hardware_parameters: dict[str, str] | None = None,
) -> Component:
    if details is None:
        return Component(
            category="ROS node",
            name=node,
            status=ComponentStatus.WARNING
            if result.state == "timeout"
            else ComponentStatus.UNKNOWN,
            details={
                "state": "DISCOVERED",
                "detail_probe": result.state,
                "hardware_parameters": _format_parameters(hardware_parameters),
            },
        )
    return Component(
        category="ROS node",
        name=node,
        status=ComponentStatus.OK,
        details={
            "state": "RUNNING",
            "publishers": ", ".join(details["publishers"]) or None,
            "subscribers": ", ".join(details["subscribers"]) or None,
            "services": ", ".join(details["services"]) or None,
            "actions": ", ".join(details["actions"]) or None,
            "hardware_parameters": _format_parameters(hardware_parameters),
            "evidence": "ros2 node info",
        },
    )


def _endpoint_components(
    category: str,
    endpoints: list[tuple[str, str]],
) -> list[Component]:
    return [
        Component(
            category=category,
            name=name,
            status=ComponentStatus.OK,
            details={
                "state": "AVAILABLE",
                "type": endpoint_type,
                "transport": "DDS request/reply" if category == "ROS service" else "DDS",
            },
        )
        for name, endpoint_type in endpoints
    ]


def _ros_sensor_inventory(
    topics: list[tuple[str, str]],
    publishers: dict[str, list[str]],
    subscribers: dict[str, list[str]],
    node_parameters: dict[str, dict[str, str]],
) -> list[Component]:
    inventory: list[Component] = []
    for topic, message_type in topics:
        kind = _sensor_kind(topic, message_type)
        if kind is None:
            continue
        publishing_nodes = publishers.get(topic, [])
        display_facing_image = bool(
            kind == "camera"
            and not publishing_nodes
            and any(
                token in topic.lower() for token in ("display", "screen", "face", "hmi", "render")
            )
        )
        if display_facing_image:
            continue
        hardware_parameters = _combined_parameters(publishing_nodes, node_parameters)
        inventory.append(
            Component(
                category="sensor",
                name=f"{kind} — {topic}",
                status=ComponentStatus.OK,
                details={
                    "kind": kind,
                    "source": "ROS 2 runtime",
                    "bus": "DDS",
                    "channel": topic,
                    "message_type": message_type,
                    "publishers": ", ".join(publishing_nodes) or "UNKNOWN",
                    "subscribers": ", ".join(subscribers.get(topic, [])) or "UNKNOWN",
                    "hardware_node": ", ".join(publishing_nodes) or None,
                    "hardware_parameters": _format_parameters(hardware_parameters),
                    "configured_device": _configured_device(hardware_parameters),
                    "state": "AVAILABLE",
                    "health": "ENDPOINT_AVAILABLE_DATA_NOT_SAMPLED",
                    "confidence": "VERIFIED",
                },
            )
        )
    return inventory


def _ros_actuator_inventory(
    topics: list[tuple[str, str]],
    actions: list[tuple[str, str]],
    publishers: dict[str, list[str]],
    subscribers: dict[str, list[str]],
    controllers: list[Component],
) -> list[Component]:
    inventory: list[Component] = []
    for topic, message_type in topics:
        if not _is_actuator_command(topic, message_type):
            continue
        kind = _actuator_kind(topic, message_type)
        inventory.append(
            Component(
                category="actuator/control",
                name=f"{kind} — {topic}",
                status=ComponentStatus.OK,
                details={
                    "kind": kind,
                    "source": "ROS 2 runtime",
                    "bus": "DDS",
                    "channel": topic,
                    "message_type": message_type,
                    "publishers": ", ".join(publishers.get(topic, [])) or "UNKNOWN",
                    "subscribers": ", ".join(subscribers.get(topic, [])) or "UNKNOWN",
                    "state": "AVAILABLE",
                    "health": "COMMAND_ENDPOINT_AVAILABLE_MOTION_NOT_TESTED",
                    "confidence": "VERIFIED",
                },
            )
        )

    for action, action_type in actions:
        action_kind = _ACTUATOR_ACTION_TYPES.get(action_type)
        if action_kind is None:
            continue
        inventory.append(
            Component(
                category="actuator/control",
                name=f"{action_kind} — {action}",
                status=ComponentStatus.OK,
                details={
                    "kind": action_kind,
                    "source": "ROS 2 runtime",
                    "bus": "DDS action",
                    "channel": action,
                    "action_type": action_type,
                    "state": "AVAILABLE",
                    "health": "ACTION_AVAILABLE_MOTION_NOT_TESTED",
                    "confidence": "VERIFIED",
                },
            )
        )
    return [*inventory, *controllers]


def _ros_device_inventory(
    *,
    nodes: list[str],
    topics: list[tuple[str, str]],
    actions: list[tuple[str, str]],
    node_details: dict[str, dict[str, list[str]] | None],
    node_parameters: dict[str, dict[str, str]],
    sensors: list[Component],
    actuators: list[Component],
    controller_hardware: list[Component],
) -> list[Component]:
    """Build a node-centric inventory of every evidenced ROS-facing device class."""

    topic_types = dict(topics)
    inventory: list[Component] = []
    represented_sensor_topics: set[str] = set()
    represented_actuator_topics: set[str] = set()

    for node in nodes:
        details = node_details.get(node) or {
            "publishers": [],
            "subscribers": [],
            "services": [],
            "actions": [],
        }
        published_topics = details.get("publishers", [])
        subscribed_topics = details.get("subscribers", [])
        parameters = node_parameters.get(node, {})
        roles = _ros_device_roles(
            node,
            published_topics,
            subscribed_topics,
            topic_types,
            parameters,
        )

        for device_class, kind, direction, confidence, evidence in roles:
            role_topics = _topics_for_device_role(
                kind,
                direction,
                published_topics,
                subscribed_topics,
                topic_types,
            )
            if device_class == "sensor / input":
                represented_sensor_topics.update(role_topics)
            if device_class == "actuator / output":
                represented_actuator_topics.update(role_topics)

            message_types = sorted(
                {topic_types[topic] for topic in role_topics if topic in topic_types}
            )
            inventory.append(
                Component(
                    category="ROS device",
                    name=f"{kind} — {node}",
                    status=ComponentStatus.OK,
                    details={
                        "device_class": device_class,
                        "kind": kind,
                        "direction": direction,
                        "source": "ROS 2 runtime",
                        "bus": "DDS",
                        "channel": ", ".join(role_topics) or node,
                        "ros_node": node,
                        "topics": ", ".join(role_topics) or None,
                        "published_topics": ", ".join(published_topics) or None,
                        "subscribed_topics": ", ".join(subscribed_topics) or None,
                        "services": ", ".join(details.get("services", [])) or None,
                        "actions": ", ".join(details.get("actions", [])) or None,
                        "message_types": ", ".join(message_types) or None,
                        "hardware_parameters": _format_parameters(parameters),
                        "configured_device": _configured_device(parameters),
                        "state": "ROS_ROLE_ACTIVE",
                        "ownership": "ROLE_ONLY",
                        "health": "GRAPH_CONNECTION_VERIFIED_HARDWARE_NOT_EXERCISED",
                        "confidence": confidence,
                        "evidence": evidence,
                    },
                )
            )

    for sensor in sensors:
        channel = str(sensor.details.get("channel") or "")
        if channel and channel not in represented_sensor_topics:
            inventory.append(
                _legacy_inventory_as_ros_device(
                    sensor,
                    device_class="sensor / input",
                    direction="input",
                )
            )

    for actuator in actuators:
        channel = str(actuator.details.get("channel") or "")
        is_action = bool(actuator.details.get("action_type"))
        is_controller = actuator.details.get("kind") == "ros2_control controller"
        if is_action or is_controller or (channel and channel not in represented_actuator_topics):
            inventory.append(
                _legacy_inventory_as_ros_device(
                    actuator,
                    device_class="actuator / output",
                    direction="output / control",
                )
            )

    for component in controller_hardware:
        inventory.append(
            _legacy_inventory_as_ros_device(
                component,
                device_class="controller / interface",
                direction="bidirectional",
            )
        )

    _inherit_device_correlations(inventory, [*sensors, *actuators])
    return _deduplicate(inventory)


def _ros_device_roles(
    node: str,
    published_topics: list[str],
    subscribed_topics: list[str],
    topic_types: dict[str, str],
    parameters: dict[str, str],
) -> list[tuple[str, str, str, str, str]]:
    """Infer one or more device roles from graph direction, types, names, and parameters."""

    roles: dict[tuple[str, str, str], tuple[str, str]] = {}

    def add(
        device_class: str,
        kind: str,
        direction: str,
        confidence: str,
        evidence: str,
    ) -> None:
        key = (device_class, kind, direction)
        current = roles.get(key)
        if current is None or current[0] == "CORRELATED" and confidence == "VERIFIED":
            roles[key] = (confidence, evidence)

    for topic in published_topics:
        message_type = topic_types.get(topic, "unknown")
        sensor_kind = _sensor_kind(topic, message_type)
        if sensor_kind is not None:
            if sensor_kind == "battery monitor":
                add(
                    "power",
                    "power / battery device",
                    "input / monitoring",
                    "VERIFIED",
                    f"publishes {message_type} on {topic}",
                )
            elif sensor_kind == "microphone":
                # Topic words such as "audio/status" do not prove microphone
                # ownership. Accept microphone data only from a mic-like node
                # with an audio payload type.
                if message_type not in _AUDIO_MESSAGE_TYPES or not _node_identity_supports(
                    node, parameters, "microphone"
                ):
                    continue
            else:
                add(
                    "sensor / input",
                    sensor_kind,
                    "input",
                    "VERIFIED",
                    f"publishes {message_type} on {topic}",
                )
        if message_type in _AUDIO_MESSAGE_TYPES and _node_identity_supports(
            node, parameters, "microphone"
        ):
            add(
                "audio",
                "microphone / audio capture",
                "input",
                "VERIFIED",
                f"publishes audio data on {topic}",
            )

    for topic in subscribed_topics:
        message_type = topic_types.get(topic, "unknown")
        if message_type in _AUDIO_MESSAGE_TYPES and _node_identity_supports(
            node, parameters, "speaker"
        ):
            add(
                "audio",
                "speaker / audio output",
                "output",
                "VERIFIED",
                f"subscribes to audio data on {topic}",
            )
        if _is_actuator_command(topic, message_type):
            add(
                "actuator / output",
                _actuator_kind(topic, message_type),
                "output / control",
                "VERIFIED",
                f"subscribes to command topic {topic}",
            )

    identity = " ".join((node, *parameters.keys(), *parameters.values())).lower()
    bidirectional = " ".join((identity, *published_topics, *subscribed_topics)).lower()

    for haystack, tokens, role in (
        (
            identity,
            ("speaker", "playback", "audio_output", "sound_player"),
            ("audio", "speaker / audio output", "output"),
        ),
        (
            identity,
            ("microphone", "mic_recorder", "audio_capture", "mic_node"),
            ("audio", "microphone / audio capture", "input"),
        ),
        (
            identity,
            ("display", "screen", "hmi", "lcd", "oled", "face_gui", "face_display", "face"),
            ("display / HMI", "display / visual output", "output"),
        ),
        (
            identity,
            ("motor", "servo", "gripper", "diff_drive", "drive_controller"),
            ("actuator / output", "motor / actuator controller", "output / control"),
        ),
        (
            identity,
            ("battery", "bms", "power_supply"),
            ("power", "power / battery device", "input / monitoring"),
        ),
        (
            bidirectional,
            ("gpio", "pwm", "relay", "led_controller", "lighting"),
            ("I/O / lighting", "digital I/O / lighting device", "bidirectional"),
        ),
        (
            bidirectional,
            (
                "canopen",
                "can_bus",
                "can_bridge",
                "ethercat",
                "modbus",
                "serial_bridge",
                "uart_bridge",
            ),
            ("communication", "hardware communication interface", "bidirectional"),
        ),
    ):
        role_kind = role[1]
        if role_kind == "speaker / audio output" and not _node_identity_supports(
            node, parameters, "speaker"
        ):
            continue
        if role_kind == "microphone / audio capture" and not _node_identity_supports(
            node, parameters, "microphone"
        ):
            continue
        if any(token in haystack for token in tokens):
            add(*role, "CORRELATED", "ROS node/parameter or endpoint direction")

    if not roles and parameters:
        add(
            "other hardware",
            "unclassified ROS-attached device",
            "unknown",
            "CONFIGURED_PATH_MATCH" if _configured_device(parameters) else "CORRELATED",
            "hardware-related ROS parameters",
        )

    return [
        (device_class, kind, direction, confidence, evidence)
        for (device_class, kind, direction), (confidence, evidence) in roles.items()
    ]


def _topics_for_device_role(
    kind: str,
    direction: str,
    published_topics: list[str],
    subscribed_topics: list[str],
    topic_types: dict[str, str],
) -> list[str]:
    candidates = published_topics if direction.startswith("input") else subscribed_topics
    if direction == "bidirectional" or direction == "unknown":
        candidates = [*published_topics, *subscribed_topics]

    lowered_kind = kind.lower()
    selected: list[str] = []
    for topic in candidates:
        message_type = topic_types.get(topic, "unknown")
        text = f"{topic} {message_type}".lower()
        matches = bool(
            (
                "audio" in lowered_kind
                and any(token in text for token in ("audio", "sound", "voice"))
            )
            or (
                "display" in lowered_kind
                and any(token in text for token in ("image", "display", "screen", "face", "hmi"))
            )
            or ("motor" in lowered_kind and _is_actuator_command(topic, message_type))
            or (
                "power" in lowered_kind
                and any(token in text for token in ("battery", "power", "bms"))
            )
            or ("sensor" in lowered_kind and _sensor_kind(topic, message_type) is not None)
            or lowered_kind == str(_sensor_kind(topic, message_type) or "").lower()
        )
        if matches and topic not in selected:
            selected.append(topic)
    return selected


def _node_identity_supports(node: str, parameters: dict[str, str], role: str) -> bool:
    node_identity = node.lower()
    parameter_identity = " ".join((*parameters.keys(), *parameters.values())).lower()
    if role == "speaker":
        node_tokens = ("speaker", "playback", "audio_output", "sound_player")
        parameter_tokens = ("playback_device", "speaker_device", "audio_output", "alsa_sink")
    else:
        node_tokens = ("microphone", "mic_recorder", "audio_capture", "mic_node")
        parameter_tokens = ("capture_device", "microphone_device", "audio_input", "alsa_source")
    return any(token in node_identity for token in node_tokens) or any(
        token in parameter_identity for token in parameter_tokens
    )


def _legacy_inventory_as_ros_device(
    component: Component,
    *,
    device_class: str,
    direction: str,
) -> Component:
    details = component.details.copy()
    details.update(
        {
            "device_class": device_class,
            "direction": direction,
            "ros_node": details.get("ros_node") or details.get("hardware_node"),
            "topics": details.get("channel") if details.get("message_type") else None,
        }
    )
    return Component(
        category="ROS device",
        name=component.name,
        status=component.status,
        details=details,
    )


def _inherit_device_correlations(
    devices: list[Component],
    inventory_items: list[Component],
) -> None:
    for device in devices:
        topics = str(device.details.get("topics") or device.details.get("channel") or "")
        for item in inventory_items:
            channel = str(item.details.get("channel") or "")
            if not channel or channel not in topics:
                continue
            for key in (
                "physical_component",
                "physical_bus",
                "physical_channel",
                "driver",
                "configured_device",
                "correlation_evidence",
            ):
                if item.details.get(key) is not None:
                    device.details[key] = item.details[key]
            if device.details.get("physical_component"):
                device.details["state"] = "IN_USE_BY_ROS"
                device.details["ownership"] = "PHYSICAL_MAPPING_CORRELATED"


def _correlate_ros_devices_with_physical(
    devices: list[Component],
    usb_devices: list[USBDevice],
    serial_devices: list[SerialDevice],
) -> None:
    """Attach exact Linux hardware only when a ROS configuration path proves it."""

    for device in devices:
        details = device.details
        parameter_text = " ".join(
            str(details.get(key) or "") for key in ("configured_device", "hardware_parameters")
        )
        if not parameter_text.strip():
            continue

        for serial_device in serial_devices:
            identities = (serial_device.port, serial_device.stable_id_path)
            matched = next(
                (identity for identity in identities if identity and identity in parameter_text),
                None,
            )
            if matched is None:
                continue
            details.update(
                {
                    "physical_component": serial_device.display_name,
                    "physical_bus": serial_device.transport,
                    "physical_channel": serial_device.port,
                    "driver": serial_device.driver,
                    "confidence": "CONFIGURED_PATH_MATCH",
                    "state": "IN_USE_BY_ROS",
                    "ownership": "PHYSICAL_PATH_VERIFIED",
                    "correlation_evidence": f"ROS configuration references {matched}",
                }
            )
            break

        for usb_device in usb_devices:
            matched_node = next(
                (node.path for node in usb_device.device_nodes if node.path in parameter_text),
                None,
            )
            if matched_node is None:
                continue
            details.update(
                {
                    "physical_component": usb_device.display_name,
                    "physical_bus": "USB",
                    "physical_channel": matched_node,
                    "driver": ", ".join(usb_device.drivers) or "unbound",
                    "confidence": "CONFIGURED_PATH_MATCH",
                    "state": "IN_USE_BY_ROS",
                    "ownership": "PHYSICAL_PATH_VERIFIED",
                    "correlation_evidence": f"ROS configuration references {matched_node}",
                }
            )
            break


def _physical_sensor_inventory(
    usb_devices: list[USBDevice],
    serial_devices: list[SerialDevice],
) -> list[Component]:
    inventory: list[Component] = []
    for usb_device in usb_devices:
        text = " ".join(
            filter(
                None,
                (
                    usb_device.display_name,
                    usb_device.device_class_name,
                    *usb_device.drivers,
                    *(node.path for node in usb_device.device_nodes),
                ),
            )
        ).lower()
        identified = _physical_sensor_kind(text)
        if identified is None:
            continue
        kind, protocol = identified
        inventory.append(
            Component(
                category="sensor",
                name=usb_device.display_name,
                status=ComponentStatus.OK,
                details={
                    "kind": kind,
                    "source": "Linux USB/sysfs",
                    "bus": "USB",
                    "protocol": protocol,
                    "channel": _usb_channel(usb_device),
                    "usb_id": usb_device.usb_id,
                    "driver": ", ".join(usb_device.drivers) or "unbound",
                    "state": "DETECTED",
                    "health": "PRESENT_NOT_EXERCISED",
                    "confidence": "VERIFIED",
                },
            )
        )

    for serial_device in serial_devices:
        serial_kind = _named_sensor_kind(serial_device.display_name.lower())
        if serial_kind is None:
            continue
        inventory.append(
            Component(
                category="sensor",
                name=serial_device.display_name,
                status=ComponentStatus.OK,
                details={
                    "kind": serial_kind,
                    "source": "Linux serial/sysfs",
                    "bus": serial_device.transport,
                    "protocol": "serial/UART",
                    "channel": serial_device.port,
                    "driver": serial_device.driver,
                    "state": "DETECTED",
                    "health": "PRESENT_PORT_NOT_OPENED",
                    "confidence": "CORRELATED",
                },
            )
        )
    return _deduplicate(inventory)


def _physical_actuator_inventory(
    usb_devices: list[USBDevice],
    serial_devices: list[SerialDevice],
) -> list[Component]:
    inventory: list[Component] = []
    for serial_device in serial_devices:
        serial_kind = _named_actuator_kind(serial_device.display_name.lower())
        if serial_kind is not None:
            inventory.append(
                _physical_actuator_component(
                    name=serial_device.display_name,
                    kind=serial_kind,
                    source="Linux serial/sysfs",
                    bus=serial_device.transport,
                    protocol="serial/UART",
                    channel=serial_device.port,
                    driver=serial_device.driver,
                )
            )
    for usb_device in usb_devices:
        usb_kind = _named_actuator_kind(usb_device.display_name.lower())
        if usb_kind is not None:
            inventory.append(
                _physical_actuator_component(
                    name=usb_device.display_name,
                    kind=usb_kind,
                    source="Linux USB/sysfs",
                    bus="USB",
                    protocol="USB",
                    channel=_usb_channel(usb_device),
                    driver=", ".join(usb_device.drivers) or "unbound",
                )
            )
    return _deduplicate(inventory)


def _physical_actuator_component(
    *,
    name: str,
    kind: str,
    source: str,
    bus: str,
    protocol: str,
    channel: str | None,
    driver: str | None,
) -> Component:
    return Component(
        category="actuator/control",
        name=name,
        status=ComponentStatus.OK,
        details={
            "kind": kind,
            "source": source,
            "bus": bus,
            "protocol": protocol,
            "channel": channel,
            "driver": driver,
            "state": "DETECTED",
            "health": "CONTROLLER_PRESENT_OUTPUTS_NOT_ACTIVATED",
            "confidence": "CORRELATED",
        },
    )


def _ros_physical_sensor_usage(
    ros_sensors: list[Component],
    usb_devices: list[USBDevice],
    serial_devices: list[SerialDevice],
    node_parameters: dict[str, dict[str, str]],
    process_text: str,
) -> list[Component]:
    """Map ROS sensor endpoints to exact Linux devices when evidence permits."""

    usage: list[Component] = []
    single_sensor = len(ros_sensors) == 1

    for ros_sensor in ros_sensors:
        publisher_text = str(ros_sensor.details.get("publishers") or "")
        publisher_nodes = [value.strip() for value in publisher_text.split(",") if value.strip()]
        parameters = _combined_parameters(publisher_nodes, node_parameters)
        parameter_text = " ".join(parameters.values())

        matches: list[tuple[str, str, str, str | None, str | None, str, str]] = []
        for serial_device in serial_devices:
            identities = [serial_device.port, serial_device.stable_id_path]
            parameter_match = any(
                identity and identity in parameter_text for identity in identities
            )
            process_match = single_sensor and any(
                identity and identity in process_text for identity in identities
            )
            if parameter_match or process_match:
                evidence = (
                    f"ROS node parameter references {serial_device.port}"
                    if parameter_match
                    else f"Running ROS process command line references {serial_device.port}"
                )
                matches.append(
                    (
                        serial_device.display_name,
                        serial_device.transport,
                        "serial/UART",
                        serial_device.port,
                        serial_device.driver,
                        evidence,
                        "CONFIGURED_PATH_MATCH" if parameter_match else "PROCESS_PATH_MATCH",
                    )
                )

        for usb_device in usb_devices:
            matching_node = next(
                (node.path for node in usb_device.device_nodes if node.path in parameter_text),
                None,
            )
            if matching_node is not None:
                identified = _physical_sensor_kind(usb_device.display_name.lower())
                matches.append(
                    (
                        usb_device.display_name,
                        "USB",
                        identified[1] if identified else "USB",
                        matching_node,
                        ", ".join(usb_device.drivers) or "unbound",
                        f"ROS node parameter references {matching_node}",
                        "CONFIGURED_PATH_MATCH",
                    )
                )

        for name, bus, protocol, channel, driver, evidence, confidence in matches:
            kind = str(ros_sensor.details.get("kind") or "sensor")
            ros_sensor.details.update(
                {
                    "physical_component": name,
                    "physical_bus": bus,
                    "physical_channel": channel,
                    "driver": driver,
                    "confidence": confidence,
                    "correlation_evidence": evidence,
                }
            )
            usage.append(
                Component(
                    category="sensor",
                    name=f"{kind} hardware — {name}",
                    status=ComponentStatus.OK,
                    details={
                        "kind": kind,
                        "source": "Linux device + ROS 2 configuration",
                        "bus": bus,
                        "protocol": protocol,
                        "channel": channel,
                        "driver": driver,
                        "state": "IN_USE_BY_ROS",
                        "health": "CONFIGURED_AND_ENDPOINT_AVAILABLE_DATA_NOT_SAMPLED",
                        "confidence": confidence,
                        "ros_node": publisher_text or None,
                        "ros_endpoint": ros_sensor.details.get("channel"),
                        "message_type": ros_sensor.details.get("message_type"),
                        "evidence": evidence,
                    },
                )
            )

    return _deduplicate(usage)


def _software_inventory(
    components: list[Component],
    *,
    process_text: str,
    ros_graph_running: bool,
    nodes: list[str] | None = None,
    topics: list[tuple[str, str]] | None = None,
    actions: list[tuple[str, str]] | None = None,
    hardware_endpoints: set[str] | None = None,
) -> list[Component]:
    runtime_text = f"{process_text} {' '.join(nodes or [])}".lower()
    endpoints = [name for name, _type in [*(topics or []), *(actions or [])]]
    hardware_endpoints = hardware_endpoints or set()
    inventory: list[Component] = []
    for component in components:
        installed = _component_installed(component)
        running = _component_running(component.name, runtime_text)
        catalog_stack = component.category in {
            "robotics stack",
            "robotics software stack",
        }
        profile = _STACK_ENDPOINT_PROFILES.get(component.name, {})
        observed_inputs = _matching_endpoints(endpoints, profile.get("inputs", ()))
        observed_outputs = _matching_endpoints(endpoints, profile.get("outputs", ()))
        if component.category == "ROS environment" and ros_graph_running:
            state = "RUNNING"
            running = True
        elif running:
            state = "RUNNING"
            if profile.get("inputs") and not observed_inputs:
                state = "RUNNING_MISSING_REQUIRED_INPUT"
            elif profile.get("outputs") and not observed_outputs:
                state = "RUNNING_NO_EXPECTED_OUTPUT_OBSERVED"
        elif installed:
            state = (
                "CONFIGURED_INACTIVE"
                if component.details.get("configured")
                else "INSTALLED_INACTIVE"
            )
        elif catalog_stack:
            state = "NOT_INSTALLED"
        else:
            continue

        details = component.details.copy()
        connected: bool | None = None
        if running and profile:
            connected = bool(observed_inputs)
        integrated: bool | None = None
        if connected and observed_inputs:
            integrated = (
                any(
                    _endpoint_matches(endpoint, hardware_endpoint)
                    for endpoint in observed_inputs
                    for hardware_endpoint in hardware_endpoints
                )
                or None
            )
        details.update(
            {
                "installed": installed,
                "running": running,
                "state": state,
                "connected": connected,
                "integrated": integrated,
                "observed_inputs": ", ".join(observed_inputs) or None,
                "observed_outputs": ", ".join(observed_outputs) or None,
                "capability_state": _capability_state(state, integrated),
                "ros_graph_present": ros_graph_running,
                "runtime_owner": (
                    "ROS graph or direct process" if running else details.get("runtime_owner")
                ),
                "original_category": component.category,
            }
        )
        inventory.append(
            Component(
                category="software stack",
                name=component.name,
                status=(
                    ComponentStatus.OK
                    if running and component.status is ComponentStatus.UNKNOWN
                    else component.status
                ),
                details=details,
            )
        )
    return inventory


def _matching_endpoints(endpoints: list[str], tokens: tuple[str, ...]) -> list[str]:
    return sorted(
        endpoint
        for endpoint in endpoints
        if any(token.casefold() in endpoint.casefold() for token in tokens)
    )


def _endpoint_matches(left: str, right: str) -> bool:
    return left == right or left.endswith(right) or right.endswith(left)


def _hardware_endpoints(devices: list[Component]) -> set[str]:
    endpoints: set[str] = set()
    for device in devices:
        for key in ("ros_endpoint", "topics", "channel"):
            value = device.details.get(key)
            if value:
                endpoints.update(item.strip() for item in str(value).split(",") if item.strip())
    return endpoints


def _capability_state(state: str, integrated: bool | None) -> str:
    if state == "NOT_INSTALLED":
        return "UNAVAILABLE"
    if state in {"INSTALLED_INACTIVE", "CONFIGURED_INACTIVE"}:
        return "INACTIVE"
    if "MISSING_REQUIRED_INPUT" in state or "NO_EXPECTED_OUTPUT" in state:
        return "BLOCKED"
    if integrated is True:
        return "OPERATIONAL_EVIDENCE_PRESENT"
    if state == "RUNNING":
        return "RUNNING_INTEGRATION_UNPROVEN"
    return "NOT_EVALUATED"


def _controller_components(output: str) -> list[Component]:
    inventory: list[Component] = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 3 or fields[0].lower().startswith("controller"):
            continue
        state = fields[-1].upper()
        inventory.append(
            Component(
                category="actuator/control",
                name=fields[0],
                status=(
                    ComponentStatus.OK
                    if state in {"ACTIVE", "RUNNING"}
                    else ComponentStatus.WARNING
                ),
                details={
                    "kind": "ros2_control controller",
                    "source": "ROS 2 runtime",
                    "controller_type": fields[1],
                    "state": state,
                    "health": "REPORTED_BY_ROS2_CONTROL",
                    "confidence": "VERIFIED",
                },
            )
        )
    return inventory


def _controller_hardware_components(output: str) -> list[Component]:
    """Parse ros2_control hardware components without activating any interface."""

    inventory: list[Component] = []
    blocks = re.split(r"(?=Hardware Component\s+\d+)", output, flags=re.IGNORECASE)
    for block in blocks:
        if not re.search(r"Hardware Component\s+\d+", block, re.IGNORECASE):
            continue
        name = _labeled_value(block, "name")
        component_type = _labeled_value(block, "type")
        plugin = _labeled_value(block, "plugin name")
        state_text = _labeled_value(block, "state") or "UNKNOWN"
        state = state_text.upper()
        inventory.append(
            Component(
                category="actuator/control",
                name=name or plugin or "ros2_control hardware component",
                status=(
                    ComponentStatus.OK
                    if any(token in state for token in ("ACTIVE", "INACTIVE", "UNCONFIGURED"))
                    else ComponentStatus.UNKNOWN
                ),
                details={
                    "kind": "ros2_control hardware component",
                    "source": "ROS 2 runtime",
                    "hardware_type": component_type,
                    "plugin": plugin,
                    "state": state,
                    "health": "REPORTED_BY_CONTROLLER_MANAGER_OUTPUT_NOT_ACTIVATED",
                    "confidence": "VERIFIED",
                    "evidence": "ros2 control list_hardware_components --verbose",
                },
            )
        )
    return inventory


def _labeled_value(block: str, label: str) -> str | None:
    match = re.search(
        rf"^\s*{re.escape(label)}:\s*(.+?)\s*$",
        block,
        re.IGNORECASE | re.MULTILINE,
    )
    return match.group(1).strip() if match else None


def _command_findings(results: dict[str, CommandResult]) -> list[Finding]:
    findings: list[Finding] = []
    for name, result in results.items():
        if result.succeeded:
            continue
        findings.append(
            Finding(
                code=f"ROS_{name.upper()}_INSPECTION_{result.state.upper()}",
                severity=(
                    FindingSeverity.WARNING
                    if result.state in {"timeout", "budget_exhausted"}
                    else FindingSeverity.INFO
                ),
                summary=f"ROS {name} inspection was {result.state}; inspection continued.",
                evidence=result.error,
                recommendation="Check the sourced ROS environment and DDS discovery settings.",
            )
        )
    return findings


def _parse_typed_names(output: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for line in output.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        match = re.match(r"^(\S+)\s+\[(.+)]$", cleaned)
        entries.append((match.group(1), match.group(2).strip()) if match else (cleaned, "unknown"))
    return entries


def _parse_node_info(output: str) -> dict[str, list[str]]:
    endpoints: dict[str, list[str]] = {
        "publishers": [],
        "subscribers": [],
        "services": [],
        "actions": [],
    }
    headings = {
        "Publishers:": "publishers",
        "Subscribers:": "subscribers",
        "Service Servers:": "services",
        "Service Clients:": "services",
        "Action Servers:": "actions",
        "Action Clients:": "actions",
    }
    section: str | None = None
    for line in output.splitlines():
        stripped = line.strip()
        if stripped in headings:
            section = headings[stripped]
        elif section and stripped.startswith("/"):
            endpoint = stripped.split(":", 1)[0]
            if endpoint not in endpoints[section]:
                endpoints[section].append(endpoint)
    return endpoints


def _parse_topic_info(output: str) -> tuple[list[str], list[str]]:
    """Extract fully qualified publisher and subscriber node names."""

    publishers: list[str] = []
    subscribers: list[str] = []
    blocks = re.split(r"(?=\s*Node name:\s*)", output)

    for block in blocks:
        name_match = re.search(r"^\s*Node name:\s*(\S+)", block, re.MULTILINE)
        type_match = re.search(r"^\s*Endpoint type:\s*(\S+)", block, re.MULTILINE)
        if name_match is None or type_match is None:
            continue

        namespace_match = re.search(r"^\s*Node namespace:\s*(\S+)", block, re.MULTILINE)
        node = _qualified_node_name(
            name_match.group(1),
            namespace_match.group(1) if namespace_match else "/",
        )
        target = publishers if type_match.group(1).upper() == "PUBLISHER" else subscribers
        if node not in target:
            target.append(node)

    return publishers, subscribers


def _qualified_node_name(name: str, namespace: str) -> str:
    if name.startswith("/"):
        return name
    prefix = namespace.rstrip("/")
    return f"{prefix}/{name}" if prefix else f"/{name}"


def _hardware_relevant_nodes(
    device_topics: list[tuple[str, str]],
    publishers: dict[str, list[str]],
    subscribers: dict[str, list[str]],
    nodes: list[str],
) -> list[str]:
    relevant: list[str] = []
    for topic, _message_type in device_topics:
        for node in publishers.get(topic, []):
            if node not in relevant:
                relevant.append(node)
        for node in subscribers.get(topic, []):
            if node not in relevant:
                relevant.append(node)

    for node in nodes:
        lowered = node.lower()
        if (
            any(
                token in lowered
                for token in (
                    "camera",
                    "lidar",
                    "laser",
                    "imu",
                    "gps",
                    "gnss",
                    "radar",
                    "sensor",
                    "driver",
                    "speaker",
                    "audio",
                    "sound",
                    "tts",
                    "display",
                    "screen",
                    "hmi",
                    "face",
                    "motor",
                    "servo",
                    "gripper",
                    "drive",
                    "battery",
                    "power",
                    "bms",
                    "gpio",
                    "pwm",
                    "relay",
                    "can",
                    "ethercat",
                    "modbus",
                    "serial",
                    "uart",
                    "controller_manager",
                )
            )
            and node not in relevant
        ):
            relevant.append(node)

    # Probe remaining nodes as budget permits. A generically named hardware driver
    # can only be recognized after its parameters expose a device path/interface.
    for node in nodes:
        if node not in relevant:
            relevant.append(node)
    return relevant[:_MAX_PARAMETER_PROBES]


def _probe_hardware_parameters(
    executable: str,
    nodes: list[str],
    *,
    environment: dict[str, str],
    deadline: float,
) -> dict[str, dict[str, str]]:
    parameters: dict[str, dict[str, str]] = {}
    for node in nodes:
        result = _run_ros2(
            executable,
            ("param", "dump", node),
            deadline=deadline,
            timeout=_DETAIL_TIMEOUT_SECONDS,
            environment=environment,
        )
        if not result.succeeded:
            continue
        relevant = _parse_hardware_parameters(result.stdout)
        if relevant:
            parameters[node] = relevant
    return parameters


def _parse_hardware_parameters(output: str) -> dict[str, str]:
    parameters: dict[str, str] = {}
    for line in output.splitlines():
        match = re.match(r"^\s+([A-Za-z0-9_.-]+):\s*(.*?)\s*$", line)
        if match is None:
            continue
        name = match.group(1)
        value = match.group(2).strip("'\"")
        lowered = name.lower()
        if not value or value in {"{}", "[]"}:
            continue
        if not any(token in lowered for token in _HARDWARE_PARAMETER_TOKENS):
            continue
        parameters[name] = value[:500]
    return parameters


def _combined_parameters(
    nodes: list[str],
    node_parameters: dict[str, dict[str, str]],
) -> dict[str, str]:
    combined: dict[str, str] = {}
    for node in nodes:
        for name, value in node_parameters.get(node, {}).items():
            combined.setdefault(name, value)
    return combined


def _format_parameters(parameters: dict[str, str] | None) -> str | None:
    if not parameters:
        return None
    return "; ".join(f"{name}={value}" for name, value in sorted(parameters.items()))


def _configured_device(parameters: dict[str, str]) -> str | None:
    for name, value in parameters.items():
        lowered = name.lower()
        if "port" in lowered or "device" in lowered:
            return value
    return None


def _is_device_relevant_topic(topic: str, message_type: str) -> bool:
    """Return whether endpoint metadata can identify a hardware-facing ROS role."""

    text = f"{topic} {message_type}".lower()
    return bool(
        _sensor_kind(topic, message_type) is not None
        or _is_actuator_command(topic, message_type)
        or message_type in _AUDIO_MESSAGE_TYPES
        or any(token in text for token in _DEVICE_TOPIC_TOKENS)
    )


def _sensor_kind(topic: str, message_type: str) -> str | None:
    if message_type in _SENSOR_MESSAGE_TYPES:
        return _SENSOR_MESSAGE_TYPES[message_type]
    lowered = f"{topic} {message_type}".lower()
    for token, kind in (
        ("radar", "radar"),
        ("microphone", "microphone"),
        ("/audio", "microphone"),
        ("encoder", "encoder"),
        ("proximity", "proximity sensor"),
    ):
        if token in lowered:
            return kind
    return None


def _physical_sensor_kind(text: str) -> tuple[str, str] | None:
    if any(token in text for token in ("uvcvideo", "/dev/video", "webcam", "camera")):
        return "camera", "USB Video Class"
    if any(token in text for token in ("snd_usb_audio", "snd-usb-audio", "microphone")):
        return "microphone", "USB Audio Class"
    named = _named_sensor_kind(text)
    return (named, "USB vendor protocol") if named else None


def _named_sensor_kind(text: str) -> str | None:
    for token, kind in (
        ("rplidar", "lidar"),
        ("lidar", "lidar"),
        (" inertial", "IMU"),
        ("imu", "IMU"),
        ("gnss", "GPS/GNSS"),
        ("gps", "GPS/GNSS"),
        ("radar", "radar"),
        ("camera", "camera"),
    ):
        if token in text:
            return kind
    return None


def _named_actuator_kind(text: str) -> str | None:
    for token, kind in (
        ("dynamixel", "servo controller"),
        ("roboclaw", "motor controller"),
        ("odrive", "motor controller"),
        ("vesc", "motor controller"),
        ("servo controller", "servo controller"),
        ("motor controller", "motor controller"),
        ("gripper controller", "gripper controller"),
    ):
        if token in text:
            return kind
    return None


def _is_actuator_command(topic: str, message_type: str) -> bool:
    command_name = any(
        token in topic.lower()
        for token in ("cmd", "command", "setpoint", "trajectory", "gripper", "servo")
    )
    return message_type in _ACTUATOR_MESSAGE_TYPES and command_name


def _actuator_kind(topic: str, message_type: str) -> str:
    lowered = topic.lower()
    if "gripper" in lowered:
        return "gripper"
    if "servo" in lowered:
        return "servo"
    if "joint" in lowered or "trajectory" in message_type.lower():
        return "joint/motor controller"
    if "ackermann" in message_type.lower():
        return "steering and drive controller"
    if "twist" in message_type.lower() or "cmd_vel" in lowered:
        return "mobile base drive"
    return "actuator command"


def _correlate_physical_and_ros(items: list[Component]) -> None:
    physical: dict[str, list[Component]] = {}
    ros: dict[str, list[Component]] = {}
    for item in items:
        kind = _correlation_kind(str(item.details.get("kind", "")))
        if not kind:
            continue
        target = ros if item.details.get("source") == "ROS 2 runtime" else physical
        target.setdefault(kind, []).append(item)

    for kind, ros_items in ros.items():
        physical_items = physical.get(kind, [])
        if len(physical_items) != 1:
            continue
        device = physical_items[0]
        device.details["ros_endpoints"] = ", ".join(
            str(item.details.get("channel") or item.name) for item in ros_items
        )
        for item in ros_items:
            if item.details.get("confidence") == "CONFIGURED_PATH_MATCH":
                continue
            item.details.update(
                {
                    "physical_component": device.name,
                    "physical_bus": device.details.get("bus"),
                    "physical_channel": device.details.get("channel"),
                    "driver": device.details.get("driver"),
                    "confidence": "CORRELATED",
                }
            )


def _correlation_kind(kind: str) -> str:
    lowered = kind.lower()
    if any(token in lowered for token in ("motor", "servo", "drive", "steering")):
        return "motion-control"
    return lowered


def _component_installed(component: Component) -> bool:
    if isinstance(component.details.get("installed"), bool):
        return bool(component.details["installed"])
    if isinstance(component.details.get("detected"), bool):
        return bool(component.details["detected"])
    return component.status is ComponentStatus.OK


def _ros_installation_detected(components: list[Component]) -> bool:
    for component in components:
        if component.category != "ROS environment":
            continue
        detected = component.details.get("detected")
        return bool(detected) if isinstance(detected, bool) else _component_installed(component)
    return False


def _component_running(name: str, runtime_text: str) -> bool:
    hints = _RUNNING_HINTS.get(name, (name.lower().replace(" ", "_"),))
    return any(
        re.search(
            rf"(?<![a-z0-9]){re.escape(hint.casefold())}(?![a-z0-9])",
            runtime_text.casefold(),
        )
        is not None
        for hint in hints
    )


def _running_process_text() -> str:
    values: list[str] = []
    try:
        processes = psutil.process_iter(["name", "cmdline"])
        for process in processes:
            try:
                name = str(process.info.get("name") or "")
                command = [str(value) for value in (process.info.get("cmdline") or [])]
                values.extend(_process_identity_tokens(name, command))
            except (psutil.Error, OSError, TypeError):
                continue
    except (psutil.Error, OSError):
        return ""
    return "\n".join(values).casefold()


def _process_identity_tokens(name: str, command: list[str]) -> list[str]:
    """Keep executable identities while excluding arbitrary shell arguments."""

    identities = {Path(name).name} if name else set()
    if command:
        identities.add(Path(command[0]).name)
    for argument in command[1:3]:
        if " " not in argument and Path(argument).suffix.casefold() in {".py", ".sh"}:
            identities.add(Path(argument).name)
    return sorted(identity for identity in identities if identity)


def _usb_channel(device: USBDevice) -> str | None:
    paths = ", ".join(node.path for node in device.device_nodes)
    return paths or device.sysfs_name


def _deduplicate(components: list[Component]) -> list[Component]:
    unique: list[Component] = []
    seen: set[tuple[str, str, object]] = set()
    for component in components:
        key = (component.category, component.name, component.details.get("channel"))
        if key not in seen:
            seen.add(key)
            unique.append(component)
    return unique


def _lines(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if line.strip()]


def _compact(output: str, limit: int = 3000) -> str:
    return " | ".join(_lines(output))[:limit]


def _decode_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


__all__ = ["RuntimeInventory", "collect_runtime_inventory"]
