"""RDS PostgreSQL component for WikiJS external database."""
import pulumi
import pulumi_aws as aws


class RDSPostgresComponent:
    """Creates an RDS PostgreSQL instance in private subnets."""

    def __init__(
        self,
        name: str,
        db_name: str,
        username: pulumi.Input[str],
        password: pulumi.Input[str],
        subnet_ids: list[str],
        vpc_id: str,
        instance_class: str = "db.t3.micro",
        allocated_storage: int = 20,
        multi_az: bool = False,
    ):
        self.name = name
        self.db_name = db_name

        self.sg = aws.ec2.SecurityGroup(
            f"{name}-rds-sg",
            vpc_id=vpc_id,
            description="RDS PostgreSQL access from VPC",
            ingress=[
                aws.ec2.SecurityGroupIngressArgs(
                    protocol="tcp",
                    from_port=5432,
                    to_port=5432,
                    cidr_blocks=["10.0.0.0/16"],  # restrict to VPC CIDR
                )
            ],
            egress=[
                aws.ec2.SecurityGroupEgressArgs(
                    protocol="-1",
                    from_port=0,
                    to_port=0,
                    cidr_blocks=["0.0.0.0/0"],
                    ipv6_cidr_blocks=["::/0"],
                )
            ],
            tags={"Name": f"{name}-rds-sg"},
        )

        self.subnet_group = aws.rds.SubnetGroup(
            f"{name}-rds-subnet-group",
            subnet_ids=subnet_ids,
            tags={"Name": f"{name}-rds-subnet-group"},
        )

        self.instance = aws.rds.Instance(
            f"{name}-rds",
            engine="postgres",
            engine_version="15",
            instance_class=instance_class,
            allocated_storage=allocated_storage,
            db_subnet_group_name=self.subnet_group.name,
            vpc_security_group_ids=[self.sg.id],
            name=db_name,
            username=username,
            password=password,
            skip_final_snapshot=True,
            multi_az=multi_az,
            publicly_accessible=False,
            storage_encrypted=True,
            deletion_protection=False,
            tags={"Name": f"{name}-rds"},
        )

        pulumi.export("rds_endpoint", self.instance.endpoint)
        pulumi.export("rds_port", self.instance.port)

