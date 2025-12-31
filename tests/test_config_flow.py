"""Tests for Thread Topology config flow."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest
import aiohttp

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.thread_topology.const import DOMAIN, DEFAULT_OTBR_URL


class TestConfigFlow:
    """Test cases for config flow."""

    @pytest.mark.asyncio
    async def test_form_shows_default_url(self, hass):
        """Test that the form shows default OTBR URL."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert "default_url" in result.get("description_placeholders", {})

    @pytest.mark.asyncio
    async def test_successful_config(self, hass, mock_otbr_node_response):
        """Test successful configuration."""
        with patch("aiohttp.ClientSession") as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_otbr_node_response)

            session_instance = AsyncMock()
            session_instance.get = AsyncMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=None)
            ))
            mock_session.return_value.__aenter__ = AsyncMock(return_value=session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"url": DEFAULT_OTBR_URL}
            )

            assert result["type"] == FlowResultType.CREATE_ENTRY
            assert result["title"] == f"Thread: {mock_otbr_node_response['NetworkName']}"
            assert result["data"]["otbr_url"] == DEFAULT_OTBR_URL

    @pytest.mark.asyncio
    async def test_connection_error(self, hass):
        """Test handling of connection error."""
        with patch("aiohttp.ClientSession") as mock_session:
            session_instance = AsyncMock()
            session_instance.get = AsyncMock(side_effect=aiohttp.ClientError())
            mock_session.return_value.__aenter__ = AsyncMock(return_value=session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"url": DEFAULT_OTBR_URL}
            )

            assert result["type"] == FlowResultType.FORM
            assert result["errors"]["base"] == "cannot_connect"

    @pytest.mark.asyncio
    async def test_timeout_error(self, hass):
        """Test handling of timeout error."""
        with patch("aiohttp.ClientSession") as mock_session:
            session_instance = AsyncMock()
            session_instance.get = AsyncMock(side_effect=TimeoutError())
            mock_session.return_value.__aenter__ = AsyncMock(return_value=session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"url": DEFAULT_OTBR_URL}
            )

            assert result["type"] == FlowResultType.FORM
            assert result["errors"]["base"] == "timeout"

    @pytest.mark.asyncio
    async def test_non_200_response(self, hass):
        """Test handling of non-200 HTTP response."""
        with patch("aiohttp.ClientSession") as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 500

            session_instance = AsyncMock()
            session_instance.get = AsyncMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=None)
            ))
            mock_session.return_value.__aenter__ = AsyncMock(return_value=session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"url": DEFAULT_OTBR_URL}
            )

            assert result["type"] == FlowResultType.FORM
            assert result["errors"]["base"] == "cannot_connect"

    @pytest.mark.asyncio
    async def test_already_configured(self, hass, mock_otbr_node_response):
        """Test handling of already configured network."""
        # First, create an existing entry
        entry = config_entries.ConfigEntry(
            version=1,
            domain=DOMAIN,
            title="Thread: MyHome1038137341",
            data={"otbr_url": DEFAULT_OTBR_URL},
            source=config_entries.SOURCE_USER,
            unique_id="MyHome1038137341",
        )
        hass.config_entries._entries.append(entry)

        with patch("aiohttp.ClientSession") as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_otbr_node_response)

            session_instance = AsyncMock()
            session_instance.get = AsyncMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=None)
            ))
            mock_session.return_value.__aenter__ = AsyncMock(return_value=session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"url": DEFAULT_OTBR_URL}
            )

            assert result["type"] == FlowResultType.ABORT
            assert result["reason"] == "already_configured"

    @pytest.mark.asyncio
    async def test_custom_url(self, hass, mock_otbr_node_response):
        """Test configuration with custom URL."""
        custom_url = "http://192.168.1.100:8081"

        with patch("aiohttp.ClientSession") as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_otbr_node_response)

            session_instance = AsyncMock()
            session_instance.get = AsyncMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=None)
            ))
            mock_session.return_value.__aenter__ = AsyncMock(return_value=session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"url": custom_url}
            )

            assert result["type"] == FlowResultType.CREATE_ENTRY
            assert result["data"]["otbr_url"] == custom_url
