#!/usr/bin/env python3
"""
Azure CLI Wrapper
Provides a clean interface for executing Azure CLI commands.
"""

import subprocess
import json
import sys
from typing import Optional, Union, Dict, List


class AzureClient:
    """Wrapper for Azure CLI commands."""

    def __init__(self):
        """Initialize the Azure CLI client."""
        self.timeout_default = 120  # 2 minutes default timeout

    def check_cli_installed(self) -> bool:
        """Check if Azure CLI is installed."""
        try:
            subprocess.run(["az", "--version"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def check_logged_in(self) -> bool:
        """Check if user is logged in to Azure."""
        try:
            result = self.run_command(["account", "show"], allow_failure=True)
            # If result is a dict with "failed" key, login failed
            return not (isinstance(result, dict) and result.get("failed", False))
        except:
            return False

    def run_command(
        self,
        command: List[str],
        allow_failure: bool = False,
        timeout: Optional[int] = None
    ) -> Union[Dict, List]:
        """
        Execute Azure CLI command and return JSON output.

        Args:
            command: List of command arguments (e.g., ["account", "show"])
            allow_failure: If True, return error dict instead of exiting
            timeout: Command timeout in seconds (default: 120)

        Returns:
            Parsed JSON output or error dict if allow_failure=True
        """
        cmd = ["az"] + command + ["--output", "json"]
        timeout = timeout or self.timeout_default

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout
            )

            if result.stdout.strip():
                return json.loads(result.stdout)
            return {}

        except subprocess.TimeoutExpired:
            error_msg = f"Command timed out after {timeout} seconds"
            if allow_failure:
                return {"error": error_msg, "failed": True}
            print(f"❌ Azure CLI Timeout: {error_msg}", file=sys.stderr)
            sys.exit(1)

        except subprocess.CalledProcessError as e:
            if allow_failure:
                return {"error": e.stderr, "failed": True}
            print(f"❌ Azure CLI Error: {e.stderr}", file=sys.stderr)
            sys.exit(1)

        except json.JSONDecodeError as e:
            if allow_failure:
                return {"error": str(e), "failed": True}
            print(f"❌ JSON Parse Error: {e}", file=sys.stderr)
            sys.exit(1)

    def set_subscription(self, subscription_id: str) -> bool:
        """
        Set the active Azure subscription.

        Args:
            subscription_id: Azure subscription ID

        Returns:
            True if successful, False otherwise
        """
        result = self.run_command(
            ["account", "set", "--subscription", subscription_id],
            allow_failure=True
        )
        return not (isinstance(result, dict) and result.get("failed", False))

    def get_current_subscription(self) -> Optional[Dict]:
        """
        Get information about the current subscription.

        Returns:
            Subscription info dict or None if failed
        """
        result = self.run_command(["account", "show"], allow_failure=True)
        if isinstance(result, dict) and result.get("failed"):
            return None
        return result if isinstance(result, dict) else None

    def list_subscriptions(self) -> List[Dict]:
        """
        List all Azure subscriptions the user has access to.

        Returns:
            List of subscription dicts
        """
        result = self.run_command(["account", "list"], allow_failure=True)
        # Check if result is a list (success) or dict (failure)
        if not isinstance(result, list):
            return []
        return result

    def rest_api_call(
        self,
        method: str,
        uri: str,
        body: Optional[str] = None,
        timeout: Optional[int] = None
    ) -> Dict:
        """
        Execute Azure REST API call using az rest.

        Args:
            method: HTTP method (GET, POST, etc.)
            uri: Full Azure REST API URI
            body: Optional JSON body (as string or path to file with @)
            timeout: Command timeout in seconds

        Returns:
            API response as dict
        """
        cmd = ["rest", "--method", method, "--uri", uri]
        if body:
            cmd.extend(["--body", body])

        return self.run_command(cmd, allow_failure=True, timeout=timeout)
