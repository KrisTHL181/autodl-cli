"""Location of the per-user autodl-toolkit data directory.

Everything that would otherwise hardcode ``~/.autodl-cli`` derives from
:func:`autodl_home`, so a test run or sandbox can relocate the whole tree with
one environment variable.

TODO: implement :func:`autodl_home` with the same contract as
``zhihu_cli.paths.zhihu_home`` — non-empty override wins, ``~`` is expanded,
and the directory is not created.
"""

from __future__ import annotations

from pathlib import Path

HOME_ENV = "AUTODL_CLI_HOME"

#: Leaf directory used when the environment variable is unset.
_DEFAULT_DIRNAME = ".autodl-cli"


def autodl_home() -> Path:
    """Return the root of the per-user autodl-toolkit data tree.

    ``AUTODL_CLI_HOME`` overrides the default when set to a non-empty value;
    a leading ``~`` in the override is expanded. The directory is not created
    here — callers that need it create it themselves.

    :returns: The configured data directory, or ``~/.autodl-cli``.
    """
    ...
