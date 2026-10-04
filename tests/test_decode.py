"""Model çıktısından JSON çıkarma ve onarma."""

from __future__ import annotations

import pytest

from kitapai.serve.decode import decode


def test_temiz_json():
    r = decode('{"picks":[{"id":"a1","why":"iyi bir kitap"}],"followups":["soru?"]}')
    assert r.ok and not r.repaired
    assert r.output.picks[0].id == "a1"
    assert r.output.followups == ["soru?"]


@pytest.mark.parametrize("raw", [
    '```json\n{"picks":[{"id":"a2","why":"x"}]}\n```',
    'İşte önerilerim:\n{"picks":[{"id":"a2","why":"x"}]}\nUmarım beğenirsin.',
    '   {"picks":[{"id":"a2","why":"x"}]}   ',
])
def test_sarmalanmis_json(raw):
    r = decode(raw)
    assert r.ok and r.output.picks[0].id == "a2"


def test_sondaki_virgul_onariliyor():
    r = decode('{"picks":[{"id":"a4","why":"z"},],}')
    assert r.ok and r.repaired


@pytest.mark.parametrize("raw,expected_id", [
    ('{"picks":[{"id":"a5","why":"yarım kalmış cümle', "a5"),
    ('{"picks":[{"id":"a6","why":', "a6"),
    ('{"picks":[{"id":"a7","why":"tam","hooks":["bir","iki"', "a7"),
])
def test_kesilmis_cikti_kurtariliyor(raw, expected_id):
    """Token sınırında kesilen üretim, iç içe parantezler doğru kapatılarak kurtarılır."""
    r = decode(raw)
    assert r.ok and r.repaired
    assert r.output.picks[0].id == expected_id


def test_metin_icindeki_susluler_bozmuyor():
    r = decode('{"picks":[{"id":"a8","why":"şu {böyle} bir şey"}]}')
    assert r.ok and r.output.picks[0].why == "şu {böyle} bir şey"


def test_gecersiz_cikti_sessizce_gecmiyor():
    for raw in ("", "   ", "hiç json yok burada", "[1,2,3]"):
        r = decode(raw)
        assert not r.ok and r.error


def test_guven_degeri_siniri_asamaz():
    r = decode('{"picks":[{"id":"a1","why":"x","confidence":7}]}')
    assert r.ok and r.output.picks[0].confidence == 1.0
    r = decode('{"picks":[{"id":"a1","why":"x","confidence":"çok"}]}')
    assert r.ok and 0.0 <= r.output.picks[0].confidence <= 1.0


def test_tekil_deger_listeye_cevriliyor():
    r = decode('{"picks":[{"id":"a1","why":"x","hooks":"tek çengel"}],"followups":"tek soru"}')
    assert r.ok
    assert r.output.picks[0].hooks == ["tek çengel"]
    assert r.output.followups == ["tek soru"]
