import jwt

token = input("Enter JWT token: ")

# Load public key
with open("public_key.pem", "r") as f:
    public_key = f.read()

try:
    decoded = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"]
    )

    print("JWT is valid")
    print("Payload:")
    print(decoded)

except jwt.ExpiredSignatureError:
    print("Token expired")

except jwt.InvalidTokenError:
    print("Invalid token")