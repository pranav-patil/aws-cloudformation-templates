import jwt
from datetime import datetime, timedelta

# Load private key
with open("private_key.pem", "r") as f:
    private_key = f.read()

payload = {
    "sub": "1234567890",
    "name": "John Doe",
    "iat": datetime.utcnow(),
    "exp": datetime.utcnow() + timedelta(minutes=30)
}

token = jwt.encode(
    payload,
    private_key,
    algorithm="RS256"
)

print("Signed JWT:\n")
print(token)