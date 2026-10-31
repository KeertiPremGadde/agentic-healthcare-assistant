"""`ClinicTools` over MCP: the graph calls the clinic MCP server (stdio subprocess) through
`langchain-mcp-adapters`.

Two details worth knowing:
- One persistent session for the whole conversation. `MultiServerMCPClient.get_tools()` without
  a session would spawn a new server process for every single tool call.
- The client runs on its own event loop in a background thread. On Windows the app's loop must be
  a SelectorEventLoop (psycopg async), which cannot spawn subprocesses; the MCP client's loop is
  a ProactorEventLoop, which can (core/aio.py). Calls are handed over with
  `run_coroutine_threadsafe`. On Linux this is simply an extra loop.
"""

import asyncio
import concurrent.futures
import contextlib
import sys
import threading
import uuid
from datetime import date, datetime
from types import TracebackType
from typing import Any, Self, TypeVar

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from pydantic import BaseModel

from medagent.core.aio import new_subprocess_loop
from medagent.core.config import Settings, get_settings
from medagent.tools.clinic import ToolError
from medagent.tools.models import (
    AppointmentList,
    Availability,
    BookingResult,
    CancelResult,
    DoctorInfo,
    DoctorList,
    NearbyClinics,
    SlotCheck,
    TimeOfDay,
)

M = TypeVar("M", bound=BaseModel)
SERVER = "clinic"


class MCPToolError(ToolError):
    """The MCP server reported a failure, or returned no structured result."""


def server_env(settings: Settings) -> dict[str, str]:
    """Only what the server needs (merged by the SDK with a safe default environment such as
    PATH). The Anthropic key and other secrets are not passed on."""
    env = {
        "DATABASE_URL": settings.database_url,
        "CLINIC_TIMEZONE": settings.clinic_timezone,
        "SLOT_MINUTES": str(settings.slot_minutes),
        "OVERPASS_URL": settings.overpass_url,
    }
    if settings.google_service_account_file:
        env["GOOGLE_SERVICE_ACCOUNT_FILE"] = settings.google_service_account_file
    if settings.google_calendar_id:
        env["GOOGLE_CALENDAR_ID"] = settings.google_calendar_id
    return env


def _jsonable(args: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in args.items():
        if value is None:
            continue  # let the server apply its defaults
        out[key] = value.isoformat() if isinstance(value, date | datetime) else value
    return out


class MCPClinicTools:
    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        self._client = MultiServerMCPClient(
            {
                SERVER: {
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": ["-m", "medagent.mcp_server"],
                    "env": server_env(settings),
                }
            }
        )
        self._loop = new_subprocess_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="mcp-client", daemon=True
        )
        self._ready: concurrent.futures.Future[None] = concurrent.futures.Future()
        self._owner: concurrent.futures.Future[None] | None = None
        self._stop: asyncio.Event | None = None
        self._tools: dict[str, BaseTool] = {}

    # -- lifecycle -----------------------------------------------------------------------
    async def _own_session(self) -> None:
        """Holds the session open in one task (anyio requires enter and exit in the same task)."""
        self._stop = asyncio.Event()
        try:
            async with self._client.session(SERVER) as session:
                tools = await load_mcp_tools(session, handle_tool_errors=False)
                self._tools = {tool.name: tool for tool in tools}
                self._ready.set_result(None)
                await self._stop.wait()
        except BaseException as exc:
            if not self._ready.done():
                self._ready.set_exception(exc)
            raise

    async def __aenter__(self) -> Self:
        self._thread.start()
        self._owner = asyncio.run_coroutine_threadsafe(self._own_session(), self._loop)
        await asyncio.wrap_future(self._ready)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._owner is not None:
            # It may already have failed at start-up; we are shutting down either way.
            with contextlib.suppress(Exception):
                await asyncio.wrap_future(self._owner)
        self._loop.call_soon_threadsafe(self._loop.stop)
        await asyncio.to_thread(self._thread.join, 5)
        self._loop.close()

    # -- calls ---------------------------------------------------------------------------
    async def _invoke(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools[name]
        call = {"type": "tool_call", "id": uuid.uuid4().hex, "name": name, "args": args}
        message = await tool.ainvoke(call)
        artifact = getattr(message, "artifact", None) or {}
        structured = artifact.get("structured_content") if isinstance(artifact, dict) else None
        if structured is None:
            raise MCPToolError(f"{name}: no structured result")
        return dict(structured)

    async def _call(self, tool: str, model: type[M], /, **args: Any) -> M:
        # Positional-only: tool arguments such as `name` (a doctor's name) must not collide.
        future = asyncio.run_coroutine_threadsafe(self._invoke(tool, _jsonable(args)), self._loop)
        try:
            result = await asyncio.wrap_future(future)
        except MCPToolError:
            raise
        except Exception as exc:  # protocol or server-side error
            raise MCPToolError(f"{tool}: {type(exc).__name__}") from exc
        return model.model_validate(result)

    # -- ClinicTools ---------------------------------------------------------------------
    async def get_doctor(self, doctor_id: int) -> DoctorInfo | None:
        result = await self._call("get_doctor", DoctorList, doctor_id=doctor_id)
        return result.doctors[0] if result.doctors else None

    async def search_doctors(
        self,
        specialty: str | None = None,
        city: str | None = None,
        language: str | None = None,
        name: str | None = None,
        limit: int = 5,
    ) -> DoctorList:
        return await self._call(
            "search_doctors",
            DoctorList,
            specialty=specialty,
            city=city,
            language=language,
            name=name,
            limit=limit,
        )

    async def check_availability(
        self,
        doctor_id: int,
        from_day: date,
        days: int = 1,
        time_of_day: TimeOfDay | None = None,
        after: datetime | None = None,
        limit: int = 5,
    ) -> Availability:
        return await self._call(
            "check_availability",
            Availability,
            doctor_id=doctor_id,
            from_day=from_day,
            days=days,
            time_of_day=time_of_day,
            after=after,
            limit=limit,
        )

    async def check_slot(self, doctor_id: int, start: datetime) -> SlotCheck:
        return await self._call("check_slot", SlotCheck, doctor_id=doctor_id, start=start)

    async def book_appointment(
        self, patient_id: int, doctor_id: int, start: datetime
    ) -> BookingResult:
        return await self._call(
            "book_appointment",
            BookingResult,
            patient_id=patient_id,
            doctor_id=doctor_id,
            start=start,
        )

    async def list_appointments(
        self, patient_id: int, upcoming_only: bool = True
    ) -> AppointmentList:
        return await self._call(
            "list_appointments", AppointmentList, patient_id=patient_id, upcoming_only=upcoming_only
        )

    async def cancel_appointment(self, patient_id: int, appointment_id: int) -> CancelResult:
        return await self._call(
            "cancel_appointment", CancelResult, patient_id=patient_id, appointment_id=appointment_id
        )

    async def find_nearby_clinics(self, city: str) -> NearbyClinics:
        return await self._call("find_nearby_clinics", NearbyClinics, city=city)
