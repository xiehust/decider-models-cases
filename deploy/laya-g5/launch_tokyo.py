"""Create or reuse the task's single Tokyo G5; never opens inference to the Internet."""
import json
import argparse
import time
import urllib.request
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent
REGION = "ap-northeast-1"
NAME = "decider-cases-laya-tokyo"
ec2 = boto3.client("ec2", region_name=REGION)


def main(spot=False, attempt="initial", instance_type="g5.2xlarge", spot_max_price="1.459"):
    existing = ec2.describe_instances(Filters=[
        {"Name": "tag:Name", "Values": [NAME]},
        {"Name": "instance-state-name", "Values": ["pending", "running", "stopped"]},
    ])
    instances = [i for r in existing["Reservations"] for i in r["Instances"]]
    if instances:
        assert len(instances) == 1, "Multiple tagged instances; inspect before continuing"
        assert instances[0]["InstanceType"] == instance_type, "Existing instance type differs"
        print(json.dumps({"id": instances[0]["InstanceId"], "state": instances[0]["State"]["Name"]}))
        return
    source = urllib.request.urlopen("https://checkip.amazonaws.com", timeout=10).read().decode().strip()
    import ipaddress
    source = str(ipaddress.IPv4Address(source)) + "/32"
    vpc = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"][0]["VpcId"]
    groups = ec2.describe_security_groups(Filters=[
        {"Name": "vpc-id", "Values": [vpc]}, {"Name": "group-name", "Values": [NAME]}])["SecurityGroups"]
    if groups:
        sg = groups[0]["GroupId"]
    else:
        sg = ec2.create_security_group(GroupName=NAME, VpcId=vpc,
                                      Description="Laya benchmark: SSH from management host only")["GroupId"]
        ec2.authorize_security_group_ingress(GroupId=sg, IpPermissions=[
            {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
             "IpRanges": [{"CidrIp": source, "Description": "Benchmark management host"}]}])
        ec2.create_tags(Resources=[sg], Tags=[{"Key": "Project", "Value": "decider-cases"}])
    keys = ec2.describe_key_pairs(Filters=[{"Name": "key-name", "Values": [NAME]}])["KeyPairs"]
    if not keys:
        ec2.import_key_pair(KeyName=NAME, PublicKeyMaterial=(Path.home() / ".ssh/id_ed25519.pub").read_bytes())
    images = ec2.describe_images(Owners=["amazon"], Filters=[
        {"Name": "name", "Values": ["Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.12 (Ubuntu 24.04)*"]},
        {"Name": "architecture", "Values": ["x86_64"]}, {"Name": "state", "Values": ["available"]}])["Images"]
    ami = max(images, key=lambda i: i["CreationDate"])
    subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc]}])["Subnets"]
    offered = {o["Location"] for o in ec2.describe_instance_type_offerings(LocationType="availability-zone",
               Filters=[{"Name": "instance-type", "Values": [instance_type]}])["InstanceTypeOfferings"]}
    for subnet in sorted(subnets, key=lambda s: s["AvailabilityZone"]):
        if subnet["AvailabilityZone"] not in offered:
            continue
        request = dict(
            ImageId=ami["ImageId"], InstanceType=instance_type, MinCount=1, MaxCount=1, KeyName=NAME,
            ClientToken="laya-1015-" + instance_type + "-" + ("spot-" if spot else "") + attempt + "-" + subnet["AvailabilityZone"],
            InstanceInitiatedShutdownBehavior="stop",
            MetadataOptions={"HttpTokens": "required", "HttpEndpoint": "enabled"},
            NetworkInterfaces=[{"DeviceIndex": 0, "SubnetId": subnet["SubnetId"], "Groups": [sg],
                                "AssociatePublicIpAddress": True}],
            BlockDeviceMappings=[{"DeviceName": ami["RootDeviceName"],
                                  "Ebs": {"VolumeSize": 100, "VolumeType": "gp3", "Encrypted": True,
                                          "DeleteOnTermination": True}}],
            TagSpecifications=[{"ResourceType": kind, "Tags": [
                {"Key": "Name", "Value": NAME}, {"Key": "Project", "Value": "decider-cases"},
                {"Key": "Purpose", "Value": "laya-benchmark-20261015"}]} for kind in ["instance", "volume"]],
        )
        if spot:
            request["InstanceInitiatedShutdownBehavior"] = "terminate"
            request["InstanceMarketOptions"] = {
                "MarketType": "spot",
                "SpotOptions": {"MaxPrice": spot_max_price, "SpotInstanceType": "one-time",
                                "InstanceInterruptionBehavior": "terminate"},
            }
        try:
            res = ec2.run_instances(**request)
        except ClientError as exc:
            with (ROOT / "launch-attempts.jsonl").open("a") as log:
                log.write(json.dumps({
                    "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "az": subnet["AvailabilityZone"], "market": "spot" if spot else "on-demand",
                    "instance_type": instance_type,
                    "client_token": request["ClientToken"], "error": exc.response["Error"],
                    "request_id": exc.response["ResponseMetadata"]["RequestId"],
                }) + "\n")
            if exc.response["Error"]["Code"] != "InsufficientInstanceCapacity":
                raise
            print(subnet["AvailabilityZone"], "InsufficientInstanceCapacity", flush=True)
            continue
        receipt = {"region": REGION, "request": request, "instance_id": res["Instances"][0]["InstanceId"],
                   "ami_name": ami["Name"], "ssh_source": source,
                   "launched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        with (ROOT / "tokyo-instance.json").open("x") as f:
            json.dump(receipt, f, indent=2)
            f.write("\n")
        print(json.dumps(receipt, indent=2))
        return
    raise SystemExit(f"No {instance_type} capacity in the available default-VPC AZs")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spot", action="store_true")
    parser.add_argument("--attempt", default="initial", help="Change only after confirmed capacity failures")
    parser.add_argument("--instance-type", choices=["g5.xlarge", "g5.2xlarge"], default="g5.2xlarge")
    parser.add_argument("--spot-max-price", default="1.459")
    args = parser.parse_args()
    main(args.spot, args.attempt, args.instance_type, args.spot_max_price)
