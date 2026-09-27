import json
from fusionsolar_readonly_exporter.storage import RunStore, sha256_bytes


class FakeResponse:
    status_code = 200
    content = b'{"data":{"synthetic":true}}'

    def json(self):
        return json.loads(self.content)


def test_raw_capture_returns_hash_and_redacts_request_secrets(tmp_path):
    store = RunStore.create(tmp_path / "out", tmp_path / "state")
    response = FakeResponse()
    digest = store.record_exchange(
        method="POST",
        url="https://eu5.fusionsolar.huawei.com/synthetic-read",
        purpose="synthetic.read",
        params={"safe": 1},
        json_body={"username": "private-user", "token": "private-token", "safe": "kept"},
        data=None,
        response=response,
    )
    assert digest == sha256_bytes(response.content)
    envelope = json.loads(next((store.root / "raw").glob("*.envelope.json")).read_text())
    assert envelope["json_body"]["username"] == "<redacted>"
    assert envelope["json_body"]["token"] == "<redacted>"
    assert envelope["json_body"]["safe"] == "kept"
    assert envelope["response_sha256"] == digest
    assert next((store.root / "raw").glob("*.json")).exists()
