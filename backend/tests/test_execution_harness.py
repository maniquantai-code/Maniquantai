import pytest

from backend.core.execution_harness import HarnessReject, validate_execution_request


def good_result():
    return {
        "execute": True, "side": "buy", "volume_pct": 0.5,
        "stop_loss": 95, "take_profit": 110, "risk_pct": 1.0,
        "consensus": 0.6, "reason": "two deterministic agents agree",
        "signals": [
            {"agent": "momentum", "signal": "BUY", "strength": 0.8},
            {"agent": "breakout", "signal": "BUY", "strength": 0.7},
        ],
    }


def bars():
    return [{"ts": i, "open": 99, "high": 101, "low": 98, "close": 100, "volume": 1} for i in range(40)]


def strategy():
    return {"strategy_id": "s1", "id": "s1"}


def spec():
    return {"live_approved": True, "pipeline_stage": "live_running"}


def test_harness_allows_valid_signal():
    result = validate_execution_request(
        strategy=strategy(), spec=spec(), result=good_result(),
        symbol="BTCUSD", timeframe="15m", bars=bars(),
        account_equity=10000, current_position="flat", bridge_online=True,
    )
    assert result.allowed is True
    assert result.signal_key


@pytest.mark.parametrize("field,value", [
    ("risk_pct", 2.01),
    ("consensus", 0.20),
])
def test_harness_rejects_unsafe_signal(field, value):
    decision = good_result()
    decision[field] = value
    with pytest.raises(HarnessReject):
        validate_execution_request(
            strategy=strategy(), spec=spec(), result=decision,
            symbol="BTCUSD", timeframe="15m", bars=bars(),
            account_equity=10000, current_position="flat", bridge_online=True,
        )


def test_harness_rejects_missing_protection():
    decision = good_result()
    decision["stop_loss"] = None
    with pytest.raises(HarnessReject):
        validate_execution_request(
            strategy=strategy(), spec=spec(), result=decision,
            symbol="BTCUSD", timeframe="15m", bars=bars(),
            account_equity=10000, current_position="flat", bridge_online=True,
        )


def test_harness_rejects_kill_switch():
    with pytest.raises(HarnessReject):
        validate_execution_request(
            strategy=strategy(), spec=spec(), result=good_result(),
            symbol="BTCUSD", timeframe="15m", bars=bars(),
            account_equity=10000, current_position="flat", bridge_online=True,
            kill_switch=True,
        )


def test_positive_daily_loss_magnitude_is_normalized():
    strategy, spec, result, bars_ = strategy(), spec(), good_result(), bars()
    spec["daily_loss_limit_pct"] = 5.0
    out = validate_execution_request(strategy=strategy, spec=spec, result=result, symbol="BTCUSD", timeframe="15m", bars=bars_, account_equity=10000, current_position="flat", bridge_online=True, daily_pnl_pct=-4.0)
    assert out.allowed is True


def test_positive_daily_loss_magnitude_still_blocks_at_limit():
    strategy, spec, result, bars = _valid()
    spec["daily_loss_limit_pct"] = 5.0
    with pytest.raises(HarnessReject, match="Daily loss limit"):
        validate_execution_request(strategy=strategy, spec=spec, result=result, symbol="BTCUSD", timeframe="15m", bars=bars, account_equity=10000, current_position="flat", bridge_online=True, daily_pnl_pct=-5.0)
