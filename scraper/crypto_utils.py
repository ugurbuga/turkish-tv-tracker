import base64


SECRET_KEY = "turkish-tv-tracker-2026"


def xor_encrypt(value):
    if value is None:
        return None

    key = SECRET_KEY.encode("utf-8")
    payload = value.encode("utf-8")

    encrypted = bytes(
        byte ^ key[index % len(key)]
        for index, byte in enumerate(payload)
    )

    return base64.b64encode(encrypted).decode("ascii")


def xor_decrypt(value):
    if value is None:
        return None

    key = SECRET_KEY.encode("utf-8")
    encrypted = base64.b64decode(value.encode("ascii"))

    decrypted = bytes(
        byte ^ key[index % len(key)]
        for index, byte in enumerate(encrypted)
    )

    return decrypted.decode("utf-8")
