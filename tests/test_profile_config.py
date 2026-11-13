"""Tests for profile-aware configuration storage."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from autodl_cli import config as config_module

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10
    import tomli as tomllib

#: Fingerprint-shaped value used to make round-trip failures obvious.
_FINGERPRINT = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def home(monkeypatch, tmp_path: Path) -> Path:
    """Point ``AUTODL_CLI_HOME`` at an isolated directory and clear the env pin.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param tmp_path: Per-test temporary directory.
    :returns: The redirected home directory.
    """
    target = tmp_path / "autodl-home"
    monkeypatch.setenv("AUTODL_CLI_HOME", str(target))
    monkeypatch.delenv(config_module.PROFILE_ENV, raising=False)
    return target


def _read_toml(path: Path) -> dict[str, object]:
    """Read a TOML file.

    :param path: File to read.
    :returns: The parsed mapping.
    """
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _mode(path: Path) -> int:
    """Return a path's permission bits.

    :param path: File or directory.
    :returns: The permission bits, for example ``0o600``.
    """
    return stat.S_IMODE(path.stat().st_mode)


def _seed_profile(name: str, token: str) -> None:
    """Create a profile holding one token.

    :param name: Profile name.
    :param token: Token to store.
    """
    with config_module.use_profile(name):
        config_module.save_config({"token": token})


def test_save_splits_global_and_profile_files(home: Path) -> None:
    """Credentials land in the profile and everything else in ``config.toml``."""
    config_module.save_config(
        {
            "token": "fake-token",
            "phone_area": "+86",
            "device_fingerprint": _FINGERPRINT,
            "default_region": "west-b",
        }
    )

    profiles_dir = home / "profiles"
    profile_file = profiles_dir / "default.toml"
    global_file = home / "config.toml"

    assert _read_toml(profile_file) == {"token": "fake-token", "phone_area": "+86"}
    assert _read_toml(global_file) == {"device_fingerprint": _FINGERPRINT, "default_region": "west-b"}
    assert config_module.load_config() == {
        "token": "fake-token",
        "phone_area": "+86",
        "device_fingerprint": _FINGERPRINT,
        "default_region": "west-b",
    }
    assert not (home / "active_profile").exists()


def test_layout_is_private(home: Path) -> None:
    """The data directories are 0700 and every written file is 0600."""
    config_module.save_config({"token": "fake-token", "device_fingerprint": _FINGERPRINT})

    assert _mode(home) == 0o700
    assert _mode(home / "profiles") == 0o700
    assert _mode(home / "profiles" / "default.toml") == 0o600
    assert _mode(home / "config.toml") == 0o600


def test_save_preserves_other_profiles(home: Path) -> None:
    """Writing one profile leaves the other profiles untouched."""
    _seed_profile("work", "work-token")

    with config_module.use_profile("work"):
        loaded = config_module.load_config()
        loaded["device_fingerprint"] = _FINGERPRINT
        config_module.save_config(loaded)

    assert _read_toml(home / "profiles" / "work.toml") == {"token": "work-token"}
    assert not (home / "profiles" / "default.toml").exists()


def test_save_preserves_unknown_global_keys(home: Path) -> None:
    """A partial credential save does not drop unrelated global settings."""
    config_module.save_config({"default_region": "west-b"})

    config_module.save_config({"token": "fake-token"})

    assert _read_toml(home / "config.toml") == {"default_region": "west-b"}


def test_save_never_changes_the_active_pointer(home: Path) -> None:
    """Credential writes leave profile selection alone."""
    config_module.save_config({"token": "first"})
    assert not (home / "active_profile").exists()

    config_module.switch_profile("default")
    config_module.save_config({"token": "second"})

    assert (home / "active_profile").read_text(encoding="utf-8").strip() == "default"


def test_profile_isolation(home: Path) -> None:
    """Each profile keeps its own token and phone area."""
    _seed_profile("a", "token-a")
    _seed_profile("b", "token-b")

    with config_module.use_profile("a"):
        assert config_module.get_token() == "token-a"
    with config_module.use_profile("b"):
        assert config_module.get_token() == "token-b"
    assert config_module.load_config().get("token") is None


def test_precedence_flag_env_pointer_default(home: Path, monkeypatch) -> None:
    """The selection follows flag > env > active file > default."""
    assert config_module.current_profile() == ("default", "default")

    config_module.set_active_profile("pointer")
    assert config_module.current_profile() == ("pointer", "active")

    monkeypatch.setenv(config_module.PROFILE_ENV, "from-env")
    assert config_module.current_profile() == ("from-env", "env")

    with config_module.use_profile("from-flag"):
        assert config_module.current_profile() == ("from-flag", "flag")


def test_use_profile_restores_previous_selection(home: Path) -> None:
    """Leaving the context manager restores normal resolution."""
    with config_module.use_profile("work"):
        assert config_module.current_profile()[0] == "work"

    assert config_module.current_profile() == ("default", "default")


def test_invalid_env_name_is_rejected(home: Path, monkeypatch) -> None:
    """``AUTODL_PROFILE`` is validated like the flag."""
    monkeypatch.setenv(config_module.PROFILE_ENV, "bad/name")

    with pytest.raises(ValueError, match="Invalid profile name"):
        config_module.current_profile()


def test_legacy_credentials_are_migrated(home: Path) -> None:
    """Top-level credentials move into ``profiles/default.toml`` on first load."""
    home.mkdir(parents=True)
    legacy = (
        f'token = "legacy-token"\nphone_area = "+1"\ndevice_fingerprint = "{_FINGERPRINT}"\ndefault_region = "west-b"\n'
    )
    (home / "config.toml").write_text(legacy, encoding="utf-8")

    loaded = config_module.load_config()

    assert loaded == {
        "token": "legacy-token",
        "phone_area": "+1",
        "device_fingerprint": _FINGERPRINT,
        "default_region": "west-b",
    }
    assert _read_toml(home / "profiles" / "default.toml") == {
        "token": "legacy-token",
        "phone_area": "+1",
    }
    assert _read_toml(home / "config.toml") == {
        "device_fingerprint": _FINGERPRINT,
        "default_region": "west-b",
    }
    assert (home / "active_profile").read_text(encoding="utf-8").strip() == "default"

    # A second load is a no-op.
    assert config_module.load_config() == loaded


def test_legacy_migration_does_not_overwrite_existing_default(home: Path) -> None:
    """The migration is skipped once ``profiles/default.toml`` exists."""
    home.mkdir(parents=True)
    _seed_profile("default", "profile-token")
    (home / "config.toml").write_text('token = "legacy-token"\n', encoding="utf-8")

    assert config_module.load_config() == {"token": "profile-token"}
    assert _read_toml(home / "profiles" / "default.toml") == {"token": "profile-token"}
    assert _read_toml(home / "config.toml") == {"token": "legacy-token"}


@pytest.mark.parametrize(
    "name",
    ["", " ", "a/b", "../escape", ".hidden", "-dash", "_under", "with space", "a" * 65],
)
def test_invalid_profile_names_are_rejected(name: str) -> None:
    """Path separators, leading punctuation, and overlong names are refused."""
    with pytest.raises(ValueError, match="Invalid profile name"):
        config_module.validate_profile_name(name)


@pytest.mark.parametrize("name", ["default", "work", "Work-2", "a.b_c", "0", "a" * 64])
def test_valid_profile_names_are_accepted(name: str) -> None:
    """Letters, digits, dots, underscores, and hyphens are allowed."""
    assert config_module.validate_profile_name(name) == name


def test_delete_clears_pointer_when_profile_was_active(home: Path) -> None:
    """Deleting the active profile removes the pointer and falls back to default."""
    _seed_profile("work", "work-token")
    config_module.switch_profile("work")

    config_module.delete_profile("work")

    assert not (home / "profiles" / "work.toml").exists()
    assert not (home / "active_profile").exists()
    assert config_module.current_profile() == ("default", "default")


def test_delete_keeps_pointer_for_other_active_profile(home: Path) -> None:
    """Deleting an inactive profile leaves the pointer alone."""
    _seed_profile("a", "token-a")
    _seed_profile("b", "token-b")
    config_module.switch_profile("b")

    config_module.delete_profile("a")

    assert (home / "active_profile").read_text(encoding="utf-8").strip() == "b"


def test_delete_missing_profile_raises(home: Path) -> None:
    """A profile can only be deleted while its file exists."""
    with pytest.raises(ValueError, match="does not exist"):
        config_module.delete_profile("missing")


def test_switch_requires_existing_profile_but_allows_default(home: Path) -> None:
    """Switching checks for the file, except for the implicit default."""
    with pytest.raises(ValueError, match="does not exist"):
        config_module.switch_profile("missing")

    config_module.switch_profile("default")
    assert (home / "active_profile").read_text(encoding="utf-8").strip() == "default"


def test_removing_missing_key_creates_no_files(home: Path) -> None:
    """Clearing a value that was never stored must not create the tree."""
    config_module.set_token(None)
    config_module.set_phone_area(None)
    config_module.set_device_fingerprint(None)
    config_module.set_base_url(None)

    assert not (home / "config.toml").exists()
    assert not (home / "profiles").exists()
    assert not (home / "active_profile").exists()


def test_profile_has_token_reports_authentication(home: Path) -> None:
    """``profile_has_token`` reflects the per-profile token."""
    _seed_profile("work", "work-token")

    assert config_module.profile_has_token("work") is True
    assert config_module.profile_has_token("default") is False
    assert config_module.list_profiles() == ["default", "work"]
