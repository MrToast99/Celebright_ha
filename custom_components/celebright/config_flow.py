"""Config flow for Celebright — collects Cognito credentials."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback

from .api import CelebrightAuthError, CelebrightCloudAPI, CelebrightConnectionError
from .const import CONF_EMAIL, CONF_PASSWORD, CONF_SHOW_SIDEBAR, DOMAIN
from .sidebar import sidebar_enabled

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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "CelebrightOptionsFlow":
        return CelebrightOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=_SCHEMA)

        errors: dict[str, str] = {}
        try:
            await self._validate(user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
        except CelebrightAuthError as err:
            _LOGGER.warning("Celebright login rejected: %s", err)
            errors["base"] = "invalid_auth"
        except CelebrightConnectionError as err:
            # Log the real cause (e.g. a Cognito 400); the UI only shows "cannot_connect".
            _LOGGER.error("Celebright could not connect during setup: %s", err)
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
        # New installs get the sidebar page; existing entries have no such option and keep it off.
        return self.async_create_entry(
            title="Celebright", data=user_input, options={CONF_SHOW_SIDEBAR: True}
        )

    # --- Re-authentication (started by Home Assistant when the saved login is rejected) ---

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="reauth_failed")

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._validate(entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])
            except CelebrightAuthError as err:
                _LOGGER.warning("Celebright re-authentication rejected: %s", err)
                errors["base"] = "invalid_auth"
            except CelebrightConnectionError as err:
                _LOGGER.error("Celebright could not connect during re-authentication: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during Celebright re-authentication")
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    async def _validate(self, email: str, password: str) -> None:
        client = CelebrightCloudAPI(email=email, password=password)
        try:
            await client.async_connect()
        finally:
            await client.async_disconnect()


class CelebrightOptionsFlow(OptionsFlow):
    """Options: show the Celebright page in the sidebar."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        # Not self.config_entry: newer cores provide it and reject assigning it.
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data={**self._entry.options, **user_input})
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_SHOW_SIDEBAR, default=sidebar_enabled(self._entry)): bool}
            ),
        )
