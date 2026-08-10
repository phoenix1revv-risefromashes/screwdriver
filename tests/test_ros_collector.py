"""Test passive ROS and robotics-software inspection."""

from __future__ import annotations

from pathlib import Path

from screwdriver.collectors import ros
from screwdriver.models import ComponentStatus, FindingSeverity


def _make_ros2_prefix(root: Path, *packages: str) -> Path:
    prefix = root / "opt" / "ros" / "humble"
    (prefix / "setup.bash").parent.mkdir(parents=True)
    (prefix / "setup.bash").write_text("", encoding="utf-8")
    index = prefix / "share" / "ament_index" / "resource_index" / "packages"
    index.mkdir(parents=True)
    for package in packages:
        (index / package).write_text("", encoding="utf-8")
    return prefix


def test_collects_healthy_ros2_environment(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    prefix = _make_ros2_prefix(
        tmp_path,
        "rclpy",
        "rmw_fastrtps_cpp",
        "nav2_bringup",
        "rviz2",
    )
    monkeypatch.setattr(ros, "_ROS_ROOT", prefix.parent)  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        ros.shutil,
        "which",
        lambda executable: f"/usr/bin/{executable}" if executable in {"ros2", "colcon"} else None,
    )
    monkeypatch.setenv("ROS_VERSION", "2")  # type: ignore[attr-defined]
    monkeypatch.setenv("ROS_DISTRO", "humble")  # type: ignore[attr-defined]
    monkeypatch.setenv("AMENT_PREFIX_PATH", str(prefix))  # type: ignore[attr-defined]
    monkeypatch.setenv("RMW_IMPLEMENTATION", "rmw_fastrtps_cpp")  # type: ignore[attr-defined]

    components, findings = ros.collect_robotics_software()

    environment = components[0]
    assert environment.status is ComponentStatus.OK
    assert environment.details["indexed_package_count"] == 4
    assert any(component.name == "Navigation2" for component in components)
    assert any(finding.code == "ROS_ENVIRONMENT_HEALTHY" for finding in findings)
    assert not any(finding.severity is FindingSeverity.ERROR for finding in findings)


def test_reports_invalid_domain_and_missing_rmw(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    prefix = _make_ros2_prefix(tmp_path, "rclpy")
    monkeypatch.setattr(ros, "_ROS_ROOT", prefix.parent)  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        ros.shutil,
        "which",
        lambda executable: "/usr/bin/ros2" if executable == "ros2" else None,
    )
    monkeypatch.setenv("ROS_VERSION", "2")  # type: ignore[attr-defined]
    monkeypatch.setenv("ROS_DISTRO", "humble")  # type: ignore[attr-defined]
    monkeypatch.setenv("AMENT_PREFIX_PATH", str(prefix))  # type: ignore[attr-defined]
    monkeypatch.setenv("ROS_DOMAIN_ID", "999")  # type: ignore[attr-defined]
    monkeypatch.setenv("RMW_IMPLEMENTATION", "rmw_cyclonedds_cpp")  # type: ignore[attr-defined]

    components, findings = ros.collect_robotics_software()

    assert components[0].status is ComponentStatus.ERROR
    assert {finding.code for finding in findings} >= {
        "ROS_DOMAIN_ID_INVALID",
        "ROS_RMW_NOT_INSTALLED",
    }


def test_reports_missing_dds_file(monkeypatch: object, tmp_path: Path) -> None:
    missing = tmp_path / "missing-cyclonedds.xml"
    monkeypatch.setenv("CYCLONEDDS_URI", f"file://{missing}")  # type: ignore[attr-defined]

    _, findings = ros.collect_robotics_software()

    assert any(finding.code == "DDS_CONFIGURATION_MISSING" for finding in findings)


def test_no_ros_is_informational(monkeypatch: object, tmp_path: Path) -> None:
    monkeypatch.setattr(ros, "_ROS_ROOT", tmp_path / "absent")  # type: ignore[attr-defined]
    monkeypatch.setattr(ros.shutil, "which", lambda _executable: None)  # type: ignore[attr-defined]
    for variable in (
        "ROS_VERSION",
        "ROS_DISTRO",
        "ROS_DOMAIN_ID",
        "RMW_IMPLEMENTATION",
        "AMENT_PREFIX_PATH",
        "COLCON_PREFIX_PATH",
        "CMAKE_PREFIX_PATH",
        "ROS_PACKAGE_PATH",
        "CYCLONEDDS_URI",
        "FASTRTPS_DEFAULT_PROFILES_FILE",
        "FASTDDS_DEFAULT_PROFILES_FILE",
    ):
        monkeypatch.delenv(variable, raising=False)  # type: ignore[attr-defined]

    components, findings = ros.collect_robotics_software()

    assert components[0].status is ComponentStatus.UNKNOWN
    assert any(finding.code == "ROS_NOT_DETECTED" for finding in findings)
    assert not any(finding.severity is FindingSeverity.ERROR for finding in findings)


def test_invalid_ros_version_is_an_error(monkeypatch: object, tmp_path: Path) -> None:
    monkeypatch.setattr(ros, "_ROS_ROOT", tmp_path / "absent")  # type: ignore[attr-defined]
    monkeypatch.setattr(ros.shutil, "which", lambda _executable: None)  # type: ignore[attr-defined]
    monkeypatch.setenv("ROS_VERSION", "not-a-number")  # type: ignore[attr-defined]

    components, findings = ros.collect_robotics_software()

    assert components[0].status is ComponentStatus.ERROR
    assert any(finding.code == "ROS_VERSION_INVALID" for finding in findings)
