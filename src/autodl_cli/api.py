"""Public library entry point.

Code that consumes autodl-cli as a library should import from here rather
than from :mod:`autodl_cli.handlers` directly. This module re-exports the
handler surface for password login, browser-token lookup, account balance,
instance listing/details, instance creation and lifecycle actions, waiting for
instances and private-image saves, and the base-image catalogue, and normalises
internal exceptions into the :class:`~autodl_cli.errors.AutoDLError` hierarchy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autodl_cli.client import AutoDLClient
from autodl_cli.handlers import account as account_handler
from autodl_cli.handlers import auth as auth_handler
from autodl_cli.handlers import image as image_handler
from autodl_cli.handlers import instance as instance_handler

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

__all__ = [
    "AutoDLClient",
    "cancel_scheduled_shutdown",
    "change_image",
    "clone_instance",
    "create_instance",
    "delete_private_image",
    "get_balance",
    "get_current_user",
    "get_instance",
    "get_usage_statistics",
    "list_images",
    "list_instances",
    "list_private_images",
    "login",
    "power_off",
    "power_on",
    "release_instance",
    "rename_instance",
    "reset_instance",
    "save_image",
    "schedule_shutdown",
    "wait_for_instance",
    "wait_for_private_image",
]


def login(
    phone: str,
    password: str,
    *,
    phone_area: str = "+86",
    device_fingerprint: str | None = None,
) -> dict[str, object]:
    """Log in with a phone number and password.

    :param phone: Phone number registered with AutoDL.
    :param password: Plaintext password.
    :param phone_area: Phone area prefix, ``"+86"`` by default.
    :param device_fingerprint: Reusable 32-character fingerprint; generated
        when ``None``.
    :returns: Mapping with ``token``, ``user``, and ``device_fingerprint``.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(None) as client:
        return auth_handler.login(
            client,
            phone,
            password,
            phone_area=phone_area,
            device_fingerprint=device_fingerprint,
        )


def get_balance(token: str, *, charge_type: str = "payg") -> dict[str, object]:
    """Return the account balance for one billing mode.

    :param token: AutoDL API token obtained by logging in.
    :param charge_type: Billing mode to query, ``"payg"`` by default.
    :returns: The wallet mapping; monetary fields are yuan floats.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return account_handler.get_balance(client, charge_type=charge_type)


def get_usage_statistics(
    token: str,
    *,
    granularity: str = "monthly",
    sub_name: str = "",
    exclude_sub_user: bool = False,
) -> list[dict[str, object]]:
    """Return billing usage statistics for the account.

    ``monthly`` reports roughly the last twelve months and ``daily`` roughly
    the last fourteen days, in ascending date order.

    :param token: AutoDL API token, typically copied from a browser session.
    :param granularity: ``"monthly"`` or ``"daily"``.
    :param sub_name: Sub-user name to filter by; empty means every sub-user.
    :param exclude_sub_user: Whether to exclude sub-user transactions.
    :returns: One mapping per period; the money fields are yuan floats.
    :raises ValueError: When ``granularity`` is not supported.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return account_handler.get_usage_statistics(
            client,
            granularity=granularity,
            sub_name=sub_name,
            exclude_sub_user=exclude_sub_user,
        )


def list_images(
    token: str,
    *,
    frameworks: Iterable[str] = (),
    framework_versions: Iterable[str] = (),
    python_versions: Iterable[str] = (),
    cuda_versions: Iterable[str] = (),
    chip_corps: Iterable[str] = (),
    cpu_archs: Iterable[str] = (),
) -> list[dict[str, object]]:
    """Return the base images available for new instances.

    The API returns a four-level option tree; this function flattens it into
    one record per selectable image. Filters are case-insensitive substrings,
    ORed within one argument and ANDed across arguments.

    :param token: AutoDL API token, typically copied from a browser session.
    :param frameworks: Framework names or fragments to include.
    :param framework_versions: Framework versions or fragments to include.
    :param python_versions: Python/OS labels or fragments to include.
    :param cuda_versions: CUDA versions or fragments to include.
    :param chip_corps: Chip vendors to include, for example ``nvidia``.
    :param cpu_archs: CPU architectures to include, for example ``x86``.
    :returns: One mapping per image with ``framework_name``,
        ``framework_version``, ``python_version``, ``cuda_version``,
        ``image_uuid``, ``chip_corp``, ``cpu_arch``, and ``is_desktop``.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return image_handler.list_images(
            client,
            frameworks=frameworks,
            framework_versions=framework_versions,
            python_versions=python_versions,
            cuda_versions=cuda_versions,
            chip_corps=chip_corps,
            cpu_archs=cpu_archs,
        )


def list_private_images(
    token: str,
    *,
    page_size: int = image_handler.DEFAULT_PRIVATE_PAGE_SIZE,
) -> list[dict[str, object]]:
    """Return the images saved from this account's instances.

    Every page is fetched, so the result is not limited by AutoDL's per-request
    page size. The API's entries are returned unchanged.

    :param token: AutoDL API token, typically copied from a browser session.
    :param page_size: Images requested per API call; must be positive.
    :returns: One mapping per private image.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return image_handler.list_private_images(client, page_size=page_size)


def delete_private_image(token: str, image_id: int) -> dict[str, object]:
    """Delete one of the account's private images.

    ``image_id`` is the numeric ``id`` field from :func:`list_private_images`,
    not the ``image-uuid`` string. Deletion is irreversible.

    :param token: AutoDL API token, typically copied from a browser session.
    :param image_id: Numeric private-image ID; must be positive.
    :returns: A mapping with ``image_id`` and ``deleted``.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return image_handler.delete_private_image(client, image_id)


def list_instances(
    token: str,
    *,
    page_size: int = instance_handler.DEFAULT_PAGE_SIZE,
    statuses: Iterable[str] = (),
    charge_types: Iterable[str] = (),
    sub_name: str = "",
    unbind_sub_user: bool = False,
    query: str = "",
) -> list[dict[str, object]]:
    """Return every instance visible to an API token.

    Every page is fetched, so the result is not limited by AutoDL's
    per-request page size.

    ``query`` is applied locally, after every page has been fetched, because
    the API has no keyword field. It matches case-insensitively against the
    instance UUID, name, region, machine alias, and GPU name fields.

    :param token: AutoDL API token, typically copied from a browser session.
    :param page_size: Instances requested per API call; must be positive.
    :param statuses: Only return instances whose status is one of these values.
    :param charge_types: Only return instances with one of these billing modes.
    :param sub_name: Only return instances whose bound sub-user name matches.
    :param unbind_sub_user: Only return instances with no bound sub-user.
    :param query: Only return instances matching this text; empty means no
        filtering.
    :returns: One mapping per instance; price fields are yuan floats.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.list_instances(
            client,
            page_size=page_size,
            statuses=statuses,
            charge_types=charge_types,
            sub_name=sub_name,
            unbind_sub_user=unbind_sub_user,
            query=query,
        )


def get_instance(token: str, instance_uuid: str) -> dict[str, object]:
    """Return one instance's configuration snapshot.

    The snapshot describes the base image, GPU allocation, host machine, and
    prices in yuan. It does not include the live status or connection details.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Instance UUID as returned by :func:`list_instances`.
    :returns: The snapshot mapping; price fields are yuan floats.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.get_instance(client, instance_uuid)


def create_instance(
    token: str,
    *,
    machine_id: str,
    base_image_uuid: str = "",
    private_image_uuid: str = "",
    gpu_amount: int = 1,
    instance_name: str = "",
    expand_data_disk: int = 0,
) -> dict[str, object]:
    """Order a pay-as-you-go instance on one machine.

    Exactly one of ``base_image_uuid`` and ``private_image_uuid`` must be set.
    AutoDL accepts the order immediately and returns the new instance UUID; the
    instance may take a moment to appear in :func:`list_instances`. This wrapper
    orders on a known machine only; resolving a region and GPU model to a
    machine is a CLI concern and is not part of the public API.

    :param token: AutoDL API token, typically copied from a browser session.
    :param machine_id: Machine to order on, as reported by the machine listing.
    :param base_image_uuid: Base-image UUID from :func:`list_images`.
    :param private_image_uuid: Private-image UUID from
        :func:`list_private_images`.
    :param gpu_amount: Number of GPUs to request; must be at least 1.
    :param instance_name: Optional instance name.
    :param expand_data_disk: Extra data-disk size in GB; must not be negative.
    :returns: A mapping with ``instance_uuid``, ``machine_id``, ``gpu_amount``,
        ``charge_type``, ``base_image_uuid``, ``private_image_uuid``,
        ``instance_name``, and ``expand_data_disk``.
    :raises ValueError: When ``machine_id`` is blank, ``gpu_amount`` is below 1,
        ``expand_data_disk`` is negative, or not exactly one image UUID is set.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.create_instance(
            client,
            machine_id=machine_id,
            base_image_uuid=base_image_uuid,
            private_image_uuid=private_image_uuid,
            gpu_amount=gpu_amount,
            instance_name=instance_name,
            expand_data_disk=expand_data_disk,
        )


def clone_instance(
    token: str,
    instance_uuid: str,
    *,
    machine_id: str,
    gpu_amount: int | None = None,
    instance_name: str = "",
    expand_data_disk: int = 0,
    copy_data_disk: bool = True,
    keep_src_user_service_address: bool = False,
) -> dict[str, object]:
    """Clone an instance onto a machine as a new pay-as-you-go order.

    The image and, unless ``gpu_amount`` is given, the GPU count are inherited
    from the source instance. AutoDL accepts the order immediately and returns
    the new instance UUID; the clone may take a moment to appear in
    :func:`list_instances`. This wrapper clones onto a known machine only;
    resolving a region and GPU model to a machine is a CLI concern and is not
    part of the public API.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Source instance UUID as returned by
        :func:`list_instances`.
    :param machine_id: Machine to clone onto, as reported by the machine
        listing.
    :param gpu_amount: Number of GPUs to request; ``None`` inherits the source
        instance's amount. Must be at least 1 when given.
    :param instance_name: Optional name for the clone.
    :param expand_data_disk: Extra data-disk size in GB; must not be negative.
    :param copy_data_disk: Whether to copy the source instance's data disk.
    :param keep_src_user_service_address: Whether to keep the source instance's
        user service address.
    :returns: A mapping with ``instance_uuid`` (the new clone),
        ``source_instance_uuid``, ``machine_id``, ``gpu_amount``,
        ``charge_type``, ``base_image_uuid``, ``private_image_uuid``,
        ``instance_name``, ``expand_data_disk``, ``copy_data_disk``, and
        ``keep_src_user_service_address``.
    :raises ValueError: When ``instance_uuid`` or ``machine_id`` is blank,
        ``gpu_amount`` is below 1, or ``expand_data_disk`` is negative.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        source = instance_handler.resolve_clone_source(client, instance_uuid)
        amount = source["gpu_amount"] if gpu_amount is None else gpu_amount
        return instance_handler.clone_instance(
            client,
            str(source["instance_uuid"]),
            machine_id=machine_id,
            base_image_uuid=str(source["base_image_uuid"]),
            private_image_uuid=str(source["private_image_uuid"]),
            gpu_amount=amount,
            instance_name=instance_name,
            expand_data_disk=expand_data_disk,
            copy_data_disk=copy_data_disk,
            keep_src_user_service_address=keep_src_user_service_address,
        )


def power_on(token: str, instance_uuid: str, *, non_gpu: bool = False) -> dict[str, object]:
    """Power an instance on, optionally in CPU-only mode.

    AutoDL accepts the request immediately and answers with a null ``data``
    payload; the instance may take a moment to start. With ``non_gpu`` the
    instance boots without its GPUs, as the web console's no-GPU mode does.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Instance UUID as returned by :func:`list_instances`.
    :param non_gpu: Start the instance in CPU-only (no-GPU) mode.
    :returns: A mapping with ``instance_uuid``, ``powered_on``, and ``non_gpu``.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.power_on(client, instance_uuid, non_gpu=non_gpu)


def power_off(token: str, instance_uuid: str) -> dict[str, object]:
    """Power an instance off.

    The data disk is preserved; AutoDL releases a powered-off instance after
    the retention window unless it is powered on again.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Instance UUID as returned by :func:`list_instances`.
    :returns: A mapping with ``instance_uuid`` and ``powered_off``.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.power_off(client, instance_uuid)


def schedule_shutdown(
    token: str,
    instance_uuid: str,
    *,
    shutdown_at: datetime,
) -> dict[str, object]:
    """Schedule an instance to shut down automatically at a given time.

    AutoDL accepts the request immediately and answers with a null ``data``
    payload. A naive ``shutdown_at`` is interpreted as Beijing time (UTC+8); an
    aware value is converted to UTC+8. Re-running the call with a new time
    modifies the existing schedule.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Instance UUID as returned by :func:`list_instances`.
    :param shutdown_at: Time at which the instance should shut down.
    :returns: A mapping with ``instance_uuid`` and ``shutdown_at`` (the
        Beijing-time wire string).
    :raises ValueError: When ``instance_uuid`` is blank.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.schedule_shutdown(client, instance_uuid, shutdown_at=shutdown_at)


def cancel_scheduled_shutdown(token: str, instance_uuid: str) -> dict[str, object]:
    """Cancel an instance's scheduled automatic shutdown.

    AutoDL accepts the request immediately and answers with a null ``data``
    payload.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Instance UUID as returned by :func:`list_instances`.
    :returns: A mapping with ``instance_uuid`` and ``shutdown_scheduled``.
    :raises ValueError: When ``instance_uuid`` is blank.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.cancel_scheduled_shutdown(client, instance_uuid)


def release_instance(token: str, instance_uuid: str) -> dict[str, object]:
    """Release an instance, deleting it and its data disk.

    Release is irreversible. AutoDL accepts the request immediately and answers
    with a null ``data`` payload; the instance does not need to be powered off
    first.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Instance UUID as returned by :func:`list_instances`.
    :returns: A mapping with ``instance_uuid`` and ``released``.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.release_instance(client, instance_uuid)


def reset_instance(token: str, instance_uuid: str) -> dict[str, object]:
    """Reset an instance, rebuilding its system disk.

    AutoDL accepts the request immediately and answers with a null ``data``
    payload. The system disk is restored from the instance's image; the data
    disk is preserved.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Instance UUID as returned by :func:`list_instances`.
    :returns: A mapping with ``instance_uuid`` and ``reset``.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.reset_instance(client, instance_uuid)


def change_image(token: str, instance_uuid: str, base_image_uuid: str) -> dict[str, object]:
    """Change an instance's image, rebuilding its system disk.

    AutoDL accepts the request immediately and answers with a null ``data``
    payload. The system disk is rebuilt from the new base image; the data disk
    is preserved.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Instance UUID as returned by :func:`list_instances`.
    :param base_image_uuid: Base-image UUID as returned by :func:`list_images`.
    :returns: A mapping with ``instance_uuid``, ``base_image_uuid``, and
        ``image_changed``.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.change_image(client, instance_uuid, base_image_uuid)


def rename_instance(token: str, instance_uuid: str, instance_name: str) -> dict[str, object]:
    """Rename an instance.

    AutoDL answers with a null ``data`` payload. The new name is immediately
    visible in :func:`list_instances`.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Instance UUID as returned by :func:`list_instances`.
    :param instance_name: New instance name.
    :returns: A mapping with ``instance_uuid``, ``instance_name``, and
        ``renamed``.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.rename_instance(client, instance_uuid, instance_name)


def save_image(
    token: str,
    instance_uuid: str,
    image_name: str,
    *,
    try_again: bool = False,
) -> dict[str, object]:
    """Save an instance as a custom image.

    AutoDL accepts the request and answers with a null ``data`` payload; the
    image may take longer to appear under the account's private images.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Instance UUID as returned by :func:`list_instances`.
    :param image_name: Name for the new image.
    :param try_again: Whether AutoDL should retry a previously failed save.
    :returns: A mapping with ``instance_uuid``, ``image_name``, ``try_again``,
        and ``saved``.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.save_image(
            client,
            instance_uuid,
            image_name,
            try_again=try_again,
        )


def wait_for_instance(
    token: str,
    instance_uuid: str,
    *,
    until: str = "running",
    interval: float = 10.0,
    timeout: float = 0.0,
    retry: int = 0,
) -> dict[str, object]:
    """Poll until an instance reaches a target status.

    ``running`` succeeds on the ``running`` and CPU-only (``cpu``) statuses;
    ``shutdown`` and ``released`` wait for those statuses respectively, with a
    missing instance counting as released. When ``timeout`` is ``0`` there is
    no deadline and the call blocks until the target is reached.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Instance UUID as returned by :func:`list_instances`.
    :param until: ``running``, ``shutdown``, or ``released``.
    :param interval: Seconds between status checks; must be positive.
    :param timeout: Maximum seconds to wait; ``0`` waits until interrupted.
    :param retry: Consecutive transient polling errors to retry; ``0`` disables
        retries.
    :returns: A mapping with ``instance_uuid``, ``status``, ``waited_seconds``,
        and ``instance``.
    :raises ValueError: When an argument is invalid.
    :raises TimeoutError: When ``timeout`` expires before the target status.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.wait_for_instance(
            client,
            instance_uuid,
            until=until,
            interval=interval,
            timeout=timeout,
            retry=retry,
        )


def wait_for_private_image(
    token: str,
    *,
    instance_uuid: str,
    image_name: str,
    previous_statuses: dict[int, str] | None = None,
    interval: float = 10.0,
    timeout: float = 0.0,
    retry: int = 0,
) -> dict[str, object]:
    """Poll until a private-image save finishes.

    Only images whose source instance UUID and name match exactly are
    considered. When ``previous_statuses`` is ``None``, the matching images are
    snapshotted at call time so an older finished or failed save is ignored.
    When ``timeout`` is ``0`` there is no deadline and the call blocks until
    the save finishes.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Source instance UUID of the save.
    :param image_name: Name the image is being saved under.
    :param previous_statuses: Snapshot taken before the save request, or
        ``None`` to take one now.
    :param interval: Seconds between status checks; must be positive.
    :param timeout: Maximum seconds to wait; ``0`` waits until interrupted.
    :param retry: Consecutive transient polling errors to retry; ``0`` disables
        retries.
    :returns: A mapping with ``image_uuid``, ``image_id``, ``name``,
        ``status``, ``waited_seconds``, and ``image``.
    :raises ValueError: When an argument is invalid.
    :raises TimeoutError: When ``timeout`` expires before the save finishes.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        previous = previous_statuses
        if previous is None:
            previous = image_handler.private_image_status_snapshot(client, instance_uuid, image_name)
        return image_handler.wait_for_private_image(
            client,
            instance_uuid=instance_uuid,
            image_name=image_name,
            previous_statuses=previous,
            interval=interval,
            timeout=timeout,
            retry=retry,
        )


def get_current_user(token: str) -> dict[str, object]:
    """Return the user owning an API token.

    :param token: AutoDL API token, typically copied from a browser session.
    :returns: The user detail mapping.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return auth_handler.get_current_user(client)
