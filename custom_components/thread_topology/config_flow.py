"""Config flow for Thread Topology integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_URL

from .const import DEFAULT_OTBR_URL, DOMAIN, ENDPOINT_NODE

_LOGGER = logging.getLogger(__name__)


class ThreadTopologyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Thread Topology."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            otbr_url = user_input.get(CONF_URL, DEFAULT_OTBR_URL)

            # Test connection to OTBR
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{otbr_url}{ENDPOINT_NODE}",
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            network_name = data.get("NetworkName", "Thread Network")

                            # Check if already configured
                            await self.async_set_unique_id(network_name)
                            self._abort_if_unique_id_configured()

                            return self.async_create_entry(
                                title=f"Thread: {network_name}",
                                data={"otbr_url": otbr_url},
                            )
                        else:
                            errors["base"] = "cannot_connect"
            except aiohttp.ClientError:
                errors["base"] = "cannot_connect"
            except TimeoutError:
                errors["base"] = "timeout"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=DEFAULT_OTBR_URL): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "default_url": DEFAULT_OTBR_URL,
            },
        )
