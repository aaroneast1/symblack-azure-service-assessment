# Azure Multi-Subscription Security Assessment Tool

Generate Azure AD application and service principal for Symmetry Black Azure Cybersecurity Assessment across multiple subscriptions.

## Overview

This tool analyzes your Azure subscriptions to:
1. **Discover all services** used across multiple subscriptions (activity logs: 90 days, cost data: 365 days)
2. **Map services to providers** - Azure Resource Providers for RBAC permissions
3. **Generate Terraform** - Infrastructure-as-Code for service principal deployment
4. **Multi-subscription support** - One service principal with access to all subscriptions

## Prerequisites

### System Requirements
- **Python 3.9+**
- **Azure CLI 2.0+**
- **Terraform 1.0+**

### Prerequisites Installation Instructions

#### macOS

Using Homebrew (recommended):
```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install prerequisites
brew install python@3.9
brew install azure-cli
brew install terraform

# Verify installations
python3 --version
az --version
terraform --version
```

#### Windows

Using winget (Windows 10 1709+):
```powershell
# Install prerequisites
winget install Python.Python.3.9
winget install Microsoft.AzureCLI
winget install HashiCorp.Terraform

# Verify installations (open new terminal after installation)
python --version
az --version
terraform --version
```

### Azure Requirements

#### For Discovery (Running assess.py)
You need read access to all subscriptions:
- **Microsoft.CostManagement/query/action** (Cost Management access)
- **Microsoft.Resources/subscriptions/read** (subscription information)
- **Microsoft.Insights/ActivityLog/read** (Activity Log access)

Typically, **Reader** role on subscriptions is sufficient for discovery.

#### For Deployment (Running terraform apply)
You need permissions to create Azure AD applications and role assignments:
- **Application Administrator** or **Cloud Application Administrator** role in Azure AD
- **Owner** or **User Access Administrator** role on all subscriptions
- **Microsoft.Authorization/roleDefinitions/write** (to create custom roles)
- **Microsoft.Authorization/roleAssignments/write** (to assign roles)

#### For Cleanup (Running terraform destroy)
Same permissions as deployment:
- **Application Administrator** role in Azure AD (to delete applications)
- **Owner** or **User Access Administrator** role (to delete role assignments)

**Note:** If you lack these permissions, see the "Clean Up" section for manual cleanup steps or ask your Azure administrator for assistance.

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/yourusername/symblack-azure-service-assessment.git
cd symblack-azure-service-assessment
```

### 2. Install Python Dependencies

```bash
# macOS/Linux
pip3 install -r requirements.txt

# Windows
pip install -r requirements.txt
```

### 3. Login to Azure

```bash
az login
```

## Usage

### Basic Usage

```bash
# Assess all subscriptions you have access to
python3 assess.py
```

### Command Line Options

```bash
# Assess specific subscriptions only
python3 assess.py --subscriptions "sub-id-1,sub-id-2,sub-id-3"

# Custom output directory
python3 assess.py --output-dir ./my-assessment

# Force refresh all data (re-download even if files exist)
python3 assess.py --force-refresh

# View help
python3 assess.py --help
```

## What Gets Generated

```
output/
├── {subscription-id-1}/
│   ├── subscription-info.json           # Subscription metadata
│   ├── activity-log/
│   │   ├── activity-log.2024-07-19_to_2024-08-18.json
│   │   ├── activity-log.2024-08-19_to_2024-09-17.json
│   │   └── ... (3 files for 90 days)
│   └── cost-management/
│       ├── cost-management.2024-10-18_to_2024-11-16.json
│       └── ... (12 files for 365 days)
├── {subscription-id-2}/
│   └── ... (same structure)
├── azure-service-consumption.2025-10-17.json
└── terraform/
    ├── provider.tf
    ├── variables.tf
    ├── role.tf
    ├── application.tf
    ├── role-assignments.tf        # One assignment per subscription
    ├── outputs.tf
    ├── terraform.tfvars
    ├── README.md
    └── .gitignore
```

## Deployment

### Deploy with Terraform

```bash
cd output/terraform

# Initialize Terraform
terraform init

# Review the plan
terraform plan

# Deploy Azure AD application and service principal
terraform apply

# Retrieve credentials
terraform output
terraform output -raw client_secret  # Sensitive - will show the secret
```

### Using the Service Principal

After Terraform deployment:

**Azure CLI:**
```bash
# Get credentials from Terraform
CLIENT_ID=$(terraform output -raw client_id)
CLIENT_SECRET=$(terraform output -raw client_secret)
TENANT_ID=$(terraform output -raw tenant_id)

# Login
az login --service-principal \
  -u $CLIENT_ID \
  -p $CLIENT_SECRET \
  --tenant $TENANT_ID

# Test access across subscriptions
az account list --output table
az account set --subscription "sub-id-1"
az resource list --output table
```

**Python SDK:**
```python
from azure.identity import ClientSecretCredential
from azure.mgmt.resource import ResourceManagementClient

credential = ClientSecretCredential(
    tenant_id="your-tenant-id",
    client_id="your-client-id",
    client_secret="your-client-secret"
)

# Use with any subscription
resource_client = ResourceManagementClient(
    credential,
    "subscription-id"
)

for rg in resource_client.resource_groups.list():
    print(rg.name)
```

## Permissions Included

The generated role includes:

### Read-Only Access
- **All discovered Resource Providers**: Describe, Get, List operations
- **Cost Management**: Query and export cost data
- **Security Center**: Security assessments and recommendations
- **Policy Insights**: Compliance and policy evaluation
- **Azure Advisor**: Best practice recommendations
- **Monitor/Insights**: Metrics, logs, and diagnostics
- **Resource Graph**: Advanced resource queries

### Explicitly Denied
- Storage account keys
- Key Vault secrets and keys
- Database connection strings
- Data plane operations (blob content, database records)
- Write/Delete/Modify operations

## Testing Your Access

After deployment, verify the service principal works:

```bash
# Login with service principal
az login --service-principal \
  -u <client-id> \
  -p <client-secret> \
  --tenant <tenant-id>

# Test commands across subscriptions
for SUB in $(az account list --query "[].id" -o tsv); do
  echo "Testing subscription: $SUB"
  az account set --subscription $SUB
  az resource list --query "[0:3].{Name:name, Type:type}" -o table
done

# Test security and advisor commands
az security assessment list
az advisor recommendation list
```

## Clean Up

Remove all created resources:

### Using Terraform (Recommended)
```bash
cd output/terraform
terraform destroy
```

### Remove Local Files
```bash
# Remove output files
rm -rf output/
```

## License

GPL-3.0 - See [LICENSE](LICENSE) file for details.
