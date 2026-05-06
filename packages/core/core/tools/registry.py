"""Tool registry: decorator, dispatcher, and the schema export.

The module presents three call-site primitives:

* :func:`tool` — decorator that registers an async function as a tool,
  capturing its name, description (from the docstring), and a JSON
  schema derived from its type-hinted parameters.
* :func:`all_tools` — returns the registered tools' schemas in the
  shape LiveKit Agents expects (``name``, ``description``,
  ``parameters``).
* :func:`dispatch` — invokes a registered handler by name, passing a
  :class:`ToolContext` (current user + a logger bound with
  ``tool_name``). Errors are caught and returned as ``{"error": str}``
  so the model receives a structured failure rather than crashing the
  session.

Schema derivation is deliberately small. We support the JSON-encodable
primitives a realtime model is realistically asked to call with —
``str``, ``int``, ``float``, ``bool``. Defaults become "not required"
in the schema. Anything richer (pydantic models, lists, unions) is
out of scope for this slice and would be added by extending
:func:`_schema_for_param` once a real tool needs it.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast, overload

from structlog.stdlib import BoundLogger

from core.auth import User

# Tool handlers are async, accept a `ToolContext` plus their own typed
# kwargs, and return a string (what the model speaks back) or a
# JSON-serialisable mapping (rare; reserved for structured tool
# outputs). The registry stores them with their schemas attached.
ToolHandler = Callable[..., Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Per-call context handed to every tool handler.

    Carries the authenticated end-user (resolved from the LiveKit
    participant identity at session start) plus a structlog logger
    pre-bound with ``tool_name`` so every line a handler emits is
    correlated to the specific tool invocation.

    ``session_id`` is the LiveKit room name and serves as the in-process
    key for any per-session state a tool wants to keep — the triage
    slot store reads it to isolate concurrent users. Defaulted to the
    empty string for tests that build a context without a session.

    ``supabase_access_token`` is the user's Supabase JWT, propagated
    through to RLS-scoped database calls (see :mod:`core.preferences`).
    Optional because not every tool touches the database — and because
    the session-bootstrap path that supplies it is wired up
    incrementally; tools that need it must check and degrade gracefully
    when it is absent.
    """

    user: User
    log: BoundLogger
    session_id: str = ""
    supabase_access_token: str | None = None


@dataclass(frozen=True, slots=True)
class ToolSchema:
    """JSON-schema description of a registered tool.

    The shape mirrors what realtime models (OpenAI Realtime, others)
    expect under their ``tools`` array: ``name``, ``description``,
    ``parameters`` (a JSON schema object).
    """

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(slots=True)
class _Registration:
    """Internal pairing of a registered handler with its schema.

    Kept private so the public API stays stable if we ever need to add
    more bookkeeping (rate limits, capability flags, etc.) later.
    """

    schema: ToolSchema
    handler: ToolHandler
    accepts_context: bool = field(default=True)


# Module-level singleton. Tools are registered as a side effect of
# importing the module that defines them (see `core.tools.examples`).
# A class-based registry would be cleaner for multi-tenant test
# isolation, but YAGNI: the agent worker is single-tenant per process,
# and tests use `_clear_registry_for_tests` when they need a clean
# slate.
_REGISTRY: dict[str, _Registration] = {}


# --- Schema derivation -------------------------------------------------------

# Map of supported Python primitive types to their JSON-schema
# equivalents. Anything outside this map raises at decoration time —
# better to fail loudly the moment a developer writes an unsupported
# type than to silently emit a schema the model can't reason about.
_PRIMITIVE_TYPES: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _schema_for_param(
    name: str,
    param: inspect.Parameter,
    annotation: Any,
    fn_name: str,
) -> dict[str, Any]:
    """Build the JSON schema fragment for a single function parameter.

    `annotation` is the resolved type (from :func:`typing.get_type_hints`)
    rather than the raw `param.annotation` — under
    ``from __future__ import annotations`` the latter is a string.
    """
    if annotation is inspect.Parameter.empty:
        raise TypeError(
            f"@tool {fn_name!r}: parameter {name!r} is missing a type annotation. "
            "Tool parameters must be typed so the schema can be derived."
        )
    json_type = _PRIMITIVE_TYPES.get(annotation)
    if json_type is None:
        raise TypeError(
            f"@tool {fn_name!r}: parameter {name!r} has unsupported type "
            f"{annotation!r}. Supported: {sorted(t.__name__ for t in _PRIMITIVE_TYPES)}."
        )
    fragment: dict[str, Any] = {"type": json_type}
    if param.default is not inspect.Parameter.empty:
        fragment["default"] = param.default
    return fragment


def _build_schema(
    fn: ToolHandler,
    *,
    name: str,
    description: str,
) -> tuple[ToolSchema, bool]:
    """Inspect `fn` and produce its :class:`ToolSchema`.

    Returns the schema and whether the handler's first parameter is a
    :class:`ToolContext` (so the dispatcher knows whether to inject one).
    """
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    # Resolve string annotations (PEP 563 / `from __future__ import
    # annotations`) into real types so schema derivation can compare
    # against `str`, `int`, etc.
    try:
        hints = typing.get_type_hints(fn)
    except Exception as exc:  # pragma: no cover — pathological hint
        raise TypeError(f"@tool {name!r}: cannot resolve type hints: {exc}") from exc

    accepts_context = bool(params) and hints.get(params[0].name) is ToolContext
    arg_params = params[1:] if accepts_context else params

    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []
    for param in arg_params:
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise TypeError(
                f"@tool {name!r}: *args / **kwargs are not supported in tool signatures."
            )
        annotation = hints.get(param.name, inspect.Parameter.empty)
        properties[param.name] = _schema_for_param(param.name, param, annotation, name)
        if param.default is inspect.Parameter.empty:
            required.append(param.name)

    parameters: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        parameters["required"] = required

    return (
        ToolSchema(name=name, description=description, parameters=parameters),
        accepts_context,
    )


# --- Decorator + dispatcher --------------------------------------------------


@overload
def tool[F: ToolHandler](fn: F, /) -> F: ...
@overload
def tool[F: ToolHandler](
    *,
    name: str | None = ...,
    description: str | None = ...,
) -> Callable[[F], F]: ...
def tool[F: ToolHandler](
    fn: F | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> F | Callable[[F], F]:
    """Register an async function as a tool.

    Usage::

        @tool
        async def get_weather(city: str) -> str:
            \"\"\"Look up the current weather in a city.\"\"\"
            ...

    The function name becomes the tool name unless ``name`` is given;
    the first paragraph of the docstring becomes the description
    unless ``description`` is given. Type-hinted parameters become the
    JSON-schema arguments. A first parameter typed as
    :class:`ToolContext` is recognised by the dispatcher and injected
    automatically — the model never sees it in the schema.
    """

    def decorator(func: F) -> F:
        original = func  # preserve the un-narrowed alias for the return.
        if not inspect.iscoroutinefunction(func):
            raise TypeError(
                f"@tool {func.__name__!r}: tools must be async (declared with `async def`)."
            )
        tool_name = name or func.__name__
        if not (description or (func.__doc__ or "").strip()):
            raise ValueError(
                f"@tool {tool_name!r}: missing description. Provide a docstring "
                "or pass description='...'."
            )
        tool_description = description or _first_paragraph(func.__doc__ or "")
        schema, accepts_context = _build_schema(
            cast(ToolHandler, func), name=tool_name, description=tool_description
        )
        _REGISTRY[tool_name] = _Registration(
            schema=schema,
            handler=cast(ToolHandler, func),
            accepts_context=accepts_context,
        )
        return original

    if fn is not None:
        return decorator(fn)
    return decorator


def _first_paragraph(doc: str) -> str:
    """Return the first paragraph of a docstring, trimmed."""
    stripped = inspect.cleandoc(doc)
    para, _, _ = stripped.partition("\n\n")
    return para.strip()


def all_tools() -> list[ToolSchema]:
    """Return every registered tool's schema.

    The agent passes this list to the LiveKit Agent at session start
    so the realtime model knows what it can call. Order follows
    registration order; downstream code should not depend on it.
    """
    return [reg.schema for reg in _REGISTRY.values()]


def get_tool(name: str) -> ToolSchema | None:
    """Look up a single tool's schema by name, or ``None`` if unknown."""
    reg = _REGISTRY.get(name)
    return reg.schema if reg is not None else None


async def dispatch(
    name: str,
    args: dict[str, Any],
    ctx: ToolContext,
) -> Any:
    """Invoke the registered handler for ``name`` with ``args``.

    Returns whatever the handler returns. On any exception, returns
    ``{"error": str(exc)}`` and logs the failure — the realtime model
    receives a structured failure it can verbalise rather than the
    session crashing on a tool bug or transient HTTP error.
    """
    reg = _REGISTRY.get(name)
    if reg is None:
        # An unknown name is a contract bug: the model called a tool
        # that wasn't registered. Surface it like any other error so
        # the agent can apologise verbally instead of crashing.
        return {"error": f"unknown tool {name!r}"}

    bound_log = ctx.log.bind(tool_name=name)
    handler_ctx = ToolContext(
        user=ctx.user,
        log=bound_log,
        session_id=ctx.session_id,
        supabase_access_token=ctx.supabase_access_token,
    )

    bound_log.info("tool.dispatch.start", args=args)
    try:
        if reg.accepts_context:
            result = await reg.handler(handler_ctx, **args)
        else:
            result = await reg.handler(**args)
    except Exception as exc:  # noqa: BLE001 — intentional broad catch
        bound_log.warning("tool.dispatch.error", error=str(exc), error_type=type(exc).__name__)
        return {"error": str(exc)}

    bound_log.info("tool.dispatch.success")
    return result


# --- Test helpers ------------------------------------------------------------


def _clear_registry_for_tests() -> None:
    """Wipe the registry. Test-only escape hatch."""
    _REGISTRY.clear()


__all__ = [
    "ToolContext",
    "ToolHandler",
    "ToolSchema",
    "all_tools",
    "dispatch",
    "get_tool",
    "tool",
]
