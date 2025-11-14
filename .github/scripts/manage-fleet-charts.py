#!/usr/bin/env python3
"""
Manage Fleet Helm chart releases in index.yaml.

Supports two operations:
1. sync: Fetch new Fleet releases from GitHub and add to index
2. cleanup: Remove old RC/beta/alpha versions from index

Usage:
    python manage-fleet-charts.py sync
    python manage-fleet-charts.py cleanup
"""

import os
import sys
import re
import subprocess
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

try:
    import requests
    from ruamel.yaml import YAML
except ImportError as e:
    print(f"Error: {e}. Install with: pip install requests ruamel.yaml")
    sys.exit(1)

yaml = YAML()
yaml.preserve_quotes = True
yaml.width = 4096
yaml.map_indent = 2
yaml.sequence_indent = 2
yaml.sequence_dash_offset = 0

FLEET_REPO = "rancher/fleet"
CHARTS = ["fleet", "fleet-crd", "fleet-agent"]
INDEX_FILE = "index.yaml"
DEV_VERSION_MAX_AGE_DAYS = 14
DEV_VERSION_PATTERN = re.compile(r"(rc|beta|alpha)")
CUTOFF_DATE = datetime.now(timezone.utc) - timedelta(weeks=2)


def extract_base_version(version_string):
    """Extract base version (e.g., '1.2.3' from '1.2.3-rc1')."""
    match = re.match(r'^(\d+\.\d+\.\d+)', version_string)
    return match.group(1) if match else version_string


def is_dev_version(version_dict):
    """Check if entry is a dev version based on version and appVersion fields."""
    version_str = version_dict.get('version', '') + version_dict.get('appVersion', '')
    return bool(DEV_VERSION_PATTERN.search(version_str))


def parse_created_date(version_dict):
    """Parse ISO 8601 datetime from entry's created field."""
    created = version_dict.get('created')
    if '.' in created:
        # Format: 2025-10-29T17:02:09.000000Z
        dt_str = created[:created.index('.') + 7] + 'Z'
        dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S.%fZ")
    else:
        # Format: 2025-10-29T17:02:09Z
        dt = datetime.strptime(created.rstrip('Z'), "%Y-%m-%dT%H:%M:%S")

    # Make timezone-aware (UTC)
    return dt.replace(tzinfo=timezone.utc)


def fetch_releases():
    """Fetch all Fleet releases from GitHub with publication dates."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"token {token}"

    url = f"https://api.github.com/repos/{FLEET_REPO}/releases?per_page=100"
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    releases = {}
    for r in response.json():
        tag = r["tag_name"]
        if "experiment" not in tag.lower() and "hotfix" not in tag.lower():
            version = tag.lstrip("v")
            published = datetime.fromisoformat(r["published_at"].replace("Z", "+00:00"))
            releases[version] = published

    print(f"Found {len(releases)} GitHub Fleet releases")
    return releases


def get_existing_versions():
    """Get existing Fleet chart versions from index.yaml."""
    with open(INDEX_FILE) as f:
        index = yaml.load(f)

    versions = {e["version"] for e in index.get("entries", {}).get("fleet", [])}
    print(f"Found {len(versions)} existing versions in the index")
    return versions


def get_versions_to_keep(all_versions):
    """
    Apply retention policy to determine which versions should be in the index.

    Policy:
    - Keep all stable versions
    - Keep recent dev versions (< 2 weeks old)
    - Keep latest old dev per base ONLY if no stable AND no other dev exists

    Args:
        all_versions: Dict mapping version strings to publication datetimes

    Returns:
        Set of version strings to keep
    """
    stable_versions = {v for v in all_versions if not bool(DEV_VERSION_PATTERN.search(v))}
    dev_versions = {v for v in all_versions if bool(DEV_VERSION_PATTERN.search(v))}

    # Get bases with stable releases
    stable_bases = {extract_base_version(v.split('-')[0]) for v in stable_versions}

    # Sort dev by date (newest first) to process in priority order
    dev_sorted = sorted(dev_versions, key=lambda v: all_versions[v], reverse=True)

    kept_dev = set()
    dev_bases_seen = set()  # Track ALL dev bases we keep (recent or old)

    for version in dev_sorted:
        published = all_versions[version]
        base = extract_base_version(version.split('-')[0])
        is_old = published < CUTOFF_DATE

        # Keep recent dev (< 2 weeks)
        if not is_old:
            kept_dev.add(version)
            dev_bases_seen.add(base)
        # Keep first old dev per base ONLY if no stable and no dev seen yet
        elif base not in stable_bases and base not in dev_bases_seen:
            kept_dev.add(version)
            dev_bases_seen.add(base)

    return stable_versions | kept_dev

def download_chart(chart, version, dest_dir):
    """Download a chart package to version-specific subdirectory."""
    url = f"https://github.com/{FLEET_REPO}/releases/download/v{version}/{chart}-{version}.tgz"
    version_dir = dest_dir / f"v{version}"
    version_dir.mkdir(exist_ok=True)
    dest_file = version_dir / f"{chart}-{version}.tgz"
    print(f"  Downloading {chart}-{version}.tgz...")

    response = requests.get(url, stream=True)
    response.raise_for_status()

    with open(dest_file, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)


def update_index(charts_dir):
    """Update index.yaml with helm CLI."""
    url = f"https://github.com/{FLEET_REPO}/releases/download"
    subprocess.run(
        ["helm", "repo", "index", str(charts_dir), "--url", url, "--merge", INDEX_FILE],
        check=True, capture_output=True, text=True
    )
    shutil.move(str(charts_dir / "index.yaml"), INDEX_FILE)


def sync_releases():
    """Sync Fleet releases from GitHub to the Helm index."""
    all_releases = fetch_releases()
    existing = get_existing_versions()

    # Combine GitHub releases with existing index (use GitHub dates where available)
    combined = dict(all_releases)
    for v in existing:
        if v not in combined:
            # Version in index but not in GitHub (old/removed release)
            combined[v] = CUTOFF_DATE - timedelta(days=365)

    # Determine which versions should exist based on complete picture
    versions_to_keep = get_versions_to_keep(combined)

    # Find what's missing from index (only from GitHub releases)
    missing = [(v, all_releases[v]) for v in versions_to_keep if v in all_releases and v not in existing]

    if not missing:
        print("All Fleet releases are already in the index")
        return

    print(f"Found {len(missing)} missing version(s):")
    now = datetime.now(timezone.utc)
    for v, published in missing:
        age_days = (now - published).days
        print(f"  {v} ({age_days} days old)")

    charts_dir = Path(tempfile.mkdtemp()) / "charts"
    charts_dir.mkdir(parents=True)
    added, failed = 0, 0

    try:
        for version, _ in missing:
            print(f"Processing {version}...")
            try:
                for chart in CHARTS:
                    download_chart(chart, version, charts_dir)
                added += 1
            except Exception as e:
                print(f"Failed to download {version}: {e}")
                failed += 1

        if added > 0:
            print("Updating index.yaml...")
            update_index(charts_dir)
            print("Index updated")
    finally:
        shutil.rmtree(charts_dir.parent)

    print(f"Successfully added: {added}, Failed: {failed}")

    if added > 0:
        with open("synced_versions.txt", "w") as f:
            f.write(",".join(v for v, _ in missing[:added]))

def cleanup_old_versions():
    """
    Cleanup old RC/beta/alpha versions from Helm chart index.yaml.

    Uses version retention policy to determine which versions to keep.
    See get_versions_to_keep() for policy details.
    """
    with open(INDEX_FILE, 'r') as file:
        data = yaml.load(file)

    removed_versions = []

    for chart in list(data['entries']):
        versions = data['entries'][chart]

        # Build version->date mapping from index entries
        version_dates = {v.get('version'): parse_created_date(v) for v in versions}

        # Get versions that should be kept
        versions_to_keep = get_versions_to_keep(version_dates)

        # Filter to keep only those versions
        kept_versions = [v for v in versions if v.get('version') in versions_to_keep]

        # Track removed versions
        for v in versions:
            if v not in kept_versions:
                version = v.get('version')
                print(f"Removing {chart} {version}")
                removed_versions.append(version)

        data['entries'][chart] = kept_versions

        if not data['entries'][chart]:
            del data['entries'][chart]

    if removed_versions:
        with open('removed_versions.txt', 'w') as f:
            f.write(','.join(removed_versions))

    with open(INDEX_FILE, 'w') as file:
        yaml.dump(data, file)

    print(f"Removed {len(removed_versions)} old version(s)")

def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: manage-fleet-charts.py [sync|cleanup]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "sync":
        sync_releases()
    elif command == "cleanup":
        cleanup_old_versions()
    else:
        print(f"Unknown command: {command}")
        print("Usage: manage-fleet-charts.py [sync|cleanup]")
        sys.exit(1)


if __name__ == "__main__":
    main()
