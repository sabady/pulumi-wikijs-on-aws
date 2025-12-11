"""S3 bucket component for WikiJS storage."""
import pulumi
import pulumi_aws as aws
import pulumi_random as random


class S3BucketComponent:
    """Creates S3 bucket for WikiJS storage."""

    def __init__(self, name: str, enable_versioning: bool = True):
        """Initialize S3 bucket component.

        Args:
            name: Base name for resources
            enable_versioning: Enable versioning on the bucket
        """
        self.name = name
        self.bucket = None
        self._create_bucket(enable_versioning)

    def _create_bucket(self, enable_versioning: bool):
        """Create S3 bucket with appropriate configuration."""
        # Generate unique bucket name with UUID postfix
        unique_id = random.RandomUuid(f"{self.name}-bucket-uuid")
        bucket_name = pulumi.Output.concat(self.name, "-wikijs-storage-", pulumi.get_stack(), "-", unique_id.result)

        self.bucket = aws.s3.BucketV2(
            f"{self.name}-wikijs-bucket",
            bucket=bucket_name,
            tags={
                "Name": bucket_name,
                "Purpose": "WikiJS storage",
            },
        )

        # Enable versioning if requested
        if enable_versioning:
            aws.s3.BucketVersioningV2(
                f"{self.name}-bucket-versioning",
                bucket=self.bucket.id,
                versioning_configuration=aws.s3.BucketVersioningV2VersioningConfigurationArgs(
                    status="Enabled",
                ),
            )

        # Block public access
        aws.s3.BucketPublicAccessBlock(
            f"{self.name}-bucket-pab",
            bucket=self.bucket.id,
            block_public_acls=True,
            block_public_policy=True,
            ignore_public_acls=True,
            restrict_public_buckets=True,
        )

        # Server-side encryption
        aws.s3.BucketServerSideEncryptionConfigurationV2(
            f"{self.name}-bucket-encryption",
            bucket=self.bucket.id,
            rules=[
                aws.s3.BucketServerSideEncryptionConfigurationV2RuleArgs(
                    apply_server_side_encryption_by_default=aws.s3.BucketServerSideEncryptionConfigurationV2RuleApplyServerSideEncryptionByDefaultArgs(
                        sse_algorithm="AES256",
                    ),
                ),
            ],
        )

        # Export bucket name
        pulumi.export("wikijs_s3_bucket_name", self.bucket.id)

