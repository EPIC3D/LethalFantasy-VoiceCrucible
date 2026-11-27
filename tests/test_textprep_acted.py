"""Written-out sighs and gasps are acted, not read aloud."""

from voicecrucible.textprep import prepare


def test_sigh_and_gasp_at_the_start_are_acted():
    assert prepare("Sigh… living large").startswith("Haaah...")
    assert prepare("Sigh, this is taking too long") == "Haaah... this is taking too long"
    assert prepare("Gasp! No way!") == "Hah! No way!"
    assert prepare("Well *sigh* fine") == "Well Haaah... fine"


def test_sigh_inside_a_sentence_stays_a_word():
    assert prepare("She lets out a big sigh.") == "She lets out a big sigh."
    assert prepare("Sighing is fine") == "Sighing is fine"


def test_ok_is_spoken_as_okay():
    assert prepare("You ok?") == "You okay?"
    assert prepare("OK, fine") == "okay, fine"
