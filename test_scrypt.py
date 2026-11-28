
import os
import hmac
import hashlib
import base64


# Scrypt settings
N = 2**15
R = 8
P = 3


# Generate password hash
def hash_password(password):

    # Generate random salt
    salt = os.urandom(16)

    # Generate hash using password and salt
    hashed = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=N,
        r=R,
        p=P,
        dklen=32
    )

    # Convert salt and hash into storable text
    salt_text = base64.b64encode(salt).decode()
    hash_text = base64.b64encode(hashed).decode()

    return salt_text + "$" + hash_text


# Verify password during login
def verify_password(entered_password, stored_hash):

    try:
        # Get original salt and stored hash
        salt_text, hash_text = stored_hash.split("$")

        salt = base64.b64decode(salt_text)
        original_hash = base64.b64decode(hash_text)

        # Generate hash using entered password and original salt
        new_hash = hashlib.scrypt(
            entered_password.encode("utf-8"),
            salt=salt,
            n=N,
            r=R,
            p=P,
            dklen=32
        )

        # Compare both hashes
        return hmac.compare_digest(new_hash, original_hash)

    except (ValueError, TypeError):
        return False


# TESTING
if __name__ == "__main__":

    # Registration
    password = "Sap@2026"

    stored_hash = hash_password(password)

    print("Stored Hash:", stored_hash)

    # Login with correct password
    print("Correct Password:",
          verify_password("Sap@2026", stored_hash))

    # Login with wrong password
    print("Wrong Password:",
          verify_password("Wrong@123", stored_hash))

    # Login with another wrong password
    print("Another Wrong Password:",
          verify_password("sap@2026", stored_hash))
