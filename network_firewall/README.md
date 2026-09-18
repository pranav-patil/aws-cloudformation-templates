# AWS Network Firewall

AWS Cloud Formation Templates for various use-cases.

## CloudFormation Template Deployment

### Get AWS Token and set environment variables as below:

```bash
PUPPETEER_EXECUTABLE_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" aws-azure-login --mode=gui
export AWS_ACCOUNT_ID={$AWS_ACCOUNT_ID}
export AWS_REGION=us-east-1
export STACK_NAME="zyron-firewall-demo"
aws sts get-caller-identity --region ${AWS_REGION}
```

### Deploy Malware Traffic Generator scripts into AWS S3 Bucket (DEPRECATED)

```bash
export BUCKET_NAME="${STACK_NAME}-scripts-bucket"

aws s3 mb s3://$BUCKET_NAME
aws s3 cp ./traffic_scripts s3://$BUCKET_NAME/traffic_scripts --recursive
aws s3 ls "s3://$BUCKET_NAME/traffic_scripts/"
```

### Validate CloudFormation Template

```bash
aws cloudformation validate-template --template-body file://template.yaml
```

### Deploy CloudFormation Stack

```bash
aws cloudformation deploy --stack-name ${STACK_NAME} \
  --template-file template.yaml \
  --parameter-overrides Environment=dev ScriptsBucket=$BUCKET_NAME \
  --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND

aws cloudformation wait stack-create-complete --stack-name ${STACK_NAME}
```

### Get Description of CloudFormation Stack

```bash
aws cloudformation describe-stacks --stack-name ${STACK_NAME}
aws cloudformation describe-stack-events --stack-name ${STACK_NAME}
```

```bash
aws cloudformation describe-stacks --stack-name ${STACK_NAME} --query "Stacks[0].Outputs"

SSM_PARAM_NAME=$(aws cloudformation describe-stacks \
  --stack-name ${STACK_NAME} \
  --query "Stacks[0].Outputs[?OutputKey=='SSMParameterName'].OutputValue" \
  --output text)

aws ssm get-parameter \
  --name "$SSM_PARAM_NAME" \
  --with-decryption \
  --query "Parameter.Value" \
  --output text > generated-key.pem

chmod 600 generated-key.pem
```

Access EC2 Instance using below command: (use `ec2-user` for aws-ami, else `ubuntu` for ubuntu-ami)

```bash
ssh -i generated-key.pem ubuntu@[INSTANCE_IP_ADDRESS]
```

### Update Deployed CloudFormation Stack

We can update the Cloudformation stack using `aws deploy` command. We can use the below `update-stack` command to update the stack.

```bash
aws cloudformation update-stack --stack-name ${STACK_NAME} \
  --template-body file://template.yaml \
  --capabilities CAPABILITY_NAMED_IAM

aws cloudformation wait stack-update-complete \
  --stack-name ${STACK_NAME}
```

### RDP into EC2 Instance

After setting up the CloudFormation template `single_vpc_firewall_inspect_category_ai.yaml`, follow the below steps to connect to EC2 instance using RDP.

```bash
ssh -i "generated-key.pem" -L 33389:[DESKTOP_PRIVATE_IP]:3389 ubuntu@[BASTION_IP_ADDRESS]
```

Install [Microsoft Windows App](https://go.microsoft.com/fwlink/?linkid=868963) for remote desktop connect. Then click on `+` on top right hand corner and select `Add PC`. In the dialog enter PC Name as `127.0.0.1:33389`, under Credentials select `Add Credentials..` and enter username `ubuntu` and password `mysecret` set using `echo "ubuntu:mysecret" | chpasswd` in Cloudformation template. This should connect to EC2 Instance. If you are still seeing the shell/console then type `startx` to start GUI login.

If you are facing issues, check if RDP service is running in EC2 Instance using `sudo systemctl status xrdp`. If the service is not running then install the below.

```bash
# 1. Update the package list
sudo apt-get update

# 2. Install the Desktop environment (This may take 5-10 mins)
sudo apt-get install -y ubuntu-desktop

# 3. Install the RDP server
sudo apt-get install -y xrdp

# 4. Enable and start the service
sudo systemctl enable xrdp
sudo systemctl start xrdp

# 5. Fix the user password (required for RDP login)
echo "ubuntu:mysecret" | sudo chpasswd
```

Alternatively you can also use [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/install-plugin-macos-overview.html) and connect using below command. Faced **Connectivity issues**.

```bash
aws ssm start-session --target <Instance-ID-of-EC2InstanceA> \
--document-name AWS-StartPortForwardingSession \
--parameters '{"portNumber":["3389"],"localPortNumber":["33389"]}'
```

### Delete (Uninstall) a CloudFormation Stack

```bash
aws cloudformation delete-stack --stack-name ${STACK_NAME}
aws cloudformation wait stack-delete-complete --stack-name ${STACK_NAME}
```

## AWS Network Firewall with Managed & Custom RuleGroups

Setup AWS Network Firewall with AWS managed rule-group enabled and pass traffic through the Network Firewall to trigger the rules.

AWS provides various [deployment models for AWS Network Firewall](https://aws.amazon.com/blogs/networking-and-content-delivery/deployment-models-for-aws-network-firewall/) (Distributed Firewall model, Centralized Firewall model and Combined Firewall deployment model) which are mainly recommended for production environments. AWS samples contains [sample CloudFormation templates](https://github.com/aws-samples/aws-networkfirewall-cfn-templates) to provision AWS Network Firewall for testing & demo purpose.

Below are the basic requirements for our limited scope of Network Firewall configuration and testing.

1) Setup Network Firewall and subscribe to [Managed RuleGroup](https://aws.amazon.com/blogs/security/simplify-cloud-security-with-managed-rules-from-aws-marketplace-for-aws-network-firewall/) (`arn:aws:network-firewall:${AWS::Region}:aws-managed:stateful-rulegroup/ThreatSignaturesBotnetActionOrder`). Add `ThreatSignaturesBotnetActionOrder` to Stateful RuleGroup in FirewallPolicy. This rule group triggers on known botnet user agents and C2 heartbeats.
2) Private EC2 instance can only be access through Network Firewall
3) Private EC2 instance can access internet for file downloads or package installation, but traffic cannot be initiated from internet to private EC2 instance. All traffic initiated from internet has to pass through Network Firewall.
4) Public EC2 instance can access internet directly without Network firewall.
5) Public EC2 instance has to go through Network Firewall to access Private EC2 instance.

[Design1](network_firewall/diagrams/single_vpc_firewall_inspect.mmd): All resources reside in same VPC. Public/Private subnets used for routing public/private EC2 instances.

[Design2](network_firewall/diagrams/multi_vpc_firewall_inspect_tgw.mmd): Resources reside in separate VPCs. Transit-Gateway is used to route traffic between VPCs.

NOTE: To check the currently available list of rule-groups use below command: 

```bash
aws network-firewall list-rule-groups --scope ACCOUNT --type STATEFUL --region ${AWS_REGION}
```
## Setup TLS Configuration for Network Firewall (Manually)

The `single_vpc_firewall_inspect_category_ai.yaml` template sets up a `NetworkFirewall` attaches it to `TempFirewallPolicy` at first and creates `FirewallPolicy` with TLS Configuration. The template creates Keys and Certificate using `CertificateGeneratorFunction` Lambda which are used to create AWS Certificate. The AWS Certificate is used to setup TLS Configuration referenced by `FirewallPolicy` policy. The `EC2InstanceA` downloads the certificate `ca.cert.pem` stored in SSM parameter `SSMCertParameterName` into Ubuntu system trust store. Once custom CA certificate is added into the system trust-store, the policy of `NetworkFirewall` is switched from `TempFirewallPolicy` to `FirewallPolicy`. We also setup Firefox, Chrome and Claude.

Go to EC2 Instances, click on `Actions` -> `Monitor and troubleshoot` -> `Get system log` (under Troubleshoot) to view system startup logs if you see any issues.

### Create Private Key and Certificates

Ideally the `CertificateGeneratorFunction` Lambda in `single_vpc_firewall_inspect_category_ai.yaml` template generates the keys and certificates, but below commands can be used to achieve the same manually. The [setupcerts.zip](https://ws-assets-prod-iad-r-pdx-f3b3f9f1a7d6a3d0.s3.us-west-2.amazonaws.com/503778b9-6dbb-4e0d-9920-e8dbae141f43/setupcerts.zip) is AWS provided script from their [Demo setup sessions](https://aws.amazon.com/video/watch/6c1f0ab1f1b/). If `setupcerts.zip` is unavailable from the URL, then use `setupcerts.zip` from `network_firewall` using `cp setupcerts.zip /tmp/setupcerts.zip`.

```bash
wget -O /tmp/setupcerts.zip https://ws-assets-prod-iad-r-pdx-f3b3f9f1a7d6a3d0.s3.us-west-2.amazonaws.com/503778b9-6dbb-4e0d-9920-e8dbae141f43/setupcerts.zip
cd /tmp
unzip -o setupcerts.zip
cd setupcerts/

# Generate certificates
bash create_certs

# Install CA certificates package and update the system trust store
sudo apt update && sudo apt install -y ca-certificates

# Copy the CA cert to the Ubuntu-specific anchor directory
# Note: Ubuntu requires the file extension to be .crt for update-ca-certificates to pick it up
sudo cp /tmp/setupcerts/out-dir/root/ca/certs/ca.cert.pem /usr/local/share/ca-certificates/ca.cert.crt

# Update the trust store
sudo update-ca-certificates
```

### Import Custom Certificate into AWS Certificate Manager

```bash
CERT_ARN=$(aws acm import-certificate \
    --certificate fileb://tmp/setupcerts/out-dir/root/ca/intermediate/certs/intermediate.cert.pem \
    --private-key fileb://tmp/setupcerts/out-dir/root/ca/intermediate/private/intermediate.key.pem \
    --certificate-chain fileb://tmp/setupcerts/out-dir/root/ca/intermediate/certs/ca-chain.cert.pem \
    --tags Key=name,Value=tls-inspection-certificate \
    --query 'CertificateArn' \
    --output text)
```

### Delete Certificate from AWS Certificate Manager

```bash
aws acm delete-certificate --certificate-arn ${CERT_ARN}
```

## Testing TLS Configuration for Network Firewall

```bash
openssl s_client -connect yahoo.com:443

curl -v https://example.com --cacert ca.cert.pem

echo | openssl s_client -showcerts -servername [DOMAIN] -connect [DOMAIN]:443 2>/dev/null | openssl x509 -inform pem -noout -text
```

### Firefox HTTPS Access

First copy the certificate to local home path. Then to add custom certificate into FireFox, go to **Settings -> Privacy & Security**, then under **Certificates** click on **View Certificates...** which will open `Certificate Manager`. Click on **Import** in Certificate Manager, select **Home** and then select the `firewall-ca.crt` certificate file. Firefox should ask you under which category it should store the certificate, select "Authorities". Or it will maybe recognize by itself that it's a CA certfifcate and put it under the appropriate category. After you finish the import process, you can check if your imported certificate is visible in the "Authorities" section.

```bash
cp /usr/local/share/ca-certificates/firewall-ca.crt.
```

### Claude Setup

Ideally the EC2InstanceA should be setting up claude and pointing to custom certificate path. If Claude is still not setup then use below commands to achieve the same manually.

```bash
bash -c 'curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash && export NVM_DIR="$HOME/.nvm" && [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh" && nvm install 20 && nvm use 20 && npm install -g @anthropic-ai/claude-code'

export NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/firewall-ca.crt

ANTHROPIC_BASE_URL="https://localhost:4000/"
ANTHROPIC_AUTH_TOKEN="[YOUR_KEY]" claude
```

To add MCP server to Claude, use the below command

```bash
claude mcp add --transport http my-mcp-server https://[DOMAIN]:443/mcp
```

To delete MCP server already added to Claude, use the below command

```bash
claude mcp delete my-mcp-server
```
