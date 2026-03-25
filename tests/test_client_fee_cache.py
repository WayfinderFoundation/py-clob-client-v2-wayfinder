"""
Tests for FeeInfo cache correctness in ClobClient.

Aligned with TypeScript clob-client-v2 behavior:
- getClobMarketInfo always sets feeInfos[tokenId] = FeeInfo(rate=fd?.r ?? 0, exponent=fd?.e ?? 0)
- Cache presence check is `token_id in __fee_infos` (not None-checking values)
- _ensureMarketInfoCached returns early if token_id in __fee_infos
- GET_FEE_RATE fallback sets FeeInfo(rate=X, exponent=0) — overwrites
"""

from unittest.mock import MagicMock, patch
import pytest

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import FeeInfo


HOST = "https://clob.example.com"
CHAIN_ID = 137
TOKEN_ID = "0xabc123"
CONDITION_ID = "0xdeadbeef"


def _make_client() -> ClobClient:
    return ClobClient(host=HOST, chain_id=CHAIN_ID)


def _inject_market_info(client: ClobClient, token_id: str, rate: float, exponent: float):
    """Simulate getClobMarketInfo populating all cache fields."""
    client._ClobClient__fee_infos[token_id] = FeeInfo(rate=rate, exponent=exponent)
    client._ClobClient__tick_sizes[token_id] = "0.01"
    client._ClobClient__neg_risk[token_id] = False
    client._ClobClient__token_condition_map[token_id] = CONDITION_ID


class TestFeeInfoDefaults:
    def test_fee_info_defaults_are_zero(self):
        fi = FeeInfo()
        assert fi.rate == 0.0
        assert fi.exponent == 0.0

    def test_fee_info_explicit_values(self):
        fi = FeeInfo(rate=0.02, exponent=2.0)
        assert fi.rate == 0.02
        assert fi.exponent == 2.0


class TestGetFeeRateBps:
    def test_returns_cached_rate_from_market_info(self):
        client = _make_client()
        _inject_market_info(client, TOKEN_ID, rate=0.02, exponent=2.0)
        assert client.get_fee_rate_bps(TOKEN_ID) == 0.02

    def test_cache_hit_any_fee_info_entry(self):
        """Any entry in __fee_infos satisfies the cache check."""
        client = _make_client()
        client._ClobClient__fee_infos[TOKEN_ID] = FeeInfo(rate=0.03, exponent=0.0)
        assert client.get_fee_rate_bps(TOKEN_ID) == 0.03

    def test_get_fee_rate_via_condition_map(self):
        """Falls through to getClobMarketInfo when token is in condition_map but not fee_infos."""
        client = _make_client()
        client._ClobClient__token_condition_map[TOKEN_ID] = CONDITION_ID

        clob_market_response = {
            "t": [{"t": TOKEN_ID}],
            "mts": "0.01",
            "nr": False,
            "fd": {"r": 0.025, "e": 1.0},
        }
        with patch.object(client, "_get", return_value=clob_market_response):
            rate = client.get_fee_rate_bps(TOKEN_ID)

        assert rate == 0.025

    def test_get_fee_rate_via_get_fee_rate_endpoint(self):
        """Falls through to GET_FEE_RATE when token not in fee_infos or condition_map."""
        client = _make_client()
        with patch.object(client, "_get", return_value={"base_fee": 0.05}) as mock_get:
            rate = client.get_fee_rate_bps(TOKEN_ID)
        assert rate == 0.05
        mock_get.assert_called_once()

    def test_get_fee_rate_endpoint_sets_exponent_zero(self):
        """GET_FEE_RATE fallback sets exponent to 0 (no exponent from that endpoint)."""
        client = _make_client()
        with patch.object(client, "_get", return_value={"base_fee": 0.04}):
            client.get_fee_rate_bps(TOKEN_ID)

        fi = client._ClobClient__fee_infos[TOKEN_ID]
        assert fi.rate == 0.04
        assert fi.exponent == 0.0

    def test_no_refetch_after_cache_hit(self):
        """Once in fee_infos, no further _get calls for rate."""
        client = _make_client()
        _inject_market_info(client, TOKEN_ID, rate=0.02, exponent=2.0)

        with patch.object(client, "_get") as mock_get:
            client.get_fee_rate_bps(TOKEN_ID)

        mock_get.assert_not_called()


class TestGetFeeExponent:
    def test_returns_cached_exponent_from_market_info(self):
        client = _make_client()
        _inject_market_info(client, TOKEN_ID, rate=0.02, exponent=2.0)
        assert client.get_fee_exponent(TOKEN_ID) == 2.0

    def test_cache_hit_any_fee_info_entry(self):
        """Any entry in __fee_infos satisfies the cache check (returns stored exponent)."""
        client = _make_client()
        # Simulate GET_FEE_RATE fallback: exponent=0
        client._ClobClient__fee_infos[TOKEN_ID] = FeeInfo(rate=0.03, exponent=0.0)
        assert client.get_fee_exponent(TOKEN_ID) == 0.0

    def test_fetches_market_info_when_not_cached(self):
        client = _make_client()
        client._ClobClient__token_condition_map[TOKEN_ID] = CONDITION_ID

        clob_market_response = {
            "t": [{"t": TOKEN_ID}],
            "mts": "0.01",
            "nr": False,
            "fd": {"r": 0.02, "e": 4.0},
        }
        with patch.object(client, "_get", return_value=clob_market_response):
            exponent = client.get_fee_exponent(TOKEN_ID)

        assert exponent == 4.0

    def test_no_refetch_after_cache_hit(self):
        """Once in fee_infos, no further _get calls for exponent."""
        client = _make_client()
        _inject_market_info(client, TOKEN_ID, rate=0.02, exponent=1.5)

        with patch.object(client, "_get") as mock_get:
            exponent = client.get_fee_exponent(TOKEN_ID)

        assert exponent == 1.5
        mock_get.assert_not_called()


class TestGetClobMarketInfo:
    def test_sets_fee_info_with_defaults_when_fd_missing(self):
        """When fd is missing from response, fee info defaults to rate=0, exponent=0."""
        client = _make_client()

        response = {
            "t": [{"t": TOKEN_ID}],
            "mts": "0.01",
            "nr": False,
        }
        with patch.object(client, "_get", return_value=response):
            client.get_clob_market_info(CONDITION_ID)

        fi = client._ClobClient__fee_infos.get(TOKEN_ID)
        assert fi is not None
        assert fi.rate == 0.0
        assert fi.exponent == 0.0

    def test_sets_fee_info_from_fd(self):
        client = _make_client()

        response = {
            "t": [{"t": TOKEN_ID}],
            "mts": "0.01",
            "nr": False,
            "fd": {"r": 0.03, "e": 2.0},
        }
        with patch.object(client, "_get", return_value=response):
            client.get_clob_market_info(CONDITION_ID)

        fi = client._ClobClient__fee_infos[TOKEN_ID]
        assert fi.rate == 0.03
        assert fi.exponent == 2.0

    def test_no_repeated_fetch_after_clob_market_info(self):
        """After getClobMarketInfo populates fee_infos, get_fee_rate_bps should not re-fetch."""
        client = _make_client()
        _inject_market_info(client, TOKEN_ID, rate=0.02, exponent=2.0)

        with patch.object(client, "_get") as mock_get:
            client.get_fee_rate_bps(TOKEN_ID)
            client.get_fee_exponent(TOKEN_ID)

        mock_get.assert_not_called()


class TestEnsureMarketInfoCached:
    def test_no_refetch_when_fee_infos_has_token(self):
        """Returns immediately if token already in __fee_infos."""
        client = _make_client()
        _inject_market_info(client, TOKEN_ID, rate=0.02, exponent=2.0)

        with patch.object(client, "_get") as mock_get:
            client._ClobClient__ensure_market_info_cached(TOKEN_ID)

        mock_get.assert_not_called()

    def test_fetches_when_not_in_fee_infos(self):
        client = _make_client()
        client._ClobClient__token_condition_map[TOKEN_ID] = CONDITION_ID

        clob_market_response = {
            "t": [{"t": TOKEN_ID}],
            "mts": "0.01",
            "nr": False,
            "fd": {"r": 0.01, "e": 1.0},
        }
        with patch.object(client, "_get", return_value=clob_market_response):
            client._ClobClient__ensure_market_info_cached(TOKEN_ID)

        assert TOKEN_ID in client._ClobClient__fee_infos

    def test_get_fee_rate_endpoint_entry_blocks_refetch(self):
        """If GET_FEE_RATE stored a FeeInfo, ensureMarketInfoCached returns early."""
        client = _make_client()
        # Simulate GET_FEE_RATE fallback result
        client._ClobClient__fee_infos[TOKEN_ID] = FeeInfo(rate=0.05, exponent=0.0)
        client._ClobClient__token_condition_map[TOKEN_ID] = CONDITION_ID

        with patch.object(client, "_get") as mock_get:
            client._ClobClient__ensure_market_info_cached(TOKEN_ID)

        mock_get.assert_not_called()
