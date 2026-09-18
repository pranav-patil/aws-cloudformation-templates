"""
CloudFormation Custom Resource Lambda handler for TLS Inspection Certificate Generation.

Generates a 3-level certificate chain:
  Root CA → Intermediate CA → TLS Leaf Certificate

The TLS leaf certificate is imported to ACM with Intermediate + Root as the chain.
The Root CA is uploaded to S3 for EC2 instance trust store configuration.

Usage in CloudFormation:
  ResourceProperties:
    BucketName: <S3 bucket for Root CA upload>
"""

import json
import boto3
import datetime
import urllib.request
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

acm = boto3.client("acm")
s3 = boto3.client("s3")


# -----------------------------
# Helper: Generate RSA key
# -----------------------------
def generate_key():
    """Generate a 2048-bit RSA private key."""
    return rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )


# -----------------------------
# Helper: Serialize private key to PEM
# -----------------------------
def pem_private_key(key):
    """Serialize private key to PEM format (unencrypted)."""
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )


# -----------------------------
# Helper: Serialize certificate to PEM
# -----------------------------
def pem_cert(cert):
    """Serialize certificate to PEM format."""
    return cert.public_bytes(serialization.Encoding.PEM)


# -----------------------------
# Create Root CA
# -----------------------------
def create_root_ca():
    """
    Create a self-signed Root CA certificate.
    
    Returns:
        tuple: (private_key, certificate)
    """
    key = generate_key()

    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TLS Inspection Root CA"),
        x509.NameAttribute(NameOID.COMMON_NAME, "TLS Inspection Root CA"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)  # Self-signed
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
        # AWS Requirement: Basic Constraints must have CA:True
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True
        )
        # AWS Requirement: Key Usage must include Cert Signing and CRL Signing
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False
            ),
            critical=True
        )
        .sign(key, hashes.SHA256())
    )

    return key, cert


# -----------------------------
# Create Intermediate CA
# -----------------------------
def create_intermediate_ca(root_key, root_cert):
    """
    Create an Intermediate CA certificate signed by the Root CA.
    
    Args:
        root_key: Root CA private key for signing
        root_cert: Root CA certificate (issuer)
    
    Returns:
        tuple: (private_key, certificate)
    """
    key = generate_key()

    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TLS Inspection Intermediate CA"),
        x509.NameAttribute(NameOID.COMMON_NAME, "TLS Inspection Intermediate CA"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(root_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
        # AWS Requirement: Basic Constraints must have CA:True, path_length=0 for intermediate
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=0),
            critical=True
        )
        # AWS Requirement: Key Usage must include Cert Signing and CRL Signing
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False
            ),
            critical=True
        )
        .sign(root_key, hashes.SHA256())
    )

    return key, cert


# -----------------------------
# Create TLS Leaf Certificate
# -----------------------------
def create_tls_leaf_cert(intermediate_key, intermediate_cert):
    """
    Create a TLS leaf certificate signed by the Intermediate CA.
    This certificate is used for TLS inspection by AWS Network Firewall.
    
    Args:
        intermediate_key: Intermediate CA private key for signing
        intermediate_cert: Intermediate CA certificate (issuer)
    
    Returns:
        tuple: (private_key, certificate)
    """
    key = generate_key()

    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TLS Inspection"),
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
        # Basic Constraints: Not a CA
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True
        )
        # Key Usage for TLS server certificate
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False
            ),
            critical=True
        )
        # Extended Key Usage for TLS
        .add_extension(
            x509.ExtendedKeyUsage([
                x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
                x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
            ]),
            critical=False
        )
        # Subject Alternative Name
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("tls-inspection.local"),
                x509.DNSName("*.tls-inspection.local"),
            ]),
            critical=False
        )
        .sign(intermediate_key, hashes.SHA256())
    )

    return key, cert


# -----------------------------
# CloudFormation Response Helper
# -----------------------------
def send_cfn(event, context, status, data, physical_id=None):
    """
    Send a response to CloudFormation's ResponseURL.
    
    Args:
        event: Lambda event containing CloudFormation request details
        context: Lambda context
        status: "SUCCESS" or "FAILED"
        data: Dictionary of response data
        physical_id: Physical resource ID (defaults to log stream name)
    """
    body = json.dumps({
        "Status": status,
        "PhysicalResourceId": physical_id or context.log_stream_name,
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": data
    }).encode("utf-8")
    
    req = urllib.request.Request(
        event["ResponseURL"],
        data=body,
        method="PUT",
        headers={"Content-Type": ""}
    )
    urllib.request.urlopen(req)


# -----------------------------
# Lambda Handler
# -----------------------------
def handler(event, context):
    """
    CloudFormation Custom Resource Lambda handler.
    
    Creates a 3-level certificate chain for AWS Network Firewall TLS inspection:
      1. Root CA (self-signed)
      2. Intermediate CA (signed by Root)
      3. TLS Leaf Certificate (signed by Intermediate)
    
    The TLS leaf cert is imported to ACM with the full chain.
    The Root CA is uploaded to S3 for EC2 trust store configuration.
    
    ResourceProperties:
        BucketName: S3 bucket name for Root CA upload
    
    Returns (via CloudFormation):
        CertificateArn: ARN of the imported ACM certificate
    """
    print(f"Received event: {json.dumps(event)}")
    
    # Handle Delete - nothing to clean up (ACM cert deletion is manual or via CFN)
    if event["RequestType"] == "Delete":
        send_cfn(event, context, "SUCCESS", {})
        return

    try:
        bucket_name = event["ResourceProperties"]["BucketName"]
        
        # 1. Generate Root CA
        print("Generating Root CA...")
        root_key, root_cert = create_root_ca()
        
        # 2. Generate Intermediate CA (signed by Root)
        print("Generating Intermediate CA...")
        inter_key, inter_cert = create_intermediate_ca(root_key, root_cert)
        
        # 3. Generate TLS Leaf Certificate (signed by Intermediate)
        print("Generating TLS Leaf Certificate...")
        tls_key, tls_cert = create_tls_leaf_cert(inter_key, inter_cert)
        
        # 4. Serialize to PEM
        root_pem = pem_cert(root_cert)
        inter_pem = pem_cert(inter_cert)
        tls_pem = pem_cert(tls_cert)
        tls_key_pem = pem_private_key(tls_key)
        
        # Certificate chain: Intermediate + Root
        chain_pem = inter_pem + root_pem
        
        # 5. Upload Root CA to S3 (for EC2 trust store)
        print(f"Uploading Root CA to s3://{bucket_name}/tls-inspection-root-ca.pem")
        s3.put_object(
            Bucket=bucket_name,
            Key="tls-inspection-root-ca.pem",
            Body=root_pem,
            ContentType="application/x-pem-file"
        )
        
        # 6. Import TLS Leaf Certificate to ACM
        print("Importing TLS certificate to ACM...")
        response = acm.import_certificate(
            Certificate=tls_pem,
            PrivateKey=tls_key_pem,
            CertificateChain=chain_pem,
            Tags=[
                {"Key": "Name", "Value": "network-firewall-tls-inspection"},
                {"Key": "Purpose", "Value": "TLS Inspection"},
                {"Key": "ManagedBy", "Value": "CloudFormation"}
            ]
        )
        
        cert_arn = response["CertificateArn"]
        print(f"Certificate imported successfully: {cert_arn}")
        
        # 7. Send success response to CloudFormation
        send_cfn(
            event, context, "SUCCESS",
            {"CertificateArn": cert_arn},
            physical_id=cert_arn
        )
        
    except Exception as e:
        error_msg = str(e)
        print(f"Error: {error_msg}")
        send_cfn(
            event, context, "FAILED",
            {"Error": error_msg}
        )
