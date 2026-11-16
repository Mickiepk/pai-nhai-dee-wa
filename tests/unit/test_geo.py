import pytest

from adapters.models import LatLng
from features.geo import format_km, haversine_km, maps_link


def test_haversine_zero():
    p = LatLng(lat=13.78, lng=100.54)
    assert haversine_km(p, p) == 0


def test_haversine_siam_to_ari_about_4km():
    siam, ari = LatLng(lat=13.7457, lng=100.5343), LatLng(lat=13.7797, lng=100.5446)
    assert haversine_km(siam, ari) == pytest.approx(3.93, abs=0.1)


def test_haversine_bangkok_to_chiang_mai():
    bkk, cnx = LatLng(lat=13.7563, lng=100.5018), LatLng(lat=18.7883, lng=98.9853)
    assert haversine_km(bkk, cnx) == pytest.approx(583, abs=5)


def test_format_km():
    assert format_km(0.45) == "~450 ม."
    assert format_km(1.234) == "~1.2 กม."


def test_maps_link_has_place_id():
    assert "query_place_id=abc" in maps_link("ร้าน A", "abc")
