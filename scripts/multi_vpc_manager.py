import argparse
import sys
import time
import boto3
from botocore.exceptions import ClientError


def get_vpc_resources(region, vpc_id):
    """Gathers all dependent resources and parent services attached to the VPC."""
    ec2_client = boto3.client("ec2", region_name=region)
    elbv2_client = boto3.client("elbv2", region_name=region)
    elb_client = boto3.client("elb", region_name=region)

    resources = {
        "subnets": [],
        "route_tables": [],
        "security_groups": [],
        "network_interfaces": [],
        "internet_gateways": [],
        "egress_only_igws": [],
        "nat_gateways": [],
        "vpc_endpoints": [],
        "vpc_endpoint_services": [],
        "vpc_peering_connections": [],
        "vpn_gateways": [],
        "network_acls": [],
        "flow_logs": [],
        "carrier_gateways": [],
        "instances": [],
        "eips": [],
        "load_balancers_v2": [],
        "load_balancers_v1": [],
        "tgw_attachments": [],
    }

    # 1. Subnets
    try:
        paginator = ec2_client.get_paginator("describe_subnets")
        for page in paginator.paginate(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]):
            resources["subnets"].extend([s["SubnetId"] for s in page["Subnets"]])
    except ClientError:
        pass

    # 2. Custom Route Tables (exclude main)
    try:
        paginator = ec2_client.get_paginator("describe_route_tables")
        for page in paginator.paginate(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]):
            for rt in page["RouteTables"]:
                is_main = any(assoc.get("Main", False) for assoc in rt.get("Associations", []))
                if not is_main:
                    resources["route_tables"].append(rt)
    except ClientError:
        pass

    # 3. Custom Security Groups (exclude default)
    try:
        paginator = ec2_client.get_paginator("describe_security_groups")
        for page in paginator.paginate(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]):
            resources["security_groups"].extend(
                [sg["GroupId"] for sg in page["SecurityGroups"] if sg["GroupName"] != "default"]
            )
    except ClientError:
        pass

    # 4. Network Interfaces
    try:
        paginator = ec2_client.get_paginator("describe_network_interfaces")
        for page in paginator.paginate(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]):
            for eni in page["NetworkInterfaces"]:
                resources["network_interfaces"].append({
                    "id": eni["NetworkInterfaceId"],
                    "description": eni.get("Description", "No Description"),
                    "status": eni.get("Status"),
                    "requester": eni.get("RequesterId", "User"),
                    "attachment": eni.get("Attachment"),
                    "is_managed": eni.get("InterfaceType") in ["nat_gateway", "lambda", "vpc_endpoint"]
                    or eni.get("RequesterManaged", False),
                })
    except ClientError:
        pass

    # 5. Internet Gateways
    try:
        paginator = ec2_client.get_paginator("describe_internet_gateways")
        for page in paginator.paginate(Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]):
            resources["internet_gateways"].extend([igw["InternetGatewayId"] for igw in page["InternetGateways"]])
    except ClientError:
        pass

    # 6. Egress-Only Internet Gateways
    try:
        eoigws = ec2_client.describe_egress_only_internet_gateways().get("EgressOnlyInternetGatewaySet", [])
        for eoigw in eoigws:
            if any(att.get("VpcId") == vpc_id for att in eoigw.get("Attachments", [])):
                resources["egress_only_igws"].append(eoigw["EgressOnlyInternetGatewayId"])
    except ClientError:
        pass

    # 7. NAT Gateways
    try:
        paginator = ec2_client.get_paginator("describe_nat_gateways")
        for page in paginator.paginate(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]):
            resources["nat_gateways"].extend(
                [nat["NatGatewayId"] for nat in page["NatGateways"] if nat["State"] != "deleted"]
            )
    except ClientError:
        pass

    # 8. VPC Endpoints
    try:
        paginator = ec2_client.get_paginator("describe_vpc_endpoints")
        for page in paginator.paginate(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]):
            resources["vpc_endpoints"].extend(
                [vpce["VpcEndpointId"] for vpce in page["VpcEndpoints"] if vpce["State"] != "deleted"]
            )
    except ClientError:
        pass

    # 9. VPC Endpoint Services
    try:
        services = ec2_client.describe_vpc_endpoint_service_configurations().get("ServiceConfigurations", [])
        for svc in services:
            if vpc_id in svc.get("VpcEndpointIds", []):
                resources["vpc_endpoint_services"].append(svc["ServiceId"])
    except ClientError:
        pass

    # 10. VPC Peering Connections
    try:
        p1 = ec2_client.describe_vpc_peering_connections(
            Filters=[{"Name": "requester-vpc-info.vpc-id", "Values": [vpc_id]}]
        ).get("VpcPeeringConnections", [])
        p2 = ec2_client.describe_vpc_peering_connections(
            Filters=[{"Name": "accepter-vpc-info.vpc-id", "Values": [vpc_id]}]
        ).get("VpcPeeringConnections", [])
        for pcx in p1 + p2:
            if pcx.get("Status", {}).get("Code") not in ["deleted", "deleting", "rejected"]:
                if pcx["VpcPeeringConnectionId"] not in resources["vpc_peering_connections"]:
                    resources["vpc_peering_connections"].append(pcx["VpcPeeringConnectionId"])
    except ClientError:
        pass

    # 11. VPN Gateways
    try:
        vgws = ec2_client.describe_vpn_gateways(
            Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
        ).get("VpnGateways", [])
        resources["vpn_gateways"].extend([vgw["VpnGatewayId"] for vgw in vgws if vgw["State"] != "deleted"])
    except ClientError:
        pass

    # 12. Custom Network ACLs
    try:
        nacls = ec2_client.describe_network_acls(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        ).get("NetworkAcls", [])
        resources["network_acls"].extend([nacl["NetworkAclId"] for nacl in nacls if not nacl.get("IsDefault")])
    except ClientError:
        pass

    # 13. VPC Flow Logs
    try:
        fls = ec2_client.describe_flow_logs(
            Filters=[{"Name": "resource-id", "Values": [vpc_id]}]
        ).get("FlowLogs", [])
        resources["flow_logs"].extend([fl["FlowLogId"] for fl in fls])
    except ClientError:
        pass

    # 14. Carrier Gateways
    try:
        cgws = ec2_client.describe_carrier_gateways(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        ).get("CarrierGateways", [])
        resources["carrier_gateways"].extend([cgw["CarrierGatewayId"] for cgw in cgws if cgw["State"] != "deleted"])
    except ClientError:
        pass

    # 15. EC2 Instances
    try:
        paginator = ec2_client.get_paginator("describe_instances")
        for page in paginator.paginate(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]):
            for reservation in page["Reservations"]:
                for instance in reservation["Instances"]:
                    if instance["State"]["Name"] != "terminated":
                        resources["instances"].append(instance["InstanceId"])
    except ClientError:
        pass

    # 16. Elastic IPs
    try:
        eni_ids = [eni["id"] for eni in resources["network_interfaces"]]
        eips = ec2_client.describe_addresses()["Addresses"]
        for eip in eips:
            if eip.get("Domain") == "vpc" and eip.get("NetworkInterfaceId") in eni_ids:
                resources["eips"].append(eip)
    except ClientError:
        pass

    # 17. Load Balancers V2 (ALB/NLB)
    try:
        paginator = elbv2_client.get_paginator("describe_load_balancers")
        for page in paginator.paginate():
            for lb in page["LoadBalancers"]:
                if lb.get("VpcId") == vpc_id:
                    resources["load_balancers_v2"].append(lb["LoadBalancerArn"])
    except ClientError:
        pass

    # 18. Classic Load Balancers V1
    try:
        paginator = elb_client.get_paginator("describe_load_balancers")
        for page in paginator.paginate():
            for lb in page["LoadBalancerDescriptions"]:
                if lb.get("VpcId") == vpc_id:
                    resources["load_balancers_v1"].append(lb["LoadBalancerName"])
    except ClientError:
        pass

    # 19. Transit Gateway Attachments
    try:
        tgw_atts = ec2_client.describe_transit_gateway_vpc_attachments(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        ).get("TransitGatewayVpcAttachments", [])
        resources["tgw_attachments"] = [
            att["TransitGatewayAttachmentId"] for att in tgw_atts if att.get("State") != "deleted"
        ]
    except ClientError:
        pass

    return resources


def display_resources(vpc_id, resources):
    """Prints details of all detected resources in the VPC."""
    print(f"\n--- AWS Resources inside VPC: {vpc_id} ---")
    total_count = 0

    for res_type, res_list in resources.items():
        count = len(res_list)
        total_count += count
        title_name = res_type.replace("_", " ").title()

        if count > 0:
            print(f"  {title_name} ({count}):")
            for item in res_list:
                if res_type == "network_interfaces":
                    print(
                        f"    - {item['id']} | Status: {item['status']} | Desc: {item['description']} (Owner: {item['requester']})"
                    )
                elif res_type == "eips":
                    print(f"    - AllocationId: {item.get('AllocationId')} (IP: {item.get('PublicIp')})")
                elif res_type == "route_tables":
                    print(f"    - {item['RouteTableId']}")
                else:
                    print(f"    - {item}")
        else:
            print(f"  {title_name} (0)")

    print(f"  Total dependent resources found: {total_count}\n")


def retry_on_dependency(func, *args, retries=15, delay=10, **kwargs):
    """Handles eventual consistency dependency retries during resource teardown."""
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except ClientError as e:
            err_msg = str(e)
            if any(term in err_msg for term in ["DependencyViolation", "ResourceInUse", "InUse"]) and attempt < retries - 1:
                print(f"    [Retry {attempt + 1}/{retries}] Waiting for dependencies to disassociate...")
                time.sleep(delay)
            else:
                raise e


def wait_for_vpc_endpoints_deletion(ec2_client, vpc_id, retries=20, delay=10):
    """Polls VPC endpoints until AWS completely cleans them up."""
    for attempt in range(retries):
        endpoints = ec2_client.describe_vpc_endpoints(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        ).get("VpcEndpoints", [])
        active_endpoints = [ep["VpcEndpointId"] for ep in endpoints if ep.get("State") != "deleted"]
        
        if not active_endpoints:
            print("All VPC Endpoints successfully removed by AWS.")
            return
        
        print(f"    [Waiting for VPC Endpoints] Active: {len(active_endpoints)} remaining... ({attempt + 1}/{retries})")
        time.sleep(delay)


def wait_and_delete_subnet(ec2_client, subnet_id, retries=18, delay=10):
    """Inspects subnet ENIs dynamically and retries deletion until clean."""
    for attempt in range(retries):
        # Dynamically check for remaining ENIs attached to this subnet
        enis = ec2_client.describe_network_interfaces(
            Filters=[{"Name": "subnet-id", "Values": [subnet_id]}]
        ).get("NetworkInterfaces", [])

        if enis:
            eni_summary = [f"{e['NetworkInterfaceId']} ({e.get('Description', 'No Desc')})" for e in enis]
            print(f"    [Subnet {subnet_id}] Waiting on {len(enis)} active ENI(s): {', '.join(eni_summary)}")
            time.sleep(delay)
            continue

        try:
            ec2_client.delete_subnet(SubnetId=subnet_id)
            print(f"Successfully deleted Subnet: {subnet_id}")
            return
        except ClientError as e:
            if "DependencyViolation" in str(e) and attempt < retries - 1:
                print(f"    [Subnet {subnet_id}] Dependency lock detected. Retrying in {delay}s...")
                time.sleep(delay)
            else:
                raise e


def strip_all_security_group_rules(ec2_client, vpc_id):
    """Revokes all ingress and egress rules across all security groups to remove cross-SG locks."""
    try:
        paginator = ec2_client.get_paginator("describe_security_groups")
        for page in paginator.paginate(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]):
            for sg in page["SecurityGroups"]:
                sg_id = sg["GroupId"]
                if sg.get("IpPermissions"):
                    try:
                        ec2_client.revoke_security_group_ingress(GroupId=sg_id, IpPermissions=sg["IpPermissions"])
                    except ClientError:
                        pass
                if sg.get("IpPermissionsEgress"):
                    try:
                        ec2_client.revoke_security_group_egress(GroupId=sg_id, IpPermissions=sg["IpPermissionsEgress"])
                    except ClientError:
                        pass
    except ClientError as e:
        print(f"Warning revoking security group rules: {e}")


def delete_vpc_resources(region, vpc_id, resources):
    """Cleans up all dependent resources in chronological order and deletes the VPC."""
    ec2_client = boto3.client("ec2", region_name=region)
    elbv2_client = boto3.client("elbv2", region_name=region)
    elb_client = boto3.client("elb", region_name=region)

    print(f"\n[!] Starting deletion process for VPC: {vpc_id}...")

    try:
        # 1. Flow Logs
        for fl_id in resources["flow_logs"]:
            print(f"Deleting Flow Log: {fl_id}")
            try:
                ec2_client.delete_flow_logs(FlowLogIds=[fl_id])
            except ClientError as e:
                print(f"Skipping Flow Log {fl_id}: {e}")

        # 2. Terminate EC2 Instances
        if resources["instances"]:
            print(f"Terminating EC2 instances: {resources['instances']}")
            ec2_client.terminate_instances(InstanceIds=resources["instances"])
            waiter = ec2_client.get_waiter("instance_terminated")
            waiter.wait(InstanceIds=resources["instances"])

        # 3. Load Balancers
        for lb_arn in resources["load_balancers_v2"]:
            print(f"Deleting Load Balancer (ELBv2): {lb_arn}")
            try:
                elbv2_client.delete_load_balancer(LoadBalancerArn=lb_arn)
            except ClientError as e:
                print(f"Skipping Load Balancer {lb_arn}: {e}")

        for lb_name in resources["load_balancers_v1"]:
            print(f"Deleting Classic Load Balancer: {lb_name}")
            try:
                elb_client.delete_load_balancer(LoadBalancerName=lb_name)
            except ClientError as e:
                print(f"Skipping Classic Load Balancer {lb_name}: {e}")

        if resources["load_balancers_v2"] or resources["load_balancers_v1"]:
            time.sleep(15)

        # 4. Transit Gateway Attachments
        for tgw_att_id in resources["tgw_attachments"]:
            print(f"Deleting Transit Gateway Attachment: {tgw_att_id}")
            try:
                ec2_client.delete_transit_gateway_vpc_attachment(TransitGatewayAttachmentId=tgw_att_id)
            except ClientError as e:
                print(f"Skipping TGW Attachment {tgw_att_id}: {e}")

        # 5. VPC Endpoints & Endpoint Services (With Polling Waiter)
        if resources["vpc_endpoints"]:
            print(f"Deleting VPC Endpoints: {resources['vpc_endpoints']}")
            try:
                ec2_client.delete_vpc_endpoints(VpcEndpointIds=resources["vpc_endpoints"])
                wait_for_vpc_endpoints_deletion(ec2_client, vpc_id)
            except ClientError as e:
                print(f"Error deleting VPC Endpoints: {e}")

        for svc_id in resources["vpc_endpoint_services"]:
            print(f"Deleting VPC Endpoint Service: {svc_id}")
            try:
                ec2_client.delete_vpc_endpoint_service_configurations(ServiceIds=[svc_id])
            except ClientError as e:
                print(f"Skipping Endpoint Service {svc_id}: {e}")

        # 6. VPC Peering Connections
        for pcx_id in resources["vpc_peering_connections"]:
            print(f"Deleting VPC Peering Connection: {pcx_id}")
            try:
                ec2_client.delete_vpc_peering_connection(VpcPeeringConnectionId=pcx_id)
            except ClientError as e:
                print(f"Skipping Peering Connection {pcx_id}: {e}")

        # 7. VPN Gateways
        for vgw_id in resources["vpn_gateways"]:
            print(f"Detaching and Deleting VPN Gateway: {vgw_id}")
            try:
                ec2_client.detach_vpn_gateway(VpnGatewayId=vgw_id, VpcId=vpc_id)
            except ClientError:
                pass
            try:
                ec2_client.delete_vpn_gateway(VpnGatewayId=vgw_id)
            except ClientError as e:
                print(f"Skipping VPN Gateway {vgw_id}: {e}")

        # 8. NAT Gateways
        if resources["nat_gateways"]:
            for nat_id in resources["nat_gateways"]:
                print(f"Deleting NAT Gateway: {nat_id}")
                try:
                    ec2_client.delete_nat_gateway(NatGatewayId=nat_id)
                except ClientError as e:
                    print(f"Skipping NAT Gateway {nat_id}: {e}")

            print("Waiting for NAT Gateways to complete deletion...")
            try:
                waiter = ec2_client.get_waiter("nat_gateway_deleted")
                waiter.wait(NatGatewayIds=resources["nat_gateways"])
            except ClientError:
                pass

        # 9. Carrier & Egress-Only IGWs
        for eoigw_id in resources["egress_only_igws"]:
            print(f"Deleting Egress-Only IGW: {eoigw_id}")
            try:
                ec2_client.delete_egress_only_internet_gateway(EgressOnlyInternetGatewayId=eoigw_id)
            except ClientError as e:
                print(f"Skipping Egress-Only IGW {eoigw_id}: {e}")

        for cgw_id in resources["carrier_gateways"]:
            print(f"Deleting Carrier Gateway: {cgw_id}")
            try:
                ec2_client.delete_carrier_gateway(CarrierGatewayId=cgw_id)
            except ClientError as e:
                print(f"Skipping Carrier Gateway {cgw_id}: {e}")

        # 10. Live Dynamic Sweep: Detach and Delete ENIs
        print("Performing live dynamic sweep for remaining ENIs...")
        live_enis = ec2_client.describe_network_interfaces(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        ).get("NetworkInterfaces", [])

        for eni in live_enis:
            eni_id = eni["NetworkInterfaceId"]
            attachment = eni.get("Attachment")
            is_managed = eni.get("InterfaceType") in ["nat_gateway", "lambda", "vpc_endpoint"] or eni.get("RequesterManaged", False)

            if attachment and not is_managed:
                print(f"Detaching ENI: {eni_id}")
                try:
                    ec2_client.detach_network_interface(AttachmentId=attachment["AttachmentId"], Force=True)
                except ClientError as e:
                    print(f"Warning detaching ENI {eni_id}: {e}")

        # 11. Release Elastic IPs
        for eip in resources["eips"]:
            assoc_id = eip.get("AssociationId")
            alloc_id = eip.get("AllocationId")

            if assoc_id:
                try:
                    ec2_client.disassociate_address(AssociationId=assoc_id)
                except ClientError:
                    pass

            if alloc_id:
                try:
                    ec2_client.release_address(AllocationId=alloc_id)
                except ClientError as e:
                    print(f"Skipping release for EIP ({alloc_id}): {e}")

        # Delete unmanaged ENIs directly
        for eni in live_enis:
            eni_id = eni["NetworkInterfaceId"]
            is_managed = eni.get("InterfaceType") in ["nat_gateway", "lambda", "vpc_endpoint"] or eni.get("RequesterManaged", False)
            if not is_managed:
                print(f"Deleting ENI: {eni_id}")
                try:
                    retry_on_dependency(ec2_client.delete_network_interface, NetworkInterfaceId=eni_id)
                except ClientError as e:
                    print(f"Skipping ENI {eni_id}: {e}")

        # 12. Detach & Delete Internet Gateways
        for igw_id in resources["internet_gateways"]:
            print(f"Detaching IGW: {igw_id}")
            try:
                retry_on_dependency(ec2_client.detach_internet_gateway, InternetGatewayId=igw_id, VpcId=vpc_id)
            except ClientError:
                pass
            print(f"Deleting IGW: {igw_id}")
            try:
                ec2_client.delete_internet_gateway(InternetGatewayId=igw_id)
            except ClientError as e:
                print(f"Skipping IGW {igw_id}: {e}")

        # 13. Revoke Security Group Rules across all SGs
        print("Revoking security group rules across VPC...")
        strip_all_security_group_rules(ec2_client, vpc_id)

        # 14. Delete Custom Network ACLs
        for nacl_id in resources["network_acls"]:
            print(f"Deleting Custom Network ACL: {nacl_id}")
            try:
                ec2_client.delete_network_acl(NetworkAclId=nacl_id)
            except ClientError as e:
                print(f"Skipping Network ACL {nacl_id}: {e}")

        # 15. Disassociate & Delete Route Tables
        for rt in resources["route_tables"]:
            rt_id = rt["RouteTableId"]
            for assoc in rt.get("Associations", []):
                if not assoc.get("Main", False) and assoc.get("RouteTableAssociationId"):
                    try:
                        ec2_client.disassociate_route_table(AssociationId=assoc["RouteTableAssociationId"])
                    except ClientError:
                        pass
            print(f"Deleting Route Table: {rt_id}")
            try:
                retry_on_dependency(ec2_client.delete_route_table, RouteTableId=rt_id)
            except ClientError as e:
                print(f"Skipping Route Table {rt_id}: {e}")

        # 16. Delete Subnets (with Active ENI Polling)
        for subnet_id in resources["subnets"]:
            print(f"Attempting Subnet deletion: {subnet_id}")
            wait_and_delete_subnet(ec2_client, subnet_id)

        # 17. Delete Custom Security Groups
        for sg_id in resources["security_groups"]:
            print(f"Deleting Security Group: {sg_id}")
            retry_on_dependency(ec2_client.delete_security_group, GroupId=sg_id)

        # 18. Revert DHCP Options Set
        try:
            ec2_client.associate_dhcp_options(DhcpOptionsId="default", VpcId=vpc_id)
        except ClientError:
            pass

        # 19. Final VPC Deletion
        print(f"Deleting VPC: {vpc_id}")
        retry_on_dependency(ec2_client.delete_vpc, VpcId=vpc_id)
        print(f"[+] Successfully deleted VPC {vpc_id}.")

    except ClientError as e:
        print(f"[-] Error deleting VPC {vpc_id}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Audit or Delete VPCs and all dependent resources.")
    parser.add_argument("--region", required=True, help="AWS Region (e.g., us-east-2)")
    parser.add_argument("--vpc-id", help="Optional: Target a specific VPC ID.")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--read", action="store_true", help="List resources inside the VPC(s)")
    group.add_argument("--delete", action="store_true", help="Delete resource(s) and VPC(s)")

    args = parser.parse_args()
    ec2_client = boto3.client("ec2", region_name=args.region)

    if args.vpc_id:
        target_vpcs = [args.vpc_id]
    else:
        try:
            paginator = ec2_client.get_paginator("describe_vpcs")
            target_vpcs = [
                vpc["VpcId"] for page in paginator.paginate() for vpc in page["Vpcs"]
            ]
        except ClientError as e:
            print(f"Error listing VPCs: {e}")
            sys.exit(1)

    if not target_vpcs:
        print(f"No VPCs found in region {args.region}.")
        sys.exit(0)

    vpc_data = {vpc_id: get_vpc_resources(args.region, vpc_id) for vpc_id in target_vpcs}

    if args.read:
        for vpc_id, resources in vpc_data.items():
            display_resources(vpc_id, resources)

    if args.delete:
        print("\n--- Summary of Targets ---")
        for vpc_id, resources in vpc_data.items():
            display_resources(vpc_id, resources)

        confirmation = input("[!] Confirm PERMANENT deletion (type 'yes'): ").strip().lower()
        if confirmation == "yes":
            for vpc_id, resources in vpc_data.items():
                delete_vpc_resources(args.region, vpc_id, resources)
        else:
            print("Deletion cancelled.")


if __name__ == "__main__":
    main()