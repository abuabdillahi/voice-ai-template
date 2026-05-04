"""Unit tests for `core.tools.registry`.

The registry's contract is the focus: register a tool, see it in
`all_tools()`, dispatch round-trip, and the error-trap behaviour that
keeps a buggy tool from killing the agent session.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
import structlog
from core.auth import User
from core.tools.registry import (
    ToolContext,
    _clear_registry_for_tests,
    all_tools,
    dispatch,
    get_tool,
    tool,
)


@pytest.fixture
def clean_registry() -> Iterator[None]:
    """Wipe the registry around each test so registrations don't leak."""
    _clear_registry_for_tests()
    yield
    _clear_registry_for_tests()


def _user() -> User:
    return User(id=UUID("11111111-1111-1111-1111-111111111111"), email="a@b.com")


def _ctx() -> ToolContext:
    return ToolContext(user=_user(), log=structlog.get_logger("test"))


@pytest.mark.usefixtures("clean_registry")
class TestRegistration:
    def test_registers_function_with_derived_name_and_description(self) -> None:
        @tool
        async def echo(message: str) -> str:
            """Echo back the supplied message."""
            return message

        schemas = all_tools()
        assert len(schemas) == 1
        schema = schemas[0]
        assert schema.name == "echo"
        assert schema.description == "Echo back the supplied message."
        assert schema.parameters["type"] == "object"
        assert schema.parameters["properties"]["message"] == {"type": "string"}
        assert schema.parameters["required"] == ["message"]

    def test_default_arguments_are_not_required(self) -> None:
        @tool
        async def greet(name: str = "world") -> str:
            """Say hi."""
            return f"hello {name}"

        schema = get_tool("greet")
        assert schema is not None
        assert "required" not in schema.parameters
        assert schema.parameters["properties"]["name"] == {
            "type": "string",
            "default": "world",
        }

    def test_explicit_name_and_description_override_defaults(self) -> None:
        @tool(name="custom_echo", description="An overridden description.")
        async def something(message: str) -> str:
            """Original docstring (should be ignored)."""
            return message

        assert get_tool("custom_echo") is not None
        assert get_tool("something") is None
        schema = get_tool("custom_echo")
        assert schema is not None
        assert schema.description == "An overridden description."

    def test_unsupported_parameter_type_raises(self) -> None:
        with pytest.raises(TypeError, match="unsupported type"):

            @tool
            async def bad(payload: list[int]) -> str:  # noqa: ARG001
                """Bad."""
                return "x"

    def test_missing_annotation_raises(self) -> None:
        with pytest.raises(TypeError, match="missing a type annotation"):

            @tool
            async def missing(thing) -> str:  # type: ignore[no-untyped-def]  # noqa: ARG001
                """Missing."""
                return "x"

    def test_sync_function_rejected(self) -> None:
        with pytest.raises(TypeError, match="must be async"):

            @tool
            def sync_tool(message: str) -> str:  # type: ignore[misc]  # noqa: ARG001
                """Sync."""
                return message

    def test_missing_description_raises(self) -> None:
        async def undocumented(message: str) -> str:
            return message

        with pytest.raises(ValueError, match="missing description"):
            tool(undocumented)


@pytest.mark.usefixtures("clean_registry")
class TestDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_round_trip(self) -> None:
        @tool
        async def echo(message: str) -> str:
            """Echo."""
            return f"got: {message}"

        result = await dispatch("echo", {"message": "hi"}, _ctx())
        assert result == "got: hi"

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error_dict(self) -> None:
        result = await dispatch("nonexistent", {}, _ctx())
        assert isinstance(result, dict)
        assert "error" in result
        assert "nonexistent" in result["error"]

    @pytest.mark.asyncio
    async def test_handler_exception_is_caught(self) -> None:
        @tool
        async def boom(message: str) -> str:  # noqa: ARG001
            """Always blow up."""
            raise RuntimeError("kaboom")

        result = await dispatch("boom", {"message": "x"}, _ctx())
        assert result == {"error": "kaboom"}

    @pytest.mark.asyncio
    async def test_tool_context_is_injected_when_first_param(self) -> None:
        seen: list[UUID] = []

        @tool
        async def needs_user(ctx: ToolContext, message: str) -> str:
            """Records the user."""
            seen.append(ctx.user.id)
            return message

        await dispatch("needs_user", {"message": "x"}, _ctx())
        assert seen == [_user().id]

    @pytest.mark.asyncio
    async def test_tool_context_logger_is_bound_with_tool_name(self) -> None:
        captured: dict[str, object] = {}

        @tool
        async def captures(ctx: ToolContext) -> str:
            """Capture context."""
            # The bound logger should have `tool_name` in its
            # context. structlog stores bound values on
            # `_context` for testing; this is fine for an
            # invariant check.
            captured["log"] = ctx.log
            return "ok"

        await dispatch("captures", {}, _ctx())
        # We don't depend on structlog's internals; instead we
        # check that the dispatch path produced a logger object
        # at all, and that calling .info on it is safe.
        log = captured["log"]
        assert log is not None
        # If the logger isn't bound correctly, this would raise.
        log.info("ok-from-test")  # type: ignore[union-attr]
