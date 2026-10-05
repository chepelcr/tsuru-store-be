from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.configuration.cors_config import AppConfig, configure_cors


def test_parameter_controls_browser_requests_and_preserves_first_party(monkeypatch):
    keys = []
    def read(key, default=None):
        keys.append(key)
        return " http://localhost:3001, https://example.test, "
    monkeypatch.setattr(AppConfig, "get_key", read)
    app = FastAPI()
    configure_cors(app)
    @app.get('/probe')
    def probe(): return {'ok': True}
    client = TestClient(app)
    for origin in ['http://localhost:3001', 'https://example.test', 'https://shop.stores.tsuru.jcampos.dev']:
        assert client.get('/probe', headers={'Origin': origin}).headers['access-control-allow-origin'] == origin
        assert client.options('/probe', headers={'Origin': origin, 'Access-Control-Request-Method':'GET'}).status_code == 200
    assert 'access-control-allow-origin' not in client.get('/probe', headers={'Origin':'https://unlisted.test'}).headers
    assert keys == ['cors.allowed-origins']
