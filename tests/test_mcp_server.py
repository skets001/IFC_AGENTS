from types import SimpleNamespace


def test_mcp_model_cache_evicts_oldest(monkeypatch, tmp_path):
    from ifc_agent.mcp_server import server

    opened = []

    def fake_open(path):
        opened.append(path)
        return SimpleNamespace(path=path)

    paths = []
    for name in ["one.ifc", "two.ifc", "three.ifc"]:
        path = tmp_path / name
        path.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
        paths.append(path)

    monkeypatch.setattr(server, "_MODEL_CACHE_SIZE", 2)
    monkeypatch.setattr(server.ifcopenshell, "open", fake_open)
    server._model_cache.clear()

    first = server._get_model(str(paths[0]))
    second = server._get_model(str(paths[1]))
    third = server._get_model(str(paths[2]))

    assert [first.path, second.path, third.path] == [str(paths[0]), str(paths[1]), str(paths[2])]
    assert len(server._model_cache) == 2
    assert str(paths[0].resolve()) not in server._model_cache
    assert str(paths[1].resolve()) in server._model_cache
    assert str(paths[2].resolve()) in server._model_cache
    assert opened == [str(paths[0]), str(paths[1]), str(paths[2])]
