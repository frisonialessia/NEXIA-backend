from app.auth.passwords import hash_password, verify_password


def test_hash_no_es_plano_y_verifica():
    h = hash_password("demo1234")
    assert h != "demo1234"
    assert verify_password("demo1234", h)


def test_password_incorrecta():
    assert not verify_password("otra", hash_password("demo1234"))


def test_hash_invalido_no_lanza():
    assert verify_password("x", "no-es-un-hash") is False
