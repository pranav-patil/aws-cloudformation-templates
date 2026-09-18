#!/bin/bash

set -e

STACK_NAME="zyron-firewall-demo"
BUCKET_NAME="${STACK_NAME}-scripts-bucket"

usage() {
    echo "Usage: $0 {deploy|destroy}"
    exit 1
}

deploy() {
    aws s3 mb s3://$BUCKET_NAME
    aws s3 cp ./scripts s3://$BUCKET_NAME/scripts --recursive
    aws s3 ls "s3://$BUCKET_NAME/scripts/"

    aws cloudformation deploy --stack-name ${STACK_NAME} \
      --template-file single_vpc_firewall_inspect.yaml \
      --parameter-overrides Environment=dev ScriptsBucket=$BUCKET_NAME \
      --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND

    aws cloudformation wait stack-create-complete --stack-name ${STACK_NAME}

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

    PUBLIC_EC2_IP=$(aws cloudformation describe-stacks \
        --stack-name ${STACK_NAME} \
        --query "Stacks[0].Outputs[?OutputKey=='EC2InstanceBPublicIP'].OutputValue" \
        --output text)

    echo "PUBLIC_EC2_IP: ${PUBLIC_EC2_IP}"

    PRIVATE_EC2_IP=$(aws cloudformation describe-stacks \
        --stack-name ${STACK_NAME} \
        --query "Stacks[0].Outputs[?OutputKey=='EC2InstanceAPrivateIP'].OutputValue" \
        --output text)

    echo "PRIVATE_EC2_IP: ${PRIVATE_EC2_IP}"
    echo "Deployment complete!"
    
    echo "Waiting for private EC2 instance initialization..."
    sleep 60

    ssh -i generated-key.pem ubuntu@${PUBLIC_EC2_IP} \
        -o "StrictHostKeyChecking=no" -o "UserKnownHostsFile=/dev/null" \
        -t "python3 scripts/generate_traffic.py ${PRIVATE_EC2_IP} --verbose; bash"
}

destroy() {
    echo "Deleting CloudFormation stack: ${STACK_NAME}..."

    rm -f generated-key.pem
    aws cloudformation delete-stack --stack-name ${STACK_NAME}
    aws cloudformation wait stack-delete-complete --stack-name ${STACK_NAME}
    aws s3 rb s3://$BUCKET_NAME --force
    echo "Destroy complete!"
}

case "$1" in
    deploy)
        deploy
        ;;
    destroy)
        destroy
        ;;
    *)
        usage
        ;;
esac
