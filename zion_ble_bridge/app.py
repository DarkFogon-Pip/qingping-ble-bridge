"""FastAPI application for Zion's host-side BLE bridge."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, status

from .auth import require_request_auth
from .config import Settings, load_settings
from .models import AlarmRequest, ConfigurationPatchRequest, QingpingState, SetTimeRequest
from .devices.qingping.service import (
    DeviceOperationError,
    InvalidDeviceConfiguration,
    QingpingBridgeService,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the bridge application."""
    settings = settings or load_settings()
    app = FastAPI(title="Zion BLE Bridge", version="0.2.0")
    service = QingpingBridgeService(settings)
    auth_dependency = require_request_auth(settings)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/api/v1/qingping/{mac}/state",
        response_model=QingpingState,
        dependencies=[Depends(auth_dependency)],
    )
    async def get_state(mac: str) -> QingpingState:
        try:
            return await service.get_state(mac)
        except DeviceOperationError as err:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(err),
            ) from err

    @app.post(
        "/api/v1/qingping/{mac}/refresh",
        response_model=QingpingState,
        dependencies=[Depends(auth_dependency)],
    )
    async def refresh(mac: str) -> QingpingState:
        try:
            return await service.refresh(mac)
        except DeviceOperationError as err:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(err),
            ) from err

    @app.post(
        "/api/v1/qingping/{mac}/time",
        response_model=QingpingState,
        dependencies=[Depends(auth_dependency)],
    )
    async def set_time(mac: str, payload: SetTimeRequest) -> QingpingState:
        try:
            return await service.set_time(mac, payload.timestamp, payload.timezone_offset)
        except DeviceOperationError as err:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(err),
            ) from err

    @app.patch(
        "/api/v1/qingping/{mac}/configuration",
        response_model=QingpingState,
        dependencies=[Depends(auth_dependency)],
    )
    async def patch_configuration(
        mac: str,
        payload: ConfigurationPatchRequest,
    ) -> QingpingState:
        try:
            return await service.patch_configuration(mac, payload)
        except InvalidDeviceConfiguration as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(err),
            ) from err
        except DeviceOperationError as err:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(err),
            ) from err

    @app.put(
        "/api/v1/qingping/{mac}/alarms/{slot}",
        response_model=QingpingState,
        dependencies=[Depends(auth_dependency)],
    )
    async def put_alarm(mac: str, slot: int, payload: AlarmRequest) -> QingpingState:
        try:
            return await service.set_alarm(mac, slot, payload)
        except InvalidDeviceConfiguration as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(err),
            ) from err
        except DeviceOperationError as err:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(err),
            ) from err

    @app.delete(
        "/api/v1/qingping/{mac}/alarms/{slot}",
        response_model=QingpingState,
        dependencies=[Depends(auth_dependency)],
    )
    async def delete_alarm(mac: str, slot: int) -> QingpingState:
        try:
            return await service.delete_alarm(mac, slot)
        except DeviceOperationError as err:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(err),
            ) from err

    return app


app = create_app()
