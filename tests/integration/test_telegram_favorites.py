"""Private favorites are per-user, idempotent, and never subscriber opt-ins."""
from __future__ import annotations

from predoc_pipeline.publish.feedback import FeedbackStore


def test_favorites_are_private_and_survive_encrypted_restart(tmp_path):
    from cryptography.fernet import Fernet

    path = tmp_path / "private.json"
    key = Fernet.generate_key().decode("ascii")
    a = "a" * 16
    with_user = FeedbackStore(path, key=key)
    assert with_user.add_favorite(101, a)
    assert with_user.add_favorite(202, a)
    assert not with_user.add_favorite(101, a)
    assert [p for p in with_user.favorites(101)] == [a]
    assert with_user.subscribers == {}
    with_user.save()

    again = FeedbackStore(path, key=key)
    assert again.favorites(101) == [a]
    assert again.favorites(202) == [a]
    assert again.remove_favorite(101, a)
    assert again.favorites(101) == []
    assert again.favorites(202) == [a]
    again.delete_favorites(202)
    assert again.favorites(202) == []


def test_favorites_reject_invalid_hashes_and_capacity(tmp_path):
    from pytest import raises

    store = FeedbackStore(tmp_path / "private.json")
    with raises(ValueError):
        store.add_favorite(10, "bad")
    with raises(ValueError):
        store.add_favorite(-1, "a" * 16)
    for i in range(200):
        assert store.add_favorite(10, f"{i:016x}")
    with raises(ValueError, match="limit"):
        store.add_favorite(10, "f" * 16)
