from app.routes.common import failure, success


def test_api_success_and_failure_envelopes():
    from flask import Flask
    app = Flask(__name__)
    with app.app_context():
        ok, ok_status = success({"value": 1})
        bad, bad_status = failure("nope")
        assert ok_status == 200 and ok.get_json()["success"] is True and ok.get_json()["data"] == {"value": 1}
        assert ok.get_json()["warnings"] == []
        assert bad_status == 400 and bad.get_json() == {"success": False, "ok": False, "error": "nope", "details": {}}


def test_reset_and_exit_sweep_routes_do_not_invoke_scan():
    from flask import Flask
    from app.routes.paper_routes import create_paper_blueprint
    calls = []
    class Paper:
        def reset(self): calls.append("reset"); return {"reset": True}
        def exit_sweep(self): calls.append("exit"); return {"closed": 0}
        def account(self): return {}
        def positions(self): return []
        def orders(self): return []
        def trades(self): return []
    def scan(): calls.append("scan"); return {}
    app = Flask(__name__); app.register_blueprint(create_paper_blueprint(Paper(), scan)); client = app.test_client()
    reset = client.post("/api/reset_session", json={"confirm": True}).get_json()
    exits = client.post("/api/run_exit_sweep").get_json()
    assert reset["success"] and exits["success"] and calls == ["reset", "exit"]


def test_reset_requires_explicit_confirmation():
    from flask import Flask
    from app.routes.paper_routes import create_paper_blueprint
    class Paper:
        def reset(self): raise AssertionError("reset must not run")
    app = Flask(__name__); app.register_blueprint(create_paper_blueprint(Paper(), lambda: None))
    response = app.test_client().post("/api/reset_session", json={})
    assert response.status_code == 400 and response.get_json()["success"] is False


def test_recalibration_route_calls_report_service():
    from flask import Flask
    from app.routes.data_routes import create_data_blueprint
    class Reports:
        def __init__(self): self.calls = 0
        def recalibrate(self): self.calls += 1; return {"status": "complete"}
    reports = Reports(); app = Flask(__name__); app.register_blueprint(create_data_blueprint(reports))
    payload = app.test_client().post("/api/recalibrate").get_json()
    assert payload["success"] and reports.calls == 1


def test_dashboard_and_state_routes_load():
    from flask import Flask
    from app.routes.dashboard_routes import create_dashboard_blueprint
    app = Flask(__name__, template_folder="../templates")
    app.register_blueprint(create_dashboard_blueprint(lambda: {"mode": "PAPER", "live_trading_enabled": False}))
    client = app.test_client()
    page = client.get("/")
    state = client.get("/api/state").get_json()
    assert page.status_code == 200 and b"pane-backtests" in page.data
    assert state["success"] is True and state["data"]["mode"] == "PAPER" and state["data"]["live_trading_enabled"] is False
