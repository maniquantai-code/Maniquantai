from backend.routers.broker_accounts import _render_template


def test_broker_order_template_renders():
    payload = _render_template(
        {"symbol": "{symbol}", "side": "{side}", "qty": "{volume}", "meta": {"strategy": "{strategy_id}"}},
        {"symbol": "BTCUSD", "side": "buy", "volume": 0.25, "strategy_id": "s-1"},
    )
    assert payload == {
        "symbol": "BTCUSD",
        "side": "buy",
        "qty": "0.25",
        "meta": {"strategy": "s-1"},
    }


def test_broker_order_template_keeps_non_strings():
    payload = _render_template({"quantity": 2, "enabled": True}, {})
    assert payload == {"quantity": 2, "enabled": True}
