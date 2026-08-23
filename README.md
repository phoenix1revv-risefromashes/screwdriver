# Screwdriver v1.2 — complete ROS node inventory correction

This is a cumulative full-file bundle based on the previous v1.2 node/stack bundle.
It preserves the single Robotics Software Stacks table and the existing direct-host / SSH report-opening behavior.

ROS node corrections in this bundle:

- no fixed node-count target and no 24-node detail cap;
- every node discovered in the selected live ROS domain is retained in the report;
- node discovery is sampled twice in both daemon and direct-DDS modes to reduce transient partial lists;
- compatible node observations are unioned and deduplicated;
- each node remembers the ROS environment + discovery mode that actually observed it;
- node-detail enrichment tries the observing contexts first, then compatible fallbacks;
- all discovered nodes are enriched concurrently within the existing bounded runtime budget;
- failed enrichment never deletes a discovered node;
- ROS 2 Nodes HTML is exactly: Node | State | Publishers | Subscribers;
- Services, Clients, Action servers, and Action clients are not shown in the node table;
- Publishers and Subscribers columns remain visible even when a scan has no values in one of them.

The software stack catalog remains one continuous table:

Stack | Type | Version / Packages | Operational Stage

Validation performed in the supplied repository baseline:

- full pytest suite: 94 passed
- Python compileall: passed
- changed files: no lines over 100 characters

Run the native project gates on the robot after extraction because Ruff and mypy binaries are not available in the artifact-build environment:

    .venv/bin/ruff format src tests
    .venv/bin/ruff check .
    .venv/bin/ruff format --check .
    .venv/bin/pytest
    .venv/bin/mypy src
    git diff --check

Then compare the live node names:

    ros2 node list | sort -u
    screwdriver inspect

The Screwdriver ROS 2 NODES section should contain the same live node-name set for the active domain, with State, Publishers, and Subscribers for every node that can still be queried during enrichment.
