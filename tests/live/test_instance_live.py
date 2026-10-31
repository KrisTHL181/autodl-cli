"""Live read-only test for the plain-instance list.

Skipped unless ``--live`` is passed, and skipped again when the isolated test
config has no token, so a plain ``pytest`` run never touches the network.
"""

from __future__ import annotations

import pytest

from autodl_cli.client import AutoDLClient
from autodl_cli.config import load_config
from autodl_cli.handlers.instance import list_instances

pytestmark = pytest.mark.live


def test_list_instances_against_real_account() -> None:
    """The real endpoint returns a list of instance mappings."""
    token = load_config().get("token")
    if not isinstance(token, str) or not token:
        pytest.skip("no token in the isolated test config; seed one with `autodl auth paste` first")

    with AutoDLClient(token) as client:
        instances = list_instances(client)

    assert isinstance(instances, list)
    for instance in instances:
        assert isinstance(instance.get("uuid"), str)
        assert instance["uuid"]
