from app.routes.common import failure, success


def test_api_success_and_failure_envelopes():
    from flask import Flask
    app = Flask(__name__)
    with app.app_context():
        ok, ok_status = success({"value": 1})
        bad, bad_status = failure("nope")
        assert ok_status == 200 and ok.get_json()["success"] is True and ok.get_json()["data"] == {"value": 1}
        assert bad_status == 400 and bad.get_json() == {"success": False, "ok": False, "error": "nope"}
