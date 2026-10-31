"""Live read-only test for the base-image catalogue.

Skipped unless ``--live`` is passed, and skipped again when the isolated test
config has no token, so a plain ``pytest`` run never touches the network.
"""

from __future__ import annotations

import pytest

from autodl_cli.client import AutoDLClient
from autodl_cli.config import load_config
from autodl_cli.handlers.image import list_images

pytestmark = pytest.mark.live


def test_list_images_against_real_api() -> None:
    """The real catalogue endpoint returns selectable images."""
    token = load_config().get("token")
    if not isinstance(token, str) or not token:
        pytest.skip("no token in the isolated test config; seed one with `autodl auth paste` first")

    with AutoDLClient(token) as client:
        images = list_images(client)

    assert images
    for image in images:
        assert isinstance(image.get("framework_name"), str)
        assert image["framework_name"]
        assert isinstance(image.get("image_uuid"), str)
        assert image["image_uuid"]
