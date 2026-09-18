import boto3
import datetime
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

s3 = boto3.client("s3")
acm = boto3.client("acm")


# -----------------------------
# Helper: create RSA key
# -----------------------------
def generate_key():
    return rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )


# -----------------------------
# Helper: serialize key
# -----------------------------
def pem_private_key(key):
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )


def pem_cert(cert):
    return cert.public_bytes(serialization.Encoding.PEM)


# -----------------------------
# Create Root CA
# -----------------------------
def create_root_ca():

    key = generate_key()

    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Example Root CA"),
        x509.NameAttribute(NameOID.COMMON_NAME, "Example Root CA"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
        .sign(key, hashes.SHA256())
    )

    return key, cert


# -----------------------------
# Create Intermediate CA
# -----------------------------
def create_intermediate_ca(root_key, root_cert):

    key = generate_key()

    subject = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Example Intermediate CA"),
        x509.NameAttribute(NameOID.COMMON_NAME, "Example Intermediate CA"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(root_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
        .sign(root_key, hashes.SHA256())
    )

    return key, cert


# -----------------------------
# Create TLS inspection cert
# -----------------------------
def create_tls_cert(intermediate_key, intermediate_cert):

    key = generate_key()

    subject = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Example TLS Inspection"),
        x509.NameAttribute(NameOID.COMMON_NAME, "tls-inspection.local"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(intermediate_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("tls-inspection.local")
            ]),
            False
        )
        .sign(intermediate_key, hashes.SHA256())
    )

    return key, cert


# -----------------------------
# Lambda Handler
# -----------------------------
def handler(event, context):

    bucket = event["BucketName"]

    # 1 Generate Root CA
    root_key, root_cert = create_root_ca()

    # 2 Generate Intermediate CA
    inter_key, inter_cert = create_intermediate_ca(root_key, root_cert)

    # 3 Generate TLS Inspection Certificate
    tls_key, tls_cert = create_tls_cert(inter_key, inter_cert)

    # Convert to PEM
    root_pem = pem_cert(root_cert)
    inter_pem = pem_cert(inter_cert)
    tls_pem = pem_cert(tls_cert)

    tls_key_pem = pem_private_key(tls_key)

    # Certificate chain
    chain = inter_pem + root_pem

    # 4 Import TLS Certificate to ACM
    resp = acm.import_certificate(
        Certificate=tls_pem,
        PrivateKey=tls_key_pem,
        CertificateChain=chain
    )

    cert_arn = resp["CertificateArn"]

    # 5 Upload Root CA to S3
    s3.put_object(
        Bucket=bucket,
        Key="tls-inspection-root-ca.pem",
        Body=root_pem
    )

    return {
        "status": "success",
        "certificateArn": cert_arn
    }