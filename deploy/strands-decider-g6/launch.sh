#!/usr/bin/env bash
# 在当前 VPC 启动一台无公网 IP 的 GPU 实例（默认 g6.2xlarge），带有界容量重试。
# 幂等：每次尝试前先查同名 Name 标签的 pending/running 实例，避免超时后重复创建。
# 输出最后一行：LAUNCHED <instance-id> <private-ip> <az>
set -uo pipefail

REGION=${REGION:-us-west-2}
VPC_ID=${VPC_ID:-vpc-0edf3a4e323c23b22}
VPC_CIDR=${VPC_CIDR:-172.31.0.0/16}
NAME=${NAME:-strands-decider-g6}
INSTANCE_TYPE=${INSTANCE_TYPE:-g6.2xlarge}
KEY_NAME=${KEY_NAME:-strands-decider-g6}
SSH_PUBKEY=${SSH_PUBKEY:-$HOME/.ssh/id_ed25519.pub}
ADMIN_SG=${ADMIN_SG:-sg-0e3131bad226a169c}          # 管理机所在 SG，仅它可 SSH
# 优先无 IGW 路由的私有子网，其余为默认子网（均不分配公网 IP）
SUBNETS=${SUBNETS:-"subnet-032b21959bdb16c4f subnet-0049c68761e287ca0 subnet-09b36d4db52839142 subnet-074b6fef6b8100535"}
API_PORT=${API_PORT:-8000}
VOLUME_GB=${VOLUME_GB:-150}
ROUNDS=${ROUNDS:-15}
SLEEP_S=${SLEEP_S:-90}
AMI_NAME=${AMI_NAME:-"Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.12 (Ubuntu 24.04)*"}
export AWS_REGION=$REGION

aws ec2 describe-key-pairs --key-names "$KEY_NAME" >/dev/null 2>&1 || \
  aws ec2 import-key-pair --key-name "$KEY_NAME" --public-key-material "fileb://$SSH_PUBKEY" >/dev/null

SG_ID=${SG_ID:-$(aws ec2 describe-security-groups --filters Name=vpc-id,Values="$VPC_ID" \
  Name=group-name,Values="$NAME" --query 'SecurityGroups[0].GroupId' --output text)}
if [ -z "$SG_ID" ] || [ "$SG_ID" = "None" ]; then
  SG_ID=$(aws ec2 create-security-group --vpc-id "$VPC_ID" --group-name "$NAME" \
    --description "strands-decider chat-completions API, VPC-internal only" --query GroupId --output text)
  aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --ip-permissions \
    "IpProtocol=tcp,FromPort=$API_PORT,ToPort=$API_PORT,IpRanges=[{CidrIp=$VPC_CIDR,Description=\"API from VPC\"}]" \
    "IpProtocol=tcp,FromPort=22,ToPort=22,UserIdGroupPairs=[{GroupId=$ADMIN_SG,Description=\"ssh from admin host\"}]" >/dev/null
  aws ec2 create-tags --resources "$SG_ID" --tags Key=Name,Value="$NAME"
fi
echo "security group: $SG_ID"

AMI_ID=${AMI_ID:-$(aws ec2 describe-images --owners amazon --filters "Name=name,Values=$AMI_NAME" \
  Name=architecture,Values=x86_64 --query 'reverse(sort_by(Images,&CreationDate))[0].ImageId' --output text)}
echo "ami: $AMI_ID"

# 只保留所在 AZ 提供该机型的子网（例如 g5 在 us-west-2d 不提供）
OFFERED=$(aws ec2 describe-instance-type-offerings --location-type availability-zone \
  --filters Name=instance-type,Values="$INSTANCE_TYPE" --query 'InstanceTypeOfferings[].Location' --output text)
KEEP=""
for SUB in $SUBNETS; do
  AZ=$(aws ec2 describe-subnets --subnet-ids "$SUB" --query 'Subnets[0].AvailabilityZone' --output text)
  if echo " $OFFERED " | tr '\t' ' ' | grep -q " $AZ "; then KEEP="$KEEP $SUB"; else echo "skip $SUB ($AZ does not offer $INSTANCE_TYPE)"; fi
done
SUBNETS=$KEEP
[ -n "$SUBNETS" ] || { echo "FATAL: no subnet in an AZ offering $INSTANCE_TYPE"; exit 2; }

existing() {
  aws ec2 describe-instances --filters Name=tag:Name,Values="$NAME" Name=instance-state-name,Values=pending,running \
    --query 'Reservations[].Instances[].[InstanceId,PrivateIpAddress,Placement.AvailabilityZone]' --output text
}

for round in $(seq 1 "$ROUNDS"); do
  for SUB in $SUBNETS; do
    E=$(existing); if [ -n "$E" ]; then echo "LAUNCHED $E"; exit 0; fi
    OUT=$(aws ec2 run-instances --image-id "$AMI_ID" --instance-type "$INSTANCE_TYPE" --key-name "$KEY_NAME" \
      --network-interfaces "DeviceIndex=0,SubnetId=$SUB,Groups=$SG_ID,AssociatePublicIpAddress=false" \
      --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=$VOLUME_GB,VolumeType=gp3,DeleteOnTermination=true}" \
      --metadata-options HttpTokens=required,HttpEndpoint=enabled \
      --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" \
        "ResourceType=volume,Tags=[{Key=Name,Value=$NAME}]" \
      --query 'Instances[0].[InstanceId,PrivateIpAddress,Placement.AvailabilityZone]' --output text 2>&1)
    if echo "$OUT" | grep -q '^i-'; then echo "LAUNCHED $OUT"; exit 0; fi
    if ! echo "$OUT" | grep -q InsufficientInstanceCapacity; then echo "FATAL round=$round $SUB: $OUT"; exit 2; fi
    echo "$(date -u +%T) round=$round $SUB: no capacity"
  done
  [ "$round" -lt "$ROUNDS" ] && sleep "$SLEEP_S"
done
E=$(existing); if [ -n "$E" ]; then echo "LAUNCHED $E"; exit 0; fi
echo "GAVE UP after $ROUNDS rounds"; exit 1
