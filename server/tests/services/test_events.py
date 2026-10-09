from app.services.events import Event, EventCollector


def test_coletor_guarda_e_entrega_na_ordem_uma_vez_so():
    coletor = EventCollector()
    coletor.add("u1", "oferta", {"ride_id": "ride-1"})
    coletor.add("u2", "aceita")
    assert coletor.events == (Event("u1", "oferta", {"ride_id": "ride-1"}), Event("u2", "aceita", {}))
    assert [e.type for e in coletor.drain()] == ["oferta", "aceita"]
    assert coletor.drain() == []
