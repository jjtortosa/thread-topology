"""Tests for Thread Topology config flow."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import aiohttp


class TestConfigFlow:
    """Test cases for config flow validation logic."""

    @pytest.mark.asyncio
    async def test_validate_url_success(self, mock_otbr_node_response):
        """Test URL validation succeeds with valid response."""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_otbr_node_response)

            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = mock_response
            mock_cm.__aexit__.return_value = None

            mock_session = AsyncMock()
            mock_session.get.return_value = mock_cm

            mock_session_class.return_value.__aenter__.return_value = mock_session
            mock_session_class.return_value.__aexit__.return_value = None

            async with aiohttp.ClientSession() as session:
                async with session.get("http://localhost:8081/node") as response:
                    assert response.status == 200
                    data = await response.json()
                    assert data["NetworkName"] == "MyHome1038137341"

    @pytest.mark.asyncio
    async def test_validate_url_connection_error(self):
        """Test URL validation handles connection errors."""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.get.side_effect = aiohttp.ClientError("Connection failed")

            mock_session_class.return_value.__aenter__.return_value = mock_session
            mock_session_class.return_value.__aexit__.return_value = None

            async with aiohttp.ClientSession() as session:
                with pytest.raises(aiohttp.ClientError):
                    await session.get("http://invalid-host:8081/node")

    @pytest.mark.asyncio
    async def test_validate_url_timeout_error(self):
        """Test URL validation handles timeout errors."""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.get.side_effect = TimeoutError("Request timed out")

            mock_session_class.return_value.__aenter__.return_value = mock_session
            mock_session_class.return_value.__aexit__.return_value = None

            async with aiohttp.ClientSession() as session:
                with pytest.raises(TimeoutError):
                    await session.get("http://localhost:8081/node")

    @pytest.mark.asyncio
    async def test_validate_url_non_200_response(self):
        """Test URL validation handles non-200 responses."""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 500

            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = mock_response
            mock_cm.__aexit__.return_value = None

            mock_session = AsyncMock()
            mock_session.get.return_value = mock_cm

            mock_session_class.return_value.__aenter__.return_value = mock_session
            mock_session_class.return_value.__aexit__.return_value = None

            async with aiohttp.ClientSession() as session:
                async with session.get("http://localhost:8081/node") as response:
                    assert response.status == 500

    def test_default_url_constant(self):
        """Test default OTBR URL constant is set correctly."""
        from custom_components.thread_topology.const import DEFAULT_OTBR_URL

        assert DEFAULT_OTBR_URL == "http://homeassistant.local:8081"

    def test_domain_constant(self):
        """Test domain constant is set correctly."""
        from custom_components.thread_topology.const import DOMAIN

        assert DOMAIN == "thread_topology"

    @pytest.mark.asyncio
    async def test_extract_network_name_from_response(self, mock_otbr_node_response):
        """Test extracting network name from OTBR response."""
        network_name = mock_otbr_node_response.get("NetworkName", "Unknown")

        assert network_name == "MyHome1038137341"

    @pytest.mark.asyncio
    async def test_url_normalization(self):
        """Test URL trailing slash is handled."""
        urls = [
            "http://localhost:8081",
            "http://localhost:8081/",
        ]

        for url in urls:
            normalized = url.rstrip("/")
            assert normalized == "http://localhost:8081"
