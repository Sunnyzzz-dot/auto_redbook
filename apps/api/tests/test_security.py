import pytest

from app.core.security import hash_password, verify_password


def test_hash_password_round_trips() -> None:
    hashed = hash_password("correct horse battery staple")

    assert hashed.startswith("$2b$")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_hash_password_rejects_bcrypt_passwords_over_72_bytes() -> None:
    with pytest.raises(ValueError):
        hash_password("a" * 73)

