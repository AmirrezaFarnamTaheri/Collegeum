"""Check the vendored tweet parser works without setuptools pkg_resources."""

from twitter_text import extract_emojis_with_indices, parse_tweet


def test_vendored_twitter_text_uses_unicode_data_without_pkg_resources():
    assert parse_tweet("漢字 👨‍👩‍👧‍👦 https://example.org/path").valid
    assert parse_tweet("漢字").weightedLength == 4
    assert parse_tweet("https://example.org/path").weightedLength == 23
    assert extract_emojis_with_indices("x👨‍👩‍👧‍👦y")[0]["indices"] == [1, 8]


def test_vendored_emoji_resource_is_in_package():
    from importlib.resources import files

    data = files("twitter_text.regexp").joinpath("emoji-test.txt").read_text("utf-8")
    assert "Emoji" in data and "fully-qualified" in data
