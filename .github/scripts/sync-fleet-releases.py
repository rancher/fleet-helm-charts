#!/usr/bin/env python3
"""Sync all Fleet releases to the Helm chart repository index."""

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

try:
    import requests
    import yaml
except ImportError as e:
    print(f"Error: {e}. Install with: pip install requests pyyaml")
    sys.exit(1)

FLEET_REPO = "rancher/fleet"
CHARTS = ["fleet", "fleet-crd", "fleet-agent"]
INDEX_FILE = "index.yaml"
DEV_VERSION_MAX_AGE_DAYS = 14


def fetch_releases():
    """Fetch all Fleet release versions from GitHub with dates."""
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

    print(f"Found {len(releases)} GitHub Fleet releases (including dev versions)")
    return releases


def should_include_version(version, published_date, existing):
    """Check if a version should be included based on cleanup rules."""
    if version in existing:
        return False

    is_dev = any(tag in version.lower() for tag in ['-rc.', '-beta.', '-alpha.'])

    if not is_dev:
        return True

    # Check if dev version is older than 2 weeks
    age = datetime.now(timezone.utc) - published_date
    if age > timedelta(days=DEV_VERSION_MAX_AGE_DAYS):
        return False

    # For dev versions, only include if no stable release exists for this minor version
    parts = version.split('-')[0].split('.')
    if len(parts) >= 3:
        base_version = '.'.join(parts[:3])
        return base_version not in existing

    return True


def get_existing_versions():
    """Get existing Fleet chart versions from index.yaml."""
    with open(INDEX_FILE) as f:
        index = yaml.safe_load(f)

    versions = {e["version"] for e in index.get("entries", {}).get("fleet", [])}
    print(f"Found {len(versions)} existing versions in the index")
    return versions


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


def main():
    all_releases = fetch_releases()
    existing = get_existing_versions()

    now = datetime.now(timezone.utc)
    missing = [
        (v, published) for v, published in all_releases.items()
        if should_include_version(v, published, existing)
    ]

    if not missing:
        print("All Fleet releases are already in the index")
        return

    print(f"Found {len(missing)} missing version(s):")
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


if __name__ == "__main__":
    main()
