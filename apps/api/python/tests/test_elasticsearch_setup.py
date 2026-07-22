from app.search import elasticsearch_setup as es


class _FakeEsqlClient:
    def __init__(self):
        self.last_query = None
        self.last_params = None

    def query(self, *, query, params=None, **_kwargs):
        self.last_query = query
        self.last_params = params
        return type("Resp", (), {"body": {"columns": [], "values": []}})()


class _FakeClient:
    def __init__(self):
        self.esql = _FakeEsqlClient()


def test_top_entity_types_by_source_binds_source_as_a_param(monkeypatch):
    """Regression test: `source` used to be f-string-interpolated
    directly into the ES|QL query text, so a value like
    `x" | LIMIT 1 | FROM other_index // ` could break out of the quoted
    literal and append arbitrary ES|QL stages. It must now be bound via
    `?` + `params`, never embedded in the query string itself."""
    fake_client = _FakeClient()
    monkeypatch.setattr(es, "get_client", lambda: fake_client)

    malicious_source = 'x" | LIMIT 1 | FROM some_other_index // '
    es.top_entity_types_by_source(malicious_source, limit=5)

    assert fake_client.esql.last_params == [malicious_source]
    assert malicious_source not in fake_client.esql.last_query
    assert '"' not in fake_client.esql.last_query.split("WHERE")[1].split("|")[0]
    assert "source == ?" in fake_client.esql.last_query


def test_top_entity_types_by_source_coerces_limit_to_int(monkeypatch):
    fake_client = _FakeClient()
    monkeypatch.setattr(es, "get_client", lambda: fake_client)

    es.top_entity_types_by_source("gtfs_metrolink", limit=7)

    assert "LIMIT 7" in fake_client.esql.last_query
