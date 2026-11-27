from eventhub.sanitise import clip, strip_control


def test_newlines_cannot_forge_a_second_log_line():
    assert strip_control("ok\nFAKE user.create") == "ok FAKE user.create"


def test_surrounding_whitespace_is_removed():
    assert strip_control("  padded  ") == "padded"


def test_clip_cleans_then_truncates():
    assert clip("abcdefgh\n", 5) == "abcde"


def test_clip_passes_none_through():
    assert clip(None, 5) is None