# Documentation Platform

```bash
./pulumi/
├── components
│   ├── compute
│   │   ├── alb_controller.py
│   │   ├── eks.py
│   │   ├── __init__.py
│   │   ├── karpenter.py
│   │   └── wikijs.py
│   ├── __init__.py
│   ├── monitoring
│   │   ├── efk.py
│   │   ├── keda.py
│   │   └── observability.py
│   ├── networking
│   │   ├── __init__.py
│   │   └── vpc.py
│   ├── security
│   │   ├── iam.py
│   │   └── __init__.py
│   └── storage
│       ├── __init__.py
│       ├── rds.py
│       └── s3.py
├── __main__.py
├── Pulumi.prod.yaml
├── Pulumi.yaml
└── requirements.txt
```

An internal knowledge management platform for teams that allows employees to collaborate on documentation, store company policies, and manage technical knowledge in a structured way.

The chosen [Wiki.js](https://js.wiki/), an open-source, self-hosted wiki platform that provides a powerful editor, authentication options, and content organization features.

### Secrets (set before deploy)
- `pulumi config set --secret wikijs:dbUser <value>`
- `pulumi config set --secret wikijs:dbPassword <value>`
- `pulumi config set --secret grafana:adminPassword <value>`
- Optional overrides:
  - `pulumi config set wikijs:dbName <value>` (defaults to `wikijs`)
  - `pulumi config set wikijs:dbHost <value>` (if overriding RDS host)

### Implemented Requirements (what we built)
- Reliability: Multi-AZ VPC/EKS, ALB ingress, Wiki.js replicas.
- Security: Private RDS, S3 with SSE/versioning, ALB limited to Cloudflare IPs, IAM least privilege, HTTPS via ACM.
- Scalability: Karpenter (spot, amd64/arm64, scale-to-zero), KEDA autoscaling on request rate, tunable replicas.
- Observability: Prometheus/Grafana, EFK, alerting-ready.
- Automation: Pulumi-defined networking, compute, storage, security, and monitoring.

### Implemented Considerations (how we addressed them)
- Compute: Wiki.js on EKS via Helm; ALB ingress controller; Karpenter provisions all nodes (no managed node group).
- Storage: RDS PostgreSQL (external DB), S3 for assets, EBS storage class for app persistence.
- Networking: VPC with public/private subnets across 2 AZs, IGW/NAT, ALB ingress restricted to Cloudflare, HTTPS-ready.
- Scaling: Karpenter + KEDA (Prometheus request-rate trigger), horizontal pod scaling; spot capacity with consolidation and scale-to-zero.
- Monitoring: kube-prometheus-stack (Prometheus/Grafana), EFK for logs; Grafana admin via Pulumi secret.

### Deployment
- Deployment covers setup, teardown, troubleshooting, and configuration reference.
- Pulumi entrypoint: `pulumi/__main__.py`; prod stack scaffolded in `pulumi/stacks/`.
- Deploy: `cd pulumi && pip install -r requirements.txt && pulumi stack select prod && pulumi up`.

### Security
- Security covers auth/access control, data protection, and best practices.
- ALB ingress restricted to Cloudflare IPs; HTTPS enabled via ACM when `certificate_arn` is provided.
- RDS runs in private subnets; SG allows 5432 only within VPC CIDR.
- S3 is private with SSE, versioning, and public access blocks.

### Components (Pulumi)
- Reusable layers:
  - **compute/**: EKS, ALB controller, Karpenter, Wiki.js Helm
  - **storage/**: RDS, S3
  - **networking/**: VPC, subnets, security groups, load balancers
  - **monitoring/**: KEDA, Prometheus/Grafana, EFK
  - **security/**: IAM roles, policies, secrets management
- Each component is self-contained and reusable.

### Stacks
- Environment-specific stack configs (prod scaffold provided in `pulumi/stacks/prod`).
- Each stack can define its own overrides and configs.

### Observability & Autoscaling
- Prometheus/Grafana via kube-prometheus-stack (Grafana password from Pulumi secret).
- KEDA scaled object uses Prometheus HTTP request rate for Wiki.js.
- Karpenter provisioner: spot-only, amd64/arm64, scale-to-zero, consolidation on; it is the sole capacity provider (managed node group disabled).

