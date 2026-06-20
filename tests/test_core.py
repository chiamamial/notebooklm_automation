"""Test delle funzioni pure (nessuna rete, nessuna chiave)."""

import config
import kanri_engine as ke
import kanri_podcast as kp
import notion_sync as ns

# --- config ---


def test_config_caricata():
    assert config.BRAND == "KANRI"
    assert "Musica Elettronica" in config.CATEGORIE_NOMI
    assert len(config.CATEGORIE_NOMI) == 5


# --- kanri_engine ---


def test_extract_json_array():
    out = ke.extract_json('rumore prima [{"a": 1}, {"a": 2}] rumore dopo')
    assert out == [{"a": 1}, {"a": 2}]


def test_extract_json_oggetto():
    assert ke.extract_json('```json\n{"x": 10}\n```') == {"x": 10}


def test_pulisci_toglie_citazioni():
    out = ke.pulisci("Testo con nota [1] e altra 【2】 qui.")
    assert "[1]" not in out and "【2】" not in out


def test_split_tts_rispetta_limite():
    testo = "\n\n".join(["Frase di prova lunga e ripetuta. " * 20 for _ in range(10)])
    blocchi = ke._split_tts(testo, limit=500)
    assert blocchi and all(len(b) <= 500 for b in blocchi)


def test_md_to_html_grassetto_e_heading():
    html = ke.md_to_html("# Titolo\nTesto **forte**.")
    assert "<h1>" in html and "<strong>forte</strong>" in html


# --- notion_sync ---


def test_normalizza_categoria():
    assert ns.normalizza_categoria("graphic design") == "Graphic Design"
    assert ns.normalizza_categoria("MUSICA  elettronica") == "Musica Elettronica"
    assert ns.normalizza_categoria("inesistente") is None


# --- kanri_podcast ---


def test_settimana_label_stesso_mese():
    import datetime

    assert kp.settimana_label(datetime.date(2026, 6, 15)) == "8–15 giugno 2026"


def test_stima_durata():
    assert kp.stima_durata(" ".join(["x"] * 155)) == "01:00"


def test_taglia_a_caratteri_su_confine_frase():
    t = "Frase uno. Frase due lunga. Frase tre."
    assert kp.taglia_a_caratteri(t, 12) == "Frase uno."
    assert kp.taglia_a_caratteri("Corto.", 100) == "Corto."


def test_pulisci_copione_toglie_markdown():
    out = kp._pulisci_copione("# Titolo\n\n- punto\n**ciao** mondo\nINTRO:\n")
    assert "#" not in out and "*" not in out and "- punto" not in out
