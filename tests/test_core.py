"""Test delle funzioni pure (nessuna rete, nessuna chiave)."""

import pytest

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


# --- validazione del copione (bug del 3 e 17 agosto 2026: la sintesi vocale
# leggeva il ragionamento del modello invece del copione) ---

COPIONE_BUONO = (
    "KANRI Tape, settimana dal dieci al diciassette agosto duemilaventisei. "
    "Questa settimana il filo conduttore è il ritorno dell'artigianato nel design "
    "contemporaneo. Il produttore giapponese ha presentato una cabina in acciaio "
    "pensata per offrire sollievo dal caldo estremo, con un sistema di "
    "raffreddamento che non richiede energia esterna. Poi il festival della stampa "
    "sperimentale torna per il terzo anno con laboratori aperti al pubblico e "
    "inchiostri ricavati dalle alghe. E infine una collezione di mobili che unisce "
    "linee sobrie e motivi tessili della tradizione. Trovate tutti gli articoli "
    "sul sito della rivista, buon ascolto e buona lettura."
)

RAGIONAMENTO = (
    "We need to produce a spoken script, ~300-350 words, about the week. "
    "Must not invent facts beyond provided. We must avoid markdown and bullet "
    "points. Let's craft the text now and count the words carefully before "
    "answering the user with the final Italian script for the podcast episode. "
    "We should select three or four articles and give each one a couple of "
    "sentences, then close with an invitation to read the magazine online. "
    "The user wants plain text only, so no symbols and no headings at all."
)


def test_valida_copione_accetta_italiano_parlato():
    ok, motivo = kp._valida_copione(COPIONE_BUONO)
    assert ok, motivo


def test_valida_copione_rifiuta_ragionamento_del_modello():
    ok, motivo = kp._valida_copione(RAGIONAMENTO)
    assert not ok and "ragionamento" in motivo


def test_valida_copione_rifiuta_inglese_senza_marcatori():
    inglese = (
        "The Japanese manufacturer presented a stainless steel cabin designed to "
        "offer immediate relief from extreme heat. The unit is portable and can be "
        "placed in public spaces, using a passive cooling system that requires no "
        "external power source at all, with clear signage for emergency use today. "
        "The printing festival returns for a third year with open workshops and "
        "inks made from algae, while a furniture collection blends sober lines "
        "with traditional textile motifs from South Asia and solid wood frames."
    )
    ok, motivo = kp._valida_copione(inglese)
    assert not ok and "italiano" in motivo


def test_valida_copione_rifiuta_troppo_corto():
    ok, motivo = kp._valida_copione("KANRI Tape, buon ascolto.")
    assert not ok and "corto" in motivo


def test_puntata_in_sospeso_trova_quella_non_pubblicata(tmp_path, monkeypatch):
    import datetime

    monkeypatch.chdir(tmp_path)
    ieri = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    (tmp_path / f"{kp.PODCAST_SLUG}-{ieri}.txt").write_text(COPIONE_BUONO, encoding="utf-8")
    assert kp._puntata_in_sospeso() == datetime.date.fromisoformat(ieri)


def test_puntata_in_sospeso_ignora_quella_gia_pubblicata(tmp_path, monkeypatch):
    import datetime

    monkeypatch.chdir(tmp_path)
    ieri = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    (tmp_path / f"{kp.PODCAST_SLUG}-{ieri}.txt").write_text(COPIONE_BUONO, encoding="utf-8")
    (tmp_path / f"{kp.PODCAST_SLUG}-{ieri}.state.json").write_text(
        '{"done": true}', encoding="utf-8"
    )
    assert kp._puntata_in_sospeso() is None


def test_data_puntata_in_ripresa_non_inventa_una_puntata_nuova(tmp_path, monkeypatch):
    """Il bug da evitare: un ritento il martedì che genera una puntata di martedì
    invece di pubblicare quella di lunedì rimasta in sospeso."""
    import datetime

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PODCAST_RESUME", "1")
    monkeypatch.delenv("PODCAST_DATE", raising=False)
    ieri = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    (tmp_path / f"{kp.PODCAST_SLUG}-{ieri}.txt").write_text(COPIONE_BUONO, encoding="utf-8")
    assert kp._data_puntata() == datetime.date.fromisoformat(ieri)
    # senza nulla in sospeso il ritento esce senza fare danni
    (tmp_path / f"{kp.PODCAST_SLUG}-{ieri}.txt").unlink()
    with pytest.raises(SystemExit):
        kp._data_puntata()


def test_prepara_copione_recupera_la_bozza_dopo_il_ragionamento():
    grezzo = f'{RAGIONAMENTO}\n\nDraft:\n\n"{COPIONE_BUONO}"'
    out = kp._prepara_copione(grezzo)
    assert kp._valida_copione(out)[0]
    assert out.startswith("KANRI Tape")
    assert "We need to" not in out
