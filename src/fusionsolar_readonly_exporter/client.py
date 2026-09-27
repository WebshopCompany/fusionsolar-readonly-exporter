from __future__ import annotations

import time
from datetime import date
from typing import Any

from .auth import AuthenticatedSession
from .timeutil import huawei_timezone_offset_hours, local_midnight_ms

MOC_TYPES = "20814,20815,20816,20819,20822,50017,60066,60014,60015,23037"


class FusionSolarReadClient:
    def __init__(self, auth: AuthenticatedSession):
        if not auth.company_dn:
            raise ValueError("authenticated session required")
        self.auth = auth
        self.t = auth.transport

    @property
    def host(self) -> str:
        return self.auth.data_host

    def plants(self) -> list[dict[str, Any]]:
        now = int(time.time() * 1000)
        body = self.t.post_json(
            f"https://{self.host}/rest/pvms/web/station/v1/station/station-list",
            "topology.plants",
            json_body={
                "curPage": 1,
                "pageSize": 200,
                "gridConnectedTime": "",
                "queryTime": now,
                "timeZone": huawei_timezone_offset_hours(date.today()),
                "sortId": "createTime",
                "sortDir": "DESC",
                "locale": "en_US",
            },
        )
        data = body.get("data", {}) if isinstance(body, dict) else {}
        return list(data.get("list") or [])

    def devices(self, parent_dn: str | None = None) -> list[dict[str, Any]]:
        body = self.t.get_json(
            f"https://{self.host}/rest/neteco/web/config/device/v1/device-list",
            "topology.devices",
            params={
                "conditionParams.parentDn": parent_dn or self.auth.company_dn,
                "conditionParams.mocTypes": MOC_TYPES,
                "_": int(time.time() * 1000),
            },
        )
        data = body.get("data") if isinstance(body, dict) else []
        return list(data or [])

    def plant_flow(self, station_dn: str) -> dict[str, Any]:
        return self.t.get_json(
            f"https://{self.host}/rest/pvms/web/station/v1/overview/energy-flow",
            "plant.flow",
            params={"stationDn": station_dn, "_": int(time.time() * 1000)},
        )

    def plant_balance(self, station_dn: str, day: date) -> dict[str, Any]:
        query_time = local_midnight_ms(day)
        return self.t.get_json(
            f"https://{self.host}/rest/pvms/web/station/v1/overview/energy-balance",
            "plant.balance",
            params={
                "stationDn": station_dn,
                "timeDim": 2,
                "queryTime": query_time,
                "timeZone": huawei_timezone_offset_hours(day),
                "timeZoneStr": "Europe/London",
                "_": int(time.time() * 1000),
            },
        )

    def history(
        self,
        device_dn: str,
        signal_ids: list[str],
        day: date,
    ) -> dict[str, Any]:
        return self.t.get_json(
            f"https://{self.host}/rest/pvms/web/device/v1/device-history-data",
            "device.history",
            params={
                "signalIds": list(signal_ids),
                "deviceDn": device_dn,
                "date": local_midnight_ms(day),
                "_": int(time.time() * 1000),
            },
        )

    def realtime(self, device_dn: str) -> dict[str, Any]:
        return self.t.get_json(
            f"https://{self.host}/rest/pvms/web/device/v1/device-realtime-data",
            "device.realtime",
            params={"deviceDn": device_dn, "_": int(time.time() * 1000)},
        )

    def kpi(self, device_dn: str, signal_ids: list[str]) -> dict[str, Any]:
        return self.t.get_json(
            f"https://{self.host}/rest/pvms/web/device/v1/device-real-kpi",
            "device.kpi",
            params={
                "deviceDn": device_dn,
                "signalIds": ",".join(signal_ids),
                "_": int(time.time() * 1000),
            },
        )

    def battery_module(
        self,
        battery_dn: str,
        module_id: str,
        signal_ids: list[str],
    ) -> dict[str, Any]:
        return self.t.get_json(
            f"https://{self.host}/rest/pvms/web/device/v1/query-battery-dc",
            "battery.module",
            params={
                "sigids": ",".join(signal_ids),
                "dn": battery_dn,
                "moduleId": module_id,
                "_": int(time.time() * 1000),
            },
        )

    def alarms(self, device_dn: str) -> dict[str, Any]:
        return self.t.post_json(
            f"https://{self.host}/rest/pvms/fm/v1/query",
            "alarms.current",
            json_body={
                "dataType": "CURRENT",
                "domainType": "OC_SOLAR",
                "pageNo": 1,
                "pageSize": 100,
                "nativeMeDn": device_dn,
            },
        )
