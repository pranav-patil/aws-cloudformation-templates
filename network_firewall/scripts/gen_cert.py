import json, boto3, datetime, urllib.request
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

acm = boto3.client('acm')
s3 = boto3.client('s3')

def create_ca(subject_name, issuer_key=None, issuer_cert=None, is_root=False):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TREND AI CA"),
        x509.NameAttribute(NameOID.COMMON_NAME, "TREND AI Root CA"),
    ])
    
    # If root, it signs itself. If intermediate, issuer signs it.
    issuer_name = subject if is_root else issuer_cert.subject
    signing_key = key if is_root else issuer_key

    builder = x509.CertificateBuilder()
    builder = builder.subject_name(subject)
    builder = builder.issuer_name(issuer_name)
    builder = builder.public_key(key.public_key())
    builder = builder.serial_number(x509.random_serial_number())
    builder = builder.not_valid_before(datetime.datetime.utcnow())
    builder = builder.not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
    
    # AWS Requirement: Basic Constraints must have CA:True
    builder = builder.add_extension(
        x509.BasicConstraints(ca=True, path_length=None if is_root else 0),
        critical=True,
    )
    # AWS Requirement: Key Usage must include Cert Signing and CRL Signing
    builder = builder.add_extension(
        x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, cert_sign=True,
            crl_sign=True, encipher_only=False, decipher_only=False
        ),
        critical=True,
    )
    
    cert = builder.sign(signing_key, hashes.SHA256())
    return key, cert

def send_cfn(event, context, status, data, physical_id=None):
    body = json.dumps({"Status": status, "PhysicalResourceId": physical_id or context.log_stream_name,
                        "StackId": event['StackId'], "RequestId": event['RequestId'],
                        "LogicalResourceId": event['LogicalResourceId'], "Data": data}).encode('utf-8')
    req = urllib.request.Request(event['ResponseURL'], data=body, method='PUT')
    urllib.request.urlopen(req)

def handler(event, context):
    if event['RequestType'] == 'Delete':
        send_cfn(event, context, "SUCCESS", {})
        return

    try:
        # 1. Generate Root CA
        root_key, root_cert = create_ca("MyRootCA", is_root=True)
        
        # 2. Generate Intermediate CA (The Inspection Cert)
        int_key, int_cert = create_ca("MyFirewallInspectionCA", issuer_key=root_key, issuer_cert=root_cert)

        # 3. Serialize to PEM
        root_pem = root_cert.public_bytes(serialization.Encoding.PEM)
        int_pem = int_cert.public_bytes(serialization.Encoding.PEM)
        int_key_pem = int_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        )

        # 4. Upload Root to S3 (for EC2 trust store)
        s3.put_object(Bucket=event['ResourceProperties']['BucketName'], Key='ca.cert.crt', Body=root_pem)

        # 5. Import Intermediate to ACM
        # The 'CertificateChain' is the Root CA
        response = acm.import_certificate(
            Certificate=int_pem,
            PrivateKey=int_key_pem,
            CertificateChain=root_pem,
            Tags=[{'Key': 'Name', 'Value': 'firewall-tls-inspection'}]
        )
        
        send_cfn(event, context, "SUCCESS", {"CertificateArn": response['CertificateArn']}, physical_id=response['CertificateArn'])
    except Exception as e:
        print(str(e))
        send_cfn(event, context, "FAILED", {"Error": str(e)})