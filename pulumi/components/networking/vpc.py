"""VPC and networking components for WikiJS infrastructure."""
import pulumi
import pulumi_aws as aws


class VPCComponent:
    """Creates VPC with subnets across 2 availability zones."""

    def __init__(self, name: str, cidr: str = "10.0.0.0/16"):
        """Initialize VPC component.

        Args:
            name: Base name for resources
            cidr: CIDR block for VPC
        """
        self.name = name
        self.cidr = cidr
        self.vpc = None
        self.public_subnets = []
        self.private_subnets = []
        self.igw = None
        self.nat_gateways = []
        self._create_vpc()
        self._create_subnets()
        self._create_internet_gateway()
        self._create_nat_gateways()
        self._create_route_tables()

    def _create_vpc(self):
        """Create VPC."""
        self.vpc = aws.ec2.Vpc(
            f"{self.name}-vpc",
            cidr_block=self.cidr,
            enable_dns_hostnames=True,
            enable_dns_support=True,
            tags={
                "Name": f"{self.name}-vpc",
            },
        )

    def _create_subnets(self):
        """Create subnets in 2 availability zones."""
        # Get availability zones
        azs = aws.get_availability_zones(state="available")
        # Use first 2 AZs
        selected_azs = azs.names[:2]

        # Create public and private subnets in each AZ
        for idx, az in enumerate(selected_azs):
            # Public subnet
            public_subnet = aws.ec2.Subnet(
                f"{self.name}-public-subnet-{idx + 1}",
                vpc_id=self.vpc.id,
                cidr_block=f"10.0.{idx + 1}.0/24",
                availability_zone=az,
                map_public_ip_on_launch=True,
                tags={
                    "Name": f"{self.name}-public-subnet-{idx + 1}",
                    "Type": "public",
                },
            )
            self.public_subnets.append(public_subnet)

            # Private subnet
            private_subnet = aws.ec2.Subnet(
                f"{self.name}-private-subnet-{idx + 1}",
                vpc_id=self.vpc.id,
                cidr_block=f"10.0.{idx + 20}.0/24",
                availability_zone=az,
                tags={
                    "Name": f"{self.name}-private-subnet-{idx + 1}",
                    "Type": "private",
                },
            )
            self.private_subnets.append(private_subnet)

    def _create_internet_gateway(self):
        """Create internet gateway."""
        self.igw = aws.ec2.InternetGateway(
            f"{self.name}-igw",
            vpc_id=self.vpc.id,
            tags={
                "Name": f"{self.name}-igw",
            },
        )

    def _create_nat_gateways(self):
        """Create NAT gateways in public subnets."""
        for idx, public_subnet in enumerate(self.public_subnets):
            # Elastic IP for NAT gateway
            eip = aws.ec2.Eip(
                f"{self.name}-nat-eip-{idx + 1}",
                domain="vpc",
                tags={
                    "Name": f"{self.name}-nat-eip-{idx + 1}",
                },
            )

            # NAT Gateway
            nat_gw = aws.ec2.NatGateway(
                f"{self.name}-nat-{idx + 1}",
                allocation_id=eip.id,
                subnet_id=public_subnet.id,
                tags={
                    "Name": f"{self.name}-nat-{idx + 1}",
                },
            )
            self.nat_gateways.append(nat_gw)

    def _create_route_tables(self):
        """Create route tables for public and private subnets."""
        # Public route table
        public_rt = aws.ec2.RouteTable(
            f"{self.name}-public-rt",
            vpc_id=self.vpc.id,
            tags={
                "Name": f"{self.name}-public-rt",
            },
        )

        # Route to internet gateway
        aws.ec2.Route(
            f"{self.name}-public-route",
            route_table_id=public_rt.id,
            destination_cidr_block="0.0.0.0/0",
            gateway_id=self.igw.id,
        )

        # Associate public subnets with public route table
        for idx, subnet in enumerate(self.public_subnets):
            aws.ec2.RouteTableAssociation(
                f"{self.name}-public-rta-{idx + 1}",
                subnet_id=subnet.id,
                route_table_id=public_rt.id,
            )

        # Private route tables (one per AZ for NAT gateway)
        for idx, (private_subnet, nat_gw) in enumerate(
            zip(self.private_subnets, self.nat_gateways)
        ):
            private_rt = aws.ec2.RouteTable(
                f"{self.name}-private-rt-{idx + 1}",
                vpc_id=self.vpc.id,
                tags={
                    "Name": f"{self.name}-private-rt-{idx + 1}",
                },
            )

            # Route to NAT gateway
            aws.ec2.Route(
                f"{self.name}-private-route-{idx + 1}",
                route_table_id=private_rt.id,
                destination_cidr_block="0.0.0.0/0",
                nat_gateway_id=nat_gw.id,
            )

            # Associate private subnet with route table
            aws.ec2.RouteTableAssociation(
                f"{self.name}-private-rta-{idx + 1}",
                subnet_id=private_subnet.id,
                route_table_id=private_rt.id,
            )

