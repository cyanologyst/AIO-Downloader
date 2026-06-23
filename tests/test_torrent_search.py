from app.services.torrent_search import TPBClient


def test_tpb_magnet_contains_hash_and_name():
    magnet = TPBClient.magnet("ABC123", "Ubuntu Linux")
    assert "xt=urn:btih:ABC123" in magnet
    assert "dn=Ubuntu%20Linux" in magnet
