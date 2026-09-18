# Ubuntu 22.04 LTS EC2 Instance with Auto-Generated Key Pair

This CloudFormation template deploys an Ubuntu 22.04 LTS EC2 instance into an existing VPC with a security group allowing SSH and RDP access. The key pair is auto-generated and stored in AWS SSM Parameter Store.

## Prerequisites

- An existing VPC with a public subnet (internet gateway attached and subnet route table pointing to it)
- AWS CLI configured with sufficient permissions
- Permissions to create: EC2 instances, key pairs, IAM roles, security groups, SSM parameters

## Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `ProjectName` | Prefix used for naming all resources | `UbuntuEC2Demo` |
| `VpcId` | ID of your existing VPC | _(required)_ |
| `SubnetId` | ID of a public subnet within the VPC | _(required)_ |
| `InstanceType` | EC2 instance type | `t3.large` |
| `AMI` | SSM path to Ubuntu 22.04 LTS AMI | `/aws/service/canonical/ubuntu/server/jammy/stable/current/amd64/hvm/ebs-gp2/ami-id` |

## Deploy the Template

### Option 1 — AWS CLI

```bash
aws cloudformation deploy \
  --template-file ubuntu_ec2_with_keypair.yaml \
  --stack-name my-ubuntu-ec2 \
  --parameter-overrides \
      ProjectName=MyProject \
      VpcId=vpc-xxxxxxxxxxxxxxxxx \
      SubnetId=subnet-xxxxxxxxxxxxxxxxx \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

### Option 2 — AWS Console

1. Open the [CloudFormation Console](https://console.aws.amazon.com/cloudformation)
2. Click **Create stack** → **With new resources**
3. Upload `ubuntu_ec2_with_keypair.yaml`
4. Fill in `VpcId` and `SubnetId` from your existing VPC
5. Acknowledge IAM capabilities and click **Create stack**

## Retrieve the Private Key

Once the stack is in `CREATE_COMPLETE` state, get the SSM parameter name from the stack outputs:

```bash
# Get the SSM parameter name from stack outputs
SSM_PARAM=$(aws cloudformation describe-stacks \
  --stack-name my-ubuntu-ec2 \
  --query "Stacks[0].Outputs[?OutputKey=='SSMParameterName'].OutputValue" \
  --output text)

# Download the private key
aws ssm get-parameter \
  --name "$SSM_PARAM" \
  --with-decryption \
  --query Parameter.Value \
  --output text > my-key.pem

chmod 400 my-key.pem
```

## Connect via SSH

```bash
# Get the public IP from stack outputs
PUBLIC_IP=$(aws cloudformation describe-stacks \
  --stack-name my-ubuntu-ec2 \
  --query "Stacks[0].Outputs[?OutputKey=='InstancePublicIP'].OutputValue" \
  --output text)

ssh -i my-key.pem ubuntu@$PUBLIC_IP
```

## Connect via RDP

1. Install an RDP client (e.g. Remmina on Linux, Microsoft Remote Desktop on macOS/Windows)
2. Connect to `<PublicIP>:3389`
3. Use username `ubuntu` (or configure a desktop environment and user in UserData if needed)

> **Note:** Ubuntu Server does not ship with a desktop environment. To use RDP you must install one (e.g. `xfce4` + `xrdp`) in the UserData section of the template.

## Stack Outputs

| Output | Description |
|--------|-------------|
| `InstancePublicIP` | Public IP address of the EC2 instance |
| `KeyPairName` | Name of the auto-generated key pair |
| `SSMParameterName` | SSM path to retrieve the private key |

## Clean Up

To delete all resources created by this stack:

```bash
aws cloudformation delete-stack \
  --stack-name my-ubuntu-ec2 \
  --region us-east-1
```

> **Note:** The EC2 key pair and SSM parameter are deleted automatically when the stack is deleted.
