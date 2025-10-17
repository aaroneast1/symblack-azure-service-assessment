#!/usr/bin/env python3
"""
Terraform Generator
Generates Terraform configuration for multi-subscription Azure service principal setup.
"""

import json
from pathlib import Path
from typing import Dict, List
from datetime import datetime


class TerraformGenerator:
    """Generates Terraform configuration files."""

    def __init__(self):
        """Initialize the Terraform generator."""
        pass

    def generate(
        self,
        analysis_result: Dict,
        output_dir: Path,
        subscriptions: List[Dict]
    ) -> None:
        """
        Generate complete Terraform configuration.

        Args:
            analysis_result: Consolidated analysis result
            output_dir: Directory to save Terraform files
            subscriptions: List of subscription metadata dicts
        """
        print("\n" + "=" * 70)
        print("GENERATING TERRAFORM CONFIGURATION")
        print("=" * 70)

        terraform_dir = output_dir / "terraform"
        terraform_dir.mkdir(parents=True, exist_ok=True)

        # Extract providers from analysis
        providers = analysis_result["consolidated"]["unique_providers"]

        # Generate role definition
        role_def = self._generate_role_definition(providers)

        # Generate Terraform files
        self._generate_provider_tf(terraform_dir)
        self._generate_variables_tf(terraform_dir, subscriptions)
        self._generate_role_tf(terraform_dir, role_def)
        self._generate_application_tf(terraform_dir)
        self._generate_role_assignments_tf(terraform_dir)
        self._generate_outputs_tf(terraform_dir)
        self._generate_tfvars(terraform_dir, subscriptions)
        self._generate_gitignore(terraform_dir)
        self._generate_readme(terraform_dir, analysis_result, subscriptions, role_def)

        print(f"\n✅ Terraform configuration generated in: {terraform_dir}")
        print(f"   • Subscriptions: {len(subscriptions)}")
        print(f"   • Providers: {len(providers)}")
        print(f"   • Permissions: {len(role_def['Actions'])}")

    def _generate_role_definition(self, providers: List[str]) -> Dict:
        """
        Generate RBAC role definition.

        Args:
            providers: List of provider namespaces

        Returns:
            Role definition dict
        """
        actions = []

        # Generate read permissions for each provider
        # Note: Azure only allows ONE wildcard per action
        for provider in sorted(providers):
            actions.append(f"{provider}/*/read")

        # Add essential assessment actions
        essential_actions = [
            "*/read",
            "Microsoft.ResourceGraph/resources/read",
            "Microsoft.CostManagement/*/read",
            "Microsoft.CostManagement/query/action",
            "Microsoft.CostManagement/exports/action",
            "Microsoft.Security/*/read",
            "Microsoft.SecurityInsights/*/read",
            "Microsoft.PolicyInsights/*/read",
            "Microsoft.Advisor/*/read",
            "Microsoft.Insights/*/read",
            "Microsoft.OperationalInsights/*/read",
            "Microsoft.Resources/subscriptions/read",
            "Microsoft.Resources/subscriptions/resourceGroups/read",
            "Microsoft.Management/managementGroups/read",
            "Microsoft.Support/*/read",
            "Microsoft.AAD/*/read",
        ]

        actions.extend(essential_actions)

        # Remove duplicates
        unique_actions = list(dict.fromkeys(actions))

        role_definition = {
            "Name": "SymmetryBlackSecurityAssessmentRole",
            "IsCustom": True,
            "Description": f"Read-only role for security assessment - Generated {datetime.now().strftime('%Y-%m-%d')}",
            "Actions": unique_actions,
            "NotActions": [
                "Microsoft.Storage/storageAccounts/listKeys/action",
                "Microsoft.Storage/storageAccounts/regeneratekey/action",
                "Microsoft.KeyVault/vaults/secrets/read",
                "Microsoft.KeyVault/vaults/keys/read",
                "Microsoft.Web/sites/config/list/action",
            ],
            "DataActions": [],
            "NotDataActions": [
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
                "Microsoft.KeyVault/vaults/secrets/getSecret/action",
                "Microsoft.KeyVault/vaults/keys/decrypt/action",
                "Microsoft.ServiceBus/namespaces/messages/receive/action",
            ]
        }

        return role_definition

    def _generate_provider_tf(self, terraform_dir: Path) -> None:
        """Generate provider.tf file."""
        content = '''terraform {
  required_version = ">= 1.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.9"
    }
  }
}

provider "azurerm" {
  features {}
  # Will use the first subscription in the list as the primary
  subscription_id = var.subscription_ids[0]
}

provider "azuread" {
  tenant_id = var.tenant_id
}
'''
        (terraform_dir / "provider.tf").write_text(content)
        print("  ✓ provider.tf")

    def _generate_variables_tf(self, terraform_dir: Path, subscriptions: List[Dict]) -> None:
        """Generate variables.tf file."""
        content = '''variable "subscription_ids" {
  description = "List of Azure Subscription IDs to grant access"
  type        = list(string)
}

variable "tenant_id" {
  description = "Azure Tenant ID"
  type        = string
}

variable "application_name" {
  description = "Name of the Azure AD Application"
  type        = string
  default     = "SymmetryBlack-SecurityAssessment"
}

variable "role_name" {
  description = "Name of the custom RBAC role"
  type        = string
  default     = "SymmetryBlackSecurityAssessmentRole"
}
'''
        (terraform_dir / "variables.tf").write_text(content)
        print("  ✓ variables.tf")

    def _generate_role_tf(self, terraform_dir: Path, role_def: Dict) -> None:
        """Generate role.tf file."""
        actions_json = json.dumps(role_def['Actions'], indent=6)
        not_actions_json = json.dumps(role_def['NotActions'], indent=6)
        data_actions_json = json.dumps(role_def['DataActions'], indent=6)
        not_data_actions_json = json.dumps(role_def['NotDataActions'], indent=6)

        content = f'''# Custom RBAC Role Definition
# This role will be created once and assigned to all subscriptions

resource "azurerm_role_definition" "security_assessment" {{
  name        = var.role_name
  scope       = "/subscriptions/${{var.subscription_ids[0]}}"
  description = "{role_def['Description']}"

  permissions {{
    actions          = {actions_json}
    not_actions      = {not_actions_json}
    data_actions     = {data_actions_json}
    not_data_actions = {not_data_actions_json}
  }}

  # Assignable to all specified subscriptions
  assignable_scopes = [
    for sub_id in var.subscription_ids : "/subscriptions/${{sub_id}}"
  ]
}}
'''
        (terraform_dir / "role.tf").write_text(content)
        print("  ✓ role.tf")

    def _generate_application_tf(self, terraform_dir: Path) -> None:
        """Generate application.tf file."""
        content = '''# Azure AD Application
resource "azuread_application" "security_assessment" {
  display_name = var.application_name
  owners       = [data.azuread_client_config.current.object_id]
}

# Service Principal for the application
resource "azuread_service_principal" "security_assessment" {
  client_id = azuread_application.security_assessment.client_id
  owners    = [data.azuread_client_config.current.object_id]
}

# Generate a client secret
resource "time_rotating" "secret_rotation" {
  rotation_days = 365
}

resource "azuread_application_password" "security_assessment" {
  application_id = azuread_application.security_assessment.id
  display_name   = "Terraform-managed secret"

  rotate_when_changed = {
    rotation = time_rotating.secret_rotation.id
  }
}

# Get current Azure AD configuration
data "azuread_client_config" "current" {}
'''
        (terraform_dir / "application.tf").write_text(content)
        print("  ✓ application.tf")

    def _generate_role_assignments_tf(self, terraform_dir: Path) -> None:
        """Generate role-assignments.tf file."""
        content = '''# Role assignment for each subscription
# This creates one assignment per subscription

resource "azurerm_role_assignment" "security_assessment" {
  for_each = toset(var.subscription_ids)

  scope              = "/subscriptions/${each.value}"
  role_definition_id = azurerm_role_definition.security_assessment.role_definition_resource_id
  principal_id       = azuread_service_principal.security_assessment.object_id

  depends_on = [
    azurerm_role_definition.security_assessment,
    azuread_service_principal.security_assessment
  ]
}
'''
        (terraform_dir / "role-assignments.tf").write_text(content)
        print("  ✓ role-assignments.tf")

    def _generate_outputs_tf(self, terraform_dir: Path) -> None:
        """Generate outputs.tf file."""
        content = '''output "tenant_id" {
  description = "Azure Tenant ID"
  value       = var.tenant_id
}

output "subscription_ids" {
  description = "Azure Subscription IDs"
  value       = var.subscription_ids
}

output "application_id" {
  description = "Azure AD Application ID"
  value       = azuread_application.security_assessment.client_id
}

output "client_id" {
  description = "Service Principal Client ID (same as application_id)"
  value       = azuread_application.security_assessment.client_id
}

output "client_secret" {
  description = "Service Principal Client Secret"
  value       = azuread_application_password.security_assessment.value
  sensitive   = true
}

output "object_id" {
  description = "Service Principal Object ID"
  value       = azuread_service_principal.security_assessment.object_id
}

output "role_definition_id" {
  description = "Custom Role Definition ID"
  value       = azurerm_role_definition.security_assessment.role_definition_resource_id
}

output "role_name" {
  description = "Custom Role Name"
  value       = azurerm_role_definition.security_assessment.name
}

output "login_command" {
  description = "Azure CLI login command"
  value       = "az login --service-principal -u ${azuread_application.security_assessment.client_id} -p '<secret>' --tenant ${var.tenant_id}"
}
'''
        (terraform_dir / "outputs.tf").write_text(content)
        print("  ✓ outputs.tf")

    def _generate_tfvars(self, terraform_dir: Path, subscriptions: List[Dict]) -> None:
        """Generate terraform.tfvars file."""
        subscription_ids = [sub["subscription_id"] for sub in subscriptions]
        tenant_id = subscriptions[0]["tenant_id"] if subscriptions else ""

        # Format subscription IDs as Terraform list
        sub_ids_list = json.dumps(subscription_ids, indent=2)

        content = f'''subscription_ids = {sub_ids_list}
tenant_id        = "{tenant_id}"
application_name = "SymmetryBlack-SecurityAssessment"
role_name        = "SymmetryBlackSecurityAssessmentRole"
'''
        (terraform_dir / "terraform.tfvars").write_text(content)
        print("  ✓ terraform.tfvars")

    def _generate_gitignore(self, terraform_dir: Path) -> None:
        """Generate .gitignore file."""
        content = '''# Terraform files
.terraform/
*.tfstate
*.tfstate.*
*.tfplan
.terraform.lock.hcl

# Sensitive files
terraform.tfvars
*.auto.tfvars

# Crash logs
crash.log
crash.*.log

# Override files
override.tf
override.tf.json
*_override.tf
*_override.tf.json
'''
        (terraform_dir / ".gitignore").write_text(content)
        print("  ✓ .gitignore")

    def _generate_readme(
        self,
        terraform_dir: Path,
        analysis_result: Dict,
        subscriptions: List[Dict],
        role_def: Dict
    ) -> None:
        """Generate README.md file."""
        sub_list = "\n".join([
            f"- {sub['subscription_name']} (`{sub['subscription_id']}`)"
            for sub in subscriptions
        ])

        providers_list = "\n".join([
            f"- {p}"
            for p in sorted(analysis_result["consolidated"]["unique_providers"])[:20]
        ])

        remaining = len(analysis_result["consolidated"]["unique_providers"]) - 20
        if remaining > 0:
            providers_list += f"\n... and {remaining} more"

        content = f'''# Azure Security Assessment - Multi-Subscription Terraform Deployment

**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 📋 Subscriptions Covered

{sub_list}

## 🚀 Quick Start

### 1. Initialize Terraform

```bash
terraform init
```

### 2. Review the Plan

```bash
terraform plan
```

### 3. Deploy

```bash
terraform apply
```

### 4. Retrieve Credentials

```bash
# View all outputs
terraform output

# Get client secret (sensitive)
terraform output -raw client_secret
```

## 🔑 Using the Service Principal

### Azure CLI

```bash
# Set credentials
export CLIENT_ID=$(terraform output -raw client_id)
export CLIENT_SECRET=$(terraform output -raw client_secret)
export TENANT_ID=$(terraform output -raw tenant_id)

# Login
az login --service-principal \\
  -u $CLIENT_ID \\
  -p $CLIENT_SECRET \\
  --tenant $TENANT_ID

# Test access across subscriptions
for SUB_ID in $(terraform output -json subscription_ids | jq -r '.[]'); do
  echo "Testing subscription: $SUB_ID"
  az account set --subscription $SUB_ID
  az resource list --output table | head -5
done
```

## 📊 Discovery Results

### Total Statistics
- **Subscriptions:** {len(subscriptions)}
- **Providers:** {analysis_result["consolidated"]["total_providers"]}
- **Services:** {analysis_result["consolidated"]["total_services"]}
- **Permissions:** {len(role_def["Actions"])}

### Discovered Providers (Top 20)

{providers_list}

## 📋 What Gets Created

1. **Custom RBAC Role**
   - Name: `SymmetryBlackSecurityAssessmentRole`
   - Assignable to all specified subscriptions
   - Read-only permissions for discovered services

2. **Azure AD Application**
   - Name: `SymmetryBlack-SecurityAssessment`

3. **Service Principal**
   - Linked to the application
   - 365-day credential rotation

4. **Role Assignments**
   - One per subscription
   - Grants the custom role to the service principal

## 🧪 Testing Access

```bash
# Login with service principal
az login --service-principal \\
  -u <client-id> \\
  -p <client-secret> \\
  --tenant <tenant-id>

# Test commands
az account list --output table
az resource list --output table
az security assessment list
az advisor recommendation list
```

## 🗑️ Cleanup

```bash
# Destroy all resources
terraform destroy
```

## ⚠️ Security Notes

1. **Client Secret:** Stored in Terraform state
2. **State Files:** Use remote backend (Azure Storage, Terraform Cloud)
3. **Never commit:** `terraform.tfstate` to version control
4. **Rotation:** Secrets auto-rotate after 1 year
5. **Audit:** All activities logged in Azure Activity Log

## 📚 Additional Resources

- [Terraform AzureRM Provider](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs)
- [Azure RBAC Documentation](https://docs.microsoft.com/en-us/azure/role-based-access-control/)
- [Service Principal Best Practices](https://docs.microsoft.com/en-us/azure/active-directory/develop/howto-create-service-principal-portal)
'''
        (terraform_dir / "README.md").write_text(content)
        print("  ✓ README.md")
