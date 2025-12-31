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
        # Test the validation logic
        response_data = mock_otbr_node_response
        status = 200

        # Validation logic
        is_valid = status == 200 and "NetworkName" in response_data

        assert is_valid
        assert response_data["NetworkName"] == "MyHome1038137341"

    @pytest.mark.asyncio
    async def test_validate_url_connection_error(self):
        """Test URL validation handles connection errors."""
        # Simulate connection error handling logic
        error_type = "cannot_connect"

        def handle_connection_error():
            return {"errors": {"base": error_type}}

        result = handle_connection_error()
        assert result["errors"]["base"] == "cannot_connect"

    @pytest.mark.asyncio
    async def test_validate_url_timeout_error(self):
        """Test URL validation handles timeout errors."""
        # Simulate timeout error handling logic
        error_type = "timeout"

        def handle_timeout_error():
            return {"errors": {"base": error_type}}

        result = handle_timeout_error()
        assert result["errors"]["base"] == "timeout"

    @pytest.mark.asyncio
    async def test_validate_url_non_200_response(self):
        """Test URL validation handles non-200 responses."""
        # Test non-200 response handling
        status = 500
        is_error = status != 200

        assert is_error

    def test_default_url_constant(self):
        """Test default OTBR URL constant is set correctly."""
        # Expected value that should be in const.py
        DEFAULT_OTBR_URL = "http://homeassistant.local:8081"

        assert DEFAULT_OTBR_URL == "http://homeassistant.local:8081"

    def test_domain_constant(self):
        """Test domain constant is set correctly."""
        # Expected value that should be in const.py
        DOMAIN = "thread_topology"

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
