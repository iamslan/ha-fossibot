"""Pytest configuration for Fossibot tests.

The integration lives in ``custom_components/fossibot-ha``, whose hyphen makes
it un-importable as a package name, and its modules import Home Assistant and
the MQTT/HTTP client libraries. This module

* registers the integration as a top-level package named ``fossibot_ha``, and
* installs lightweight stubs for ``homeassistant``, ``paho`` and ``aiohttp``,

so the tests can import the *real* entity-definition tables rather than
maintaining hand-written copies of them (copies which silently drift out of
sync with the code they are meant to protect).
"""

import importlib
import importlib.util
import sys
import types
from pathlib import Path

INTEGRATION_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "fossibot-ha"
)


# ---------------------------------------------------------------------------
# Stub framework
#
# Home Assistant is used two ways by the platform modules: as base classes
# (``SensorEntity``) and as enum-like constant holders
# (``SensorDeviceClass.POWER``). A MagicMock covers the second but not the
# first — you cannot subclass a Mock. So each stub attribute is a freshly
# created class, cached by name so repeated access is identity-stable and
# distinct names stay distinct.
# ---------------------------------------------------------------------------

class _StubMeta(type):
    """Metaclass that materialises any attribute as a nested stub class."""

    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        stub = _StubMeta(name, (), {})
        setattr(cls, name, stub)
        return stub


class _StubModule(types.ModuleType):
    """Module whose every attribute is a stub class."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        stub = _StubMeta(name, (), {})
        setattr(self, name, stub)
        return stub


_STUBBED_MODULES = [
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.number",
    "homeassistant.components.select",
    "homeassistant.components.sensor",
    "homeassistant.components.switch",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.data_entry_flow",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.update_coordinator",
    "voluptuous",
    "aiohttp",
    "paho",
    "paho.mqtt",
    "paho.mqtt.client",
]

for _name in _STUBBED_MODULES:
    if _name not in sys.modules:
        sys.modules[_name] = _StubModule(_name)

# Decorators must stay callable and identity-preserving; a stub class would be
# invoked as ``callback(func)`` and fail.
sys.modules["homeassistant.core"].callback = lambda func: func


def _register_package(name: str, directory: Path) -> None:
    """Register ``directory`` as an importable package under ``name``.

    The package's own ``__init__.py`` is deliberately not executed — for the
    integration root it would pull in the Home Assistant setup path — but
    ``__path__`` is set so that relative imports inside the package resolve
    normally through the standard import machinery.
    """
    if name in sys.modules:
        return
    package = types.ModuleType(name)
    package.__path__ = [str(directory)]
    sys.modules[name] = package


_register_package("fossibot_ha", INTEGRATION_DIR)
_register_package("fossibot_ha.sydpower", INTEGRATION_DIR / "sydpower")

# Import eagerly so a syntax or import error surfaces during collection
# rather than as a confusing failure inside an individual test.
for _module in (
    "fossibot_ha.sydpower.const",
    "fossibot_ha.sydpower.registers",
    "fossibot_ha.sydpower.modbus",
    "fossibot_ha.entity",
    "fossibot_ha.binary_sensor",
    "fossibot_ha.sensor",
    "fossibot_ha.select",
    "fossibot_ha.switch",
    "fossibot_ha.number",
):
    importlib.import_module(_module)
