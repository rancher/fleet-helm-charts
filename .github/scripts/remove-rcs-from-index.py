#!/usr/bin/env python3
"""
Cleanup old RC/beta/alpha versions from Helm chart index.yaml.

- Removes all dev versions when final version exists (e.g., removes 1.2.3-rc1 if 1.2.3 exists)
- Removes dev versions older than 2 weeks for unreleased versions
- Keeps latest dev version if no final version exists (prevents chart disappearing)

Requires: ruamel.yaml
"""
from ruamel.yaml import YAML
import re
from datetime import datetime, timedelta

yaml = YAML()
yaml.preserve_quotes = True
yaml.width = 4096
yaml.map_indent = 2
yaml.sequence_indent = 2
yaml.sequence_dash_offset = 0
yaml.default_flow_style = False
yaml.sort_keys = False

with open('index.yaml', 'r') as file:
    data = yaml.load(file)

AGE_LIMIT = timedelta(weeks=2)
DEV_VERSION_PATTERN = re.compile(r"(rc|beta|alpha)")

def extract_base_version(version_string):
    """Extract base version (e.g., '1.2.3' from '1.2.3-rc1')"""
    match = re.match(r'^(\d+\.\d+\.\d+)', version_string)
    return match.group(1) if match else version_string

def is_dev_version(version):
    return bool(DEV_VERSION_PATTERN.search(version.get('version', '') + version.get('appVersion', '')))

def parse_created_date(version):
    created = version.get('created')
    return datetime.strptime(created[:created.index('.') + 7] + 'Z', "%Y-%m-%dT%H:%M:%S.%fZ")

def is_old(version, cutoff_date):
    return parse_created_date(version) < cutoff_date

cutoff_date = datetime.now() - AGE_LIMIT

for chart in list(data['entries']):
    versions = data['entries'][chart]

    final_versions = [v for v in versions if not is_dev_version(v)]
    dev_versions = [v for v in versions if is_dev_version(v)]

    if final_versions:
        final_base_versions = {extract_base_version(v.get('version', '')) for v in final_versions}
        kept_versions = [
            v for v in versions
            if not is_dev_version(v) or (
                extract_base_version(v.get('version', '')) not in final_base_versions
                and not is_old(v, cutoff_date)
            )
        ]
    else:
        recent_dev = [v for v in dev_versions if not is_old(v, cutoff_date)]
        old_dev = [v for v in dev_versions if is_old(v, cutoff_date)]

        if old_dev:
            latest_old_dev = max(old_dev, key=parse_created_date)
            kept_versions = [v for v in versions if v in recent_dev or v == latest_old_dev]
        else:
            kept_versions = recent_dev

    for v in versions:
        if v not in kept_versions:
            print(f"Removing {chart} {v.get('version')}")

    data['entries'][chart] = kept_versions

    if not data['entries'][chart]:
        del data['entries'][chart]

with open('index.yaml', 'w') as file:
    yaml.dump(data, file)