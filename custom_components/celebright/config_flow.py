"""Config flow for Celebright — collects Cognito credentials."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .api import CelebrightAuthError, CelebrightCloudAPI, CelebrightConnectionError
from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN

_LOGGER = logging.getLogger(__name__)

_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class CelebrightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-step setup: email + password → Cognito auth validation."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=_SCHEMA)

        errors: dict[str, str] = {}
        try:
            await self._validate(user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
        except CelebrightAuthError:
            errors["base"] = "invalid_auth"
        except CelebrightConnectionError:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error during Celebright setup")
            errors["base"] = "unknown"

        if errors:
            return self.async_show_form(
                step_id="user", data_schema=_SCHEMA, errors=errors
            )

        await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Celebright", data=user_input)

    async def _validate(self, email: str, password: str) -> None:
        client = CelebrightCloudAPI(email=email, password=password)
        await client.async_connect()
        await client.async_disconnect()
