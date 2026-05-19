#!/usr/bin/env bash
set -euo pipefail

sudo dnf install -y amazon-cloudwatch-agent || sudo yum install -y amazon-cloudwatch-agent

sudo mkdir -p /opt/aws/amazon-cloudwatch-agent/bin
sudo cp cloudwatch/agent-config.json /opt/aws/amazon-cloudwatch-agent/bin/config.json

sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config \
  -m ec2 \
  -c file:/opt/aws/amazon-cloudwatch-agent/bin/config.json \
  -s

echo "CloudWatch Agent instalado e iniciado."
