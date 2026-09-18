import json
import urllib.request
import boto3
import datetime
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

acm_client = boto3.client('acm')
s3_client = boto3.client('s3')

def send_response(event, context, status, data, physical_id=None):
    """Sends the custom resource response back to CloudFormation."""
    body = json.dumps({
        "Status": status,
        "Reason": f"See CloudWatch Logs: {context.log_stream_name}",
        "PhysicalResourceId": physical_id or context.log_stream_name,
        "StackId": event['StackId'],
        "RequestId": event['RequestId'],
        "LogicalResourceId": event['LogicalResourceId'],
        "Data": data
    }).encode('utf-8')

    try:
        req = urllib.request.Request(event['ResponseURL'], data=body, method='PUT')
        req.add_header('Content-Type', '')
        urllib.request.urlopen(req)
        print(f"Successfully sent {status} to CloudFormation.")
    except Exception as e:
        print(f"Failed to signal CloudFormation: {e}")

def build_subject_name(common_name):
    """Replicates the req_distinguished_name block from openssl.cnf"""
    return x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"VA"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"IAD28"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"Custom Org"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, u"Custom Unit"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.EMAIL_ADDRESS, u"custom-dev@amazon.com"),
    ])

def generate_ca(common_name, days_valid, is_root=False, issuer_cert=None, issuer_key=None):
    """Generates a CA certificate replicating the bash script logic."""
    print(f"Generating {'Root' if is_root else 'Intermediate'} CA: {common_name}...")
    
    # 1. Generate Key (4096 bit as per bash script)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    
    # 2. Setup Subject and Issuer
    subject = build_subject_name(common_name)
    issuer = subject if is_root else issuer_cert.subject
    signing_key = private_key if is_root else issuer_key

    # 3. Build Certificate
    builder = x509.CertificateBuilder()
    builder = builder.subject_name(subject)
    builder = builder.issuer_name(issuer)
    builder = builder.public_key(private_key.public_key())
    builder = builder.serial_number(x509.random_serial_number())
    builder = builder.not_valid_before(datetime.datetime.utcnow() - datetime.timedelta(days=1))
    builder = builder.not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=days_valid))

    # 4. Extensions (v3_ca & v3_intermediate_ca)
    # Basic Constraints
    builder = builder.add_extension(
        x509.BasicConstraints(ca=True, path_length=None if is_root else 0),
        critical=True,
    )
    # Key Usage (digitalSignature, cRLSign, keyCertSign)
    builder = builder.add_extension(
        x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=True,
            crl_sign=True, encipher_only=False, decipher_only=False
        ),
        critical=True,
    )
    
    # Subject Key Identifier
    builder = builder.add_extension(
        x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()),
        critical=False
    )

    # Authority Key Identifier
    auth_pub_key = private_key.public_key() if is_root else issuer_key.public_key()
    builder = builder.add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(auth_pub_key),
        critical=False
    )

    # 5. Sign the certificate (SHA256)
    certificate = builder.sign(private_key=signing_key, algorithm=hashes.SHA256())
    
    return private_key, certificate

def get_pem_cert(cert):
    return cert.public_bytes(serialization.Encoding.PEM)

def get_pem_key(key):
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL, # Equivalent to standard openssl genrsa
        encryption_algorithm=serialization.NoEncryption()
    )

def handler(event, context):
    print("Received event:", json.dumps(event))

    if event['RequestType'] == 'Delete':
        # During stack deletion, we do nothing to the certs. They can be cleaned up manually or via retention policies.
        send_response(event, context, "SUCCESS", {})
        return

    try:
        # Configuration
        bucket_name = event.get('ResourceProperties', {}).get('BucketName', 'tls-inspection-bucket')
        
        # 1. Generate Root CA (7300 days / 20 years)
        root_key, root_cert = generate_ca("Custom Root CA", days_valid=7300, is_root=True)
        root_cert_pem = get_pem_cert(root_cert)

        # 2. Generate Intermediate CA (3650 days / 10 years)
        int_key, int_cert = generate_ca(
            "Custom Intermediate CA", 
            days_valid=3650, 
            is_root=False, 
            issuer_cert=root_cert, 
            issuer_key=root_key
        )
        int_cert_pem = get_pem_cert(int_cert)
        int_key_pem = get_pem_key(int_key)

        # 3. Upload Root CA to S3
        print(f"Uploading Root CA to S3 bucket: {bucket_name}")
        s3_client.put_object(
            Bucket=bucket_name,
            Key='ca.cert.pem',
            Body=root_cert_pem,
            ContentType='application/x-pem-file'
        )

        # 4. Import Intermediate CA to ACM
        print("Importing Intermediate CA to AWS Certificate Manager")
        acm_response = acm_client.import_certificate(
            Certificate=int_cert_pem,
            PrivateKey=int_key_pem,
            CertificateChain=root_cert_pem,
            Tags=[{'Key': 'Name', 'Value': 'firewall-tls-inspection'}]
        )
        
        cert_arn = acm_response['CertificateArn']
        print(f"Successfully imported cert: {cert_arn}")

        # Respond to CloudFormation with the new ARN
        send_response(event, context, "SUCCESS", {"CertificateArn": cert_arn}, physical_id=cert_arn)

    except Exception as e:
        import traceback
        print("Error encountered:")
        traceback.print_exc()
        send_response(event, context, "FAILED", {"Error": str(e)})