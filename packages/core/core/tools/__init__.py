"""Tool registration and dispatch for the agent.

`core.tools` is the single seam through which downstream developers
add capabilities to the assistant. The contract is intentionally
small: write an async function, decorate it with :func:`tool`, accept
the optional :class:`ToolContext` and your typed arguments, and return
a string. The decorator captures the JSON schema from your type hints
and the docstring; the registry dispatches with structured logging
and error trapping.

The module is deep by design — call sites import three names
(:func:`tool`, :func:`all_tools`, :func:`dispatch`) and never see the
schema-derivation, error-mapping, or logging-binding details.
"""

from __future__ import annotations

# Importing the examples module triggers @tool registration as a side
# effect, so the canonical example tools are discoverable on first
# import of `core.tools`. Downstream developers wire up their own
# tools the same way: `import myapp.tools` once at process start.
from core.tools import examples as examples  # noqa: F401
from core.tools import memory as memory  # noqa: F401
from core.tools import preferences as preferences  # noqa: F401
from core.tools.registry import (
    ToolContext,
    ToolHandler,
    ToolSchema,
    all_tools,
    dispatch,
    get_tool,
    tool,
)

__all__ = [
    "ToolContext",
    "ToolHandler",
    "ToolSchema",
    "all_tools",
    "dispatch",
    "get_tool",
    "tool",
]
