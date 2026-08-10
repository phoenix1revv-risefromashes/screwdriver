"""Test passive, bounded runtime inventory collection."""

from __future__ import annotations

import subprocess

import pytest

from screwdriver.collectors import runtime
from screwdriver.models import (
    Component,
    ComponentStatus,
    SerialDevice,
    USBDevice,
)


@pytest.fixture(autouse=True)
def _stable_ros_environment_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "_ros_environment_candidates", lambda: [{}])


def _static_components() -> list[Component]:
    return [
        Component(
            category="ROS environment",
            name="ROS installation and environment",
            status=ComponentStatus.OK,
            details={"detected": True},
        ),
        Component(
            category="robotics stack",
            name="Navigation2",
            status=ComponentStatus.OK,
            details={"matched_packages": "nav2_bringup"},
        ),
        Component(
            category="compute library",
            name="OpenCV",
            status=ComponentStatus.OK,
            details={"version": "4.10"},
        ),
    ]


def test_missing_ros2_keeps_physical_and_software_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: None)
    monkeypatch.setattr(runtime, "_running_process_text", lambda: "")
    camera = USBDevice(
        sysfs_name="1-3",
        vendor_id="046d",
        product_id="094c",
        manufacturer="Logitech",
        product_name="Brio 100",
        drivers=["uvcvideo"],
    )
    generic_bridge = SerialDevice(
        port="/dev/ttyUSB0",
        sysfs_name="ttyUSB0",
        transport="usb-serial",
        manufacturer="Silicon Labs",
        product_name="CP2102 USB to UART Bridge",
    )

    result = runtime.collect_runtime_inventory(
        _static_components(),
        [camera],
        [generic_bridge],
    )

    assert result.software_stacks
    assert result.sensors[0].details["kind"] == "camera"
    assert result.actuators == []
    assert result.devices == []
    assert result.ros_runtime[0].details["state"] == "UNAVAILABLE"
    assert any(finding.code == "ROS_RUNTIME_UNAVAILABLE" for finding in result.findings)


def test_running_graph_discovers_endpoints_controllers_and_correlations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/usr/bin/ros2")
    monkeypatch.setattr(runtime, "_running_process_text", lambda: "planner_server")
    calls: list[list[str]] = []
    outputs = {
        ("node", "list"): "/camera_node\n/controller_manager\n/planner_server\n",
        ("topic", "list", "-t"): (
            "/camera/image_raw [sensor_msgs/msg/Image]\n"
            "/cmd_vel [geometry_msgs/msg/Twist]\n"
            "/joint_states [sensor_msgs/msg/JointState]\n"
        ),
        ("service", "list", "-t"): ("/camera/get_parameters [rcl_interfaces/srv/GetParameters]\n"),
        ("action", "list", "-t"): (
            "/follow_joint_trajectory [control_msgs/action/FollowJointTrajectory]\n"
        ),
        ("node", "info", "/camera_node"): (
            "Publishers:\n  /camera/image_raw: sensor_msgs/msg/Image\n"
            "Subscribers:\n  /parameter_events: rcl_interfaces/msg/ParameterEvent\n"
        ),
        ("node", "info", "/controller_manager"): (
            "Publishers:\n  /joint_states: sensor_msgs/msg/JointState\n"
            "Subscribers:\n  /cmd_vel: geometry_msgs/msg/Twist\n"
        ),
        ("node", "info", "/planner_server"): "Publishers:\nSubscribers:\n",
        ("control", "list_controllers"): (
            "diff_drive_controller diff_drive_controller/DiffDriveController active\n"
        ),
        ("control", "list_hardware_interfaces"): (
            "command interfaces\n  left_wheel/velocity [available] [claimed]\n"
        ),
        ("control", "list_hardware_components", "--verbose"): (
            "Hardware Component 0\n"
            "  name: mobile_base_system\n"
            "  type: system\n"
            "  plugin name: base_hardware/DiffDriveSystem\n"
            "  state: id=3 label=active\n"
        ),
    }

    def fake_run(
        arguments: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        command_arguments = arguments[1:]
        if command_arguments[-1:] == ["--no-daemon"]:
            command_arguments = command_arguments[:-1]
        key = tuple(command_arguments)
        return subprocess.CompletedProcess(arguments, 0, outputs.get(key, ""), "")

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)
    camera = USBDevice(
        sysfs_name="1-3",
        vendor_id="046d",
        product_id="094c",
        product_name="Camera",
        drivers=["uvcvideo"],
    )

    result = runtime.collect_runtime_inventory(_static_components(), [camera], [])

    summary = result.ros_runtime[0]
    assert summary.details["state"] == "RUNNING"
    assert summary.details["nodes"] == 3
    assert any(item.name == "diff_drive_controller" for item in result.actuators)
    assert any(item.name == "mobile_base_system" for item in result.actuators)
    assert any(item.details.get("kind") == "mobile base drive" for item in result.actuators)
    assert any(item.details.get("device_class") == "sensor / input" for item in result.devices)
    assert any(
        item.details.get("device_class") == "actuator / output" for item in result.devices
    )
    assert any(
        item.details.get("device_class") == "controller / interface"
        for item in result.devices
    )
    ros_camera = next(
        item for item in result.sensors if item.details.get("source") == "ROS 2 runtime"
    )
    assert ros_camera.details["physical_component"] == "Camera"
    navigation = next(item for item in result.software_stacks if item.name == "Navigation2")
    assert navigation.details["state"] == "RUNNING"
    assert any(finding.code == "ROS_RUNTIME_DISCOVERED" for finding in result.findings)
    graph_list_calls = [
        command
        for command in calls
        if tuple(command[1:])
        in {
            ("node", "list"),
            ("topic", "list", "-t"),
            ("service", "list", "-t"),
            ("action", "list", "-t"),
        }
    ]
    control_calls = [command for command in calls if command[1] == "control"]
    assert len(graph_list_calls) == 4
    assert all("--no-daemon" not in command for command in graph_list_calls)
    assert all("--no-daemon" not in command for command in control_calls)
    assert not any("publish" in command or "action send_goal" in command for command in calls)


def test_hanging_ros_commands_are_bounded_and_nonfatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/usr/bin/ros2")
    monkeypatch.setattr(runtime, "_running_process_text", lambda: "")

    def timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired("ros2", 0.01)

    monkeypatch.setattr(runtime.subprocess, "run", timeout)

    result = runtime.collect_runtime_inventory(_static_components(), [], [])

    assert result.software_stacks
    assert result.sensors == []
    assert result.actuators == []
    assert result.devices == []
    assert result.ros_runtime[0].details["state"] == "UNAVAILABLE"
    assert result.ros_runtime[0].status is ComponentStatus.WARNING
    assert any("TIMEOUT" in finding.code for finding in result.findings)


def test_failed_node_details_do_not_erase_discovered_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/usr/bin/ros2")
    monkeypatch.setattr(runtime, "_running_process_text", lambda: "")

    def fake_run(
        arguments: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if arguments[1:] == ["node", "list", "--no-daemon"]:
            return subprocess.CompletedProcess(arguments, 0, "/camera_node\n", "")
        if arguments[1:] == ["node", "info", "/camera_node", "--no-daemon"]:
            return subprocess.CompletedProcess(arguments, 1, "", "node disappeared")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)

    result = runtime.collect_runtime_inventory([], [], [])

    node = next(item for item in result.ros_runtime if item.name == "/camera_node")
    assert node.details["state"] == "DISCOVERED"
    assert node.details["detail_probe"] == "failed"


def test_generic_usb_audio_class_is_not_assumed_to_be_a_microphone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: None)
    monkeypatch.setattr(runtime, "_running_process_text", lambda: "")
    speakers = USBDevice(
        sysfs_name="1-4",
        vendor_id="1234",
        product_id="5678",
        product_name="USB Speakers",
        device_class_name="audio",
    )

    result = runtime.collect_runtime_inventory([], [speakers], [])

    assert result.sensors == []


def test_direct_dds_fallback_recovers_graph_when_daemon_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/usr/bin/ros2")
    monkeypatch.setattr(runtime, "_running_process_text", lambda: "")

    def fake_run(
        arguments: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        direct = arguments[-1:] == ["--no-daemon"]
        command = tuple(arguments[1:-1] if direct else arguments[1:])
        if direct and command == ("node", "list"):
            return subprocess.CompletedProcess(arguments, 0, "/lidar_node\n", "")
        if direct and command == ("topic", "list", "-t"):
            return subprocess.CompletedProcess(
                arguments,
                0,
                "/scan [sensor_msgs/msg/LaserScan]\n",
                "",
            )
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)

    result = runtime.collect_runtime_inventory([], [], [])

    assert result.ros_runtime[0].details["state"] == "RUNNING"
    assert result.ros_runtime[0].details["discovery_mode"] == "direct DDS"
    assert any(item.details.get("kind") == "lidar" for item in result.sensors)
    assert any(
        finding.code == "ROS_RUNTIME_DISCOVERY_RECOVERED" for finding in result.findings
    )


def test_ros_lidar_is_mapped_to_exact_usb_uart_device_from_node_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/usr/bin/ros2")
    monkeypatch.setattr(runtime, "_running_process_text", lambda: "rplidar_node")
    outputs = {
        ("node", "list"): "/rplidar_node\n",
        ("topic", "list", "-t"): "/scan [sensor_msgs/msg/LaserScan]\n",
        ("service", "list", "-t"): "",
        ("action", "list", "-t"): "",
        ("node", "info", "/rplidar_node"): (
            "Publishers:\n  /scan: sensor_msgs/msg/LaserScan\nSubscribers:\n"
        ),
        ("topic", "info", "/scan", "--verbose"): (
            "Publisher count: 1\n"
            "Node name: rplidar_node\n"
            "Node namespace: /\n"
            "Endpoint type: PUBLISHER\n"
            "Subscription count: 0\n"
        ),
        ("param", "dump", "/rplidar_node"): (
            "/rplidar_node:\n"
            "  ros__parameters:\n"
            "    serial_port: /dev/ttyUSB0\n"
            "    serial_baudrate: 115200\n"
            "    frame_id: laser\n"
        ),
    }

    def fake_run(
        arguments: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            arguments,
            0,
            outputs.get(tuple(arguments[1:]), ""),
            "",
        )

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)
    bridge = SerialDevice(
        port="/dev/ttyUSB0",
        sysfs_name="ttyUSB0",
        transport="usb-serial",
        driver="cp210x",
        stable_id_path="/dev/serial/by-id/usb-Silicon_Labs_CP2102N-123",
        usb_vendor_id="10c4",
        usb_product_id="ea60",
        manufacturer="Silicon Labs",
        product_name="CP2102N USB to UART Bridge",
    )

    result = runtime.collect_runtime_inventory(_static_components(), [], [bridge])

    physical_lidar = next(
        item for item in result.sensors if item.details.get("state") == "IN_USE_BY_ROS"
    )
    assert physical_lidar.details["kind"] == "lidar"
    assert physical_lidar.details["channel"] == "/dev/ttyUSB0"
    assert physical_lidar.details["driver"] == "cp210x"
    assert physical_lidar.details["ros_node"] == "/rplidar_node"
    assert physical_lidar.details["ros_endpoint"] == "/scan"

    ros_lidar = next(
        item for item in result.sensors if item.details.get("source") == "ROS 2 runtime"
    )
    assert ros_lidar.details["physical_channel"] == "/dev/ttyUSB0"
    assert ros_lidar.details["confidence"] == "CONFIGURED_PATH_MATCH"


def test_software_inventory_omits_components_that_are_not_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: None)
    monkeypatch.setattr(runtime, "_running_process_text", lambda: "")
    missing = Component(
        category="robotics stack",
        name="Missing optional stack",
        status=ComponentStatus.UNKNOWN,
        details={"installed": False},
    )

    result = runtime.collect_runtime_inventory([missing], [], [])

    assert result.software_stacks == []


def test_graph_discovery_uses_environment_recovered_from_running_ros_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environments = [
        {"ROS_DOMAIN_ID": "0"},
        {"ROS_DOMAIN_ID": "7", "ROS_DISTRO": "humble"},
    ]
    monkeypatch.setattr(runtime, "_ros_environment_candidates", lambda: environments)
    monkeypatch.setattr(
        runtime,
        "_ros2_executable",
        lambda _environment, *, prefer_shutil: "/usr/bin/ros2",
    )
    monkeypatch.setattr(runtime, "_running_process_text", lambda: "")

    def fake_run(
        arguments: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        domain = environment.get("ROS_DOMAIN_ID")
        command = tuple(value for value in arguments[1:] if value != "--no-daemon")
        if domain == "7" and command == ("node", "list"):
            return subprocess.CompletedProcess(arguments, 0, "/imu_driver\n", "")
        if domain == "7" and command == ("topic", "list", "-t"):
            return subprocess.CompletedProcess(
                arguments,
                0,
                "/imu/data [sensor_msgs/msg/Imu]\n",
                "",
            )
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)

    result = runtime.collect_runtime_inventory([], [], [])

    assert result.ros_runtime[0].details["state"] == "RUNNING"
    assert result.ros_runtime[0].details["domain_id"] == "7"
    assert result.ros_runtime[0].details["environment_recovered"] is True
    assert any(
        finding.code == "ROS_RUNTIME_ENVIRONMENT_RECOVERED" for finding in result.findings
    )


def test_ros_device_inventory_covers_non_sensor_hardware_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/usr/bin/ros2")
    monkeypatch.setattr(runtime, "_running_process_text", lambda: "")
    outputs = {
        ("node", "list"): (
            "/camera_node\n/microphone_node\n/speaker_node\n/face_display\n/base_controller\n"
            "/battery_monitor\n/led_controller\n/can_bridge\n/mystery_driver\n"
        ),
        ("topic", "list", "-t"): (
            "/camera/image_raw [sensor_msgs/msg/Image]\n"
            "/audio_in [audio_common_msgs/msg/AudioData]\n"
            "/audio_out [audio_common_msgs/msg/AudioData]\n"
            "/face/image [sensor_msgs/msg/Image]\n"
            "/cmd_vel [geometry_msgs/msg/Twist]\n"
            "/battery_state [sensor_msgs/msg/BatteryState]\n"
            "/led/color [std_msgs/msg/ColorRGBA]\n"
            "/can_rx [can_msgs/msg/Frame]\n"
        ),
        ("service", "list", "-t"): "",
        ("action", "list", "-t"): "",
        ("node", "info", "/camera_node"): (
            "Publishers:\n  /camera/image_raw: sensor_msgs/msg/Image\nSubscribers:\n"
        ),
        ("node", "info", "/microphone_node"): (
            "Publishers:\n  /audio_in: audio_common_msgs/msg/AudioData\nSubscribers:\n"
        ),
        ("node", "info", "/speaker_node"): (
            "Publishers:\nSubscribers:\n"
            "  /audio_out: audio_common_msgs/msg/AudioData\n"
        ),
        ("node", "info", "/face_display"): (
            "Publishers:\nSubscribers:\n  /face/image: sensor_msgs/msg/Image\n"
        ),
        ("node", "info", "/base_controller"): (
            "Publishers:\nSubscribers:\n  /cmd_vel: geometry_msgs/msg/Twist\n"
        ),
        ("node", "info", "/battery_monitor"): (
            "Publishers:\n  /battery_state: sensor_msgs/msg/BatteryState\n"
            "Subscribers:\n"
        ),
        ("node", "info", "/led_controller"): (
            "Publishers:\nSubscribers:\n  /led/color: std_msgs/msg/ColorRGBA\n"
        ),
        ("node", "info", "/can_bridge"): (
            "Publishers:\n  /can_rx: can_msgs/msg/Frame\nSubscribers:\n"
        ),
        ("node", "info", "/mystery_driver"): "Publishers:\nSubscribers:\n",
        ("param", "dump", "/mystery_driver"): (
            "/mystery_driver:\n  ros__parameters:\n    device: /dev/ttyACM0\n"
        ),
    }

    def fake_run(
        arguments: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        command = tuple(value for value in arguments[1:] if value != "--no-daemon")
        return subprocess.CompletedProcess(arguments, 0, outputs.get(command, ""), "")

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)
    serial = SerialDevice(
        port="/dev/ttyACM0",
        sysfs_name="ttyACM0",
        transport="usb-serial",
        driver="cdc_acm",
        product_name="Custom USB controller",
    )

    result = runtime.collect_runtime_inventory(_static_components(), [], [serial])

    classes = {item.details.get("device_class") for item in result.devices}
    assert {
        "sensor / input",
        "audio",
        "display / HMI",
        "actuator / output",
        "power",
        "I/O / lighting",
        "communication",
        "other hardware",
    } <= classes
    assert any(
        item.details.get("kind") == "speaker / audio output"
        and item.details.get("ros_node") == "/speaker_node"
        for item in result.devices
    )
    assert any(
        item.details.get("device_class") == "display / HMI"
        and item.details.get("ros_node") == "/face_display"
        for item in result.devices
    )
    unknown = next(
        item
        for item in result.devices
        if item.details.get("kind") == "unclassified ROS-attached device"
    )
    assert unknown.details["physical_channel"] == "/dev/ttyACM0"
    assert unknown.details["driver"] == "cdc_acm"
    assert unknown.details["confidence"] == "CONFIGURED_PATH_MATCH"


def test_audio_text_producers_are_not_mislabeled_as_speakers() -> None:
    topic_types = {
        "/cutie/audio/status": "std_msgs/msg/String",
        "/cutie/audio/file": "std_msgs/msg/String",
        "/cutie/speaker/say": "std_msgs/msg/String",
        "/cutie/speech/text": "std_msgs/msg/String",
    }

    face_roles = runtime._ros_device_roles(
        "/cutie_face",
        ["/cutie/audio/status"],
        [],
        topic_types,
        {},
    )
    llm_roles = runtime._ros_device_roles(
        "/cutie_llm",
        ["/cutie/speech/text"],
        [],
        topic_types,
        {},
    )
    recorder_roles = runtime._ros_device_roles(
        "/cutie_mic_recorder",
        ["/cutie/audio/file", "/cutie/audio/status", "/cutie/speaker/say"],
        [],
        topic_types,
        {},
    )
    speaker_roles = runtime._ros_device_roles(
        "/cutie_speaker",
        [],
        ["/cutie/speaker/say"],
        topic_types,
        {},
    )

    assert not any(kind == "speaker / audio output" for _, kind, *_ in face_roles)
    assert not any(kind == "speaker / audio output" for _, kind, *_ in llm_roles)
    assert not any(kind == "speaker / audio output" for _, kind, *_ in recorder_roles)
    assert any(kind == "speaker / audio output" for _, kind, *_ in speaker_roles)
    assert any(kind == "display / visual output" for _, kind, *_ in face_roles)
