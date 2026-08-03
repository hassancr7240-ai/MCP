"""
Auto-Tagging Script for APIM APIs.

Automatically applies mcp-enabled or mcp-excluded tags to all APIs
in APIM based on naming rules. Run this manually or via Azure DevOps
pipeline on a schedule.

Usage:
    python scripts/auto_tag_apis.py              # dry run (no changes)
    python scripts/auto_tag_apis.py --apply      # apply tags for real

Requirements:
    pip install azure-identity azure-mgmt-apimanagement
"""
from __future__ import annotations

import argparse
import logging
import os

from azure.identity import AzureCliCredential, DefaultAzureCredential
from azure.mgmt.apimanagement import ApiManagementClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
SUBSCRIPTION_ID = os.getenv("AZURE_SUBSCRIPTION_ID", "ea51059b-b5f5-4a86-ae78-6fbf365d1c89")
RESOURCE_GROUP  = os.getenv("APIM_RESOURCE_GROUP",   "rg-dev-integrationTeam")
APIM_NAME       = os.getenv("APIM_SERVICE_NAME",      "apim-dev-intg")

MCP_ENABLED_TAG  = "mcp-enabled"
MCP_EXCLUDED_TAG = "mcp-excluded"

# APIs whose names START WITH these prefixes get mcp-enabled automatically
_ENABLE_PREFIXES = (
    "bark-",
    "dimitri",
    "uom",
    "ebs",
    "otm",
    "wms",
    "logility",
    "service-cloud",
    "pmw",
    "palantir",
    "monitor",
)

# APIs whose names START WITH these prefixes get mcp-excluded automatically
_EXCLUDE_PREFIXES = (
    "o2c_",
    "p2p_",
    "p2m_",
    "b2b_",
    "b2b-",
    "echo_api",
    "testblob",
    "fourkites_",
    "fap_dev_",
    "3pl_ofc_",
    "fn_dev_edi_",
)


def _get_credential():
    try:
        return AzureCliCredential()
    except Exception:
        return DefaultAzureCredential()


def _decide_tag(api_name: str) -> str | None:
    name = api_name.lower().replace("-", "_")
    for prefix in _EXCLUDE_PREFIXES:
        if name.startswith(prefix.replace("-", "_")):
            return MCP_EXCLUDED_TAG
    for prefix in _ENABLE_PREFIXES:
        if name.startswith(prefix.replace("-", "_")):
            return MCP_ENABLED_TAG
    return None


def run(apply: bool = False) -> None:
    credential = _get_credential()
    client = ApiManagementClient(credential, SUBSCRIPTION_ID)

    logger.info("Fetching all APIs from %s ...", APIM_NAME)
    apis = list(client.api.list_by_service(RESOURCE_GROUP, APIM_NAME))
    logger.info("Found %d APIs", len(apis))

    enabled_count  = 0
    excluded_count = 0
    skipped_count  = 0

    for api in apis:
        api_id   = api.name
        api_name = api.name or ""
        current_tags = list(getattr(api, "tags", None) or [])
        desired_tag  = _decide_tag(api_name)

        if desired_tag is None:
            logger.info("SKIP     %s — no rule matches", api_id)
            skipped_count += 1
            continue

        if desired_tag in current_tags:
            logger.info("ALREADY  %s — already has %s", api_id, desired_tag)
            continue

        # Remove opposite tag if present
        new_tags = [t for t in current_tags
                    if t not in (MCP_ENABLED_TAG, MCP_EXCLUDED_TAG)]
        new_tags.append(desired_tag)

        if desired_tag == MCP_ENABLED_TAG:
            enabled_count += 1
        else:
            excluded_count += 1

        if apply:
            client.api.update(
                RESOURCE_GROUP,
                APIM_NAME,
                api_id,
                {"tags": new_tags},
                "*",
            )
            logger.info("TAGGED   %s → %s", api_id, desired_tag)
        else:
            logger.info("DRY RUN  %s → would tag %s", api_id, desired_tag)

    logger.info("")
    logger.info("Summary:")
    logger.info("  Would enable : %d APIs", enabled_count)
    logger.info("  Would exclude: %d APIs", excluded_count)
    logger.info("  Skipped      : %d APIs (no rule)", skipped_count)
    if not apply:
        logger.info("")
        logger.info("Run with --apply to make changes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-tag APIM APIs for MCP")
    parser.add_argument("--apply", action="store_true",
                        help="Actually apply tags (default is dry run)")
    args = parser.parse_args()
    run(apply=args.apply)
