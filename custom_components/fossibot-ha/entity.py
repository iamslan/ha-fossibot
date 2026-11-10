"""Base entity for Fossibot integration."""

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER

# Board version registers (holding 47..51). Each packs a hardware and a
# software version into one word, so each board contributes to both of Home
# Assistant's version fields.
_VERSION_FIELDS = (
    ("AC", "versionAc"),
    ("BMS", "versionBms"),
    ("PV", "versionPv"),
    ("Panel", "versionPanel"),
    ("Com", "versionExternalCom"),
)


def device_profile(coordinator, device_id: str) -> int:
    """Register profile of a device: 0 = V0 document, 1 = V1 (registers_v1)."""
    return coordinator.data.get(device_id, {}).get("protocolProfile", 0)


def definitions_for(definitions, profile: int):
    """Yield entity definitions that apply to ``profile``, minus the marker key.

    A definition without ``profile`` applies to every device; ``profile: 0``
    or ``profile: 1`` restricts it to that register layout.
    """
    for defn in definitions:
        wanted = defn.get("profile")
        if wanted is None or wanted == profile:
            yield {k: v for k, v in defn.items() if k != "profile"}


class FossibotEntity(CoordinatorEntity):
    """Base class for all Fossibot entities.

    Provides shared device_info and availability logic so that
    platform-specific entities (sensor, switch, select) don't
    duplicate this code.
    """

    def __init__(self, coordinator, device_id: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._device_id = device_id

    @property
    def available(self) -> bool:
        """Return True if the device is present in coordinator data."""
        return super().available and self._device_id in self.coordinator.data

    @property
    def device_info(self):
        """Return device information.

        Model, firmware and serial number come from the holding registers the
        protocol reserves for them (11 device type/model, 47-51 board
        versions, 72-79 serial number), so the device page shows real
        hardware detail rather than just a MAC address.
        """
        device_data = self.coordinator.data.get(self._device_id, {})
        name = device_data.get("device_name") or f"Fossibot {self._device_id}"

        info = {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": name,
            "manufacturer": MANUFACTURER,
        }

        model = self._model(device_data)
        if model:
            info["model"] = model

        for field, suffix in (("sw_version", "Software"),
                              ("hw_version", "Hardware")):
            versions = [
                "%s %s" % (label, device_data["%s%s" % (key, suffix)])
                for label, key in _VERSION_FIELDS
                if device_data.get("%s%s" % (key, suffix)) is not None
            ]
            if versions:
                info[field] = " / ".join(versions)

        serial = device_data.get("serialNumber")
        if serial:
            info["serial_number"] = serial

        return info

    @staticmethod
    def _model(device_data: dict) -> str | None:
        """Build a model string from the API record or holding register 11."""
        product_info = device_data.get("productInfo") or {}
        for key in ("product_name", "model", "device_model"):
            value = product_info.get(key)
            if value:
                return str(value)

        market_type = device_data.get("deviceMarketType")
        model_code = device_data.get("deviceModelCode")
        if market_type and model_code:
            return "%s (model %s)" % (market_type, model_code)
        return market_type or None
