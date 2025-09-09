#!/usr/bin/env python3

import sys
import yaml
from importlib.metadata import version

def main():
    """Check if the version in Chart.yaml matches titiler-eopf package version"""
    # Get version using importlib.metadata (PEP 566)
    pkg_version = version("titiler-eopf")
    
    # Read Chart.yaml
    with open("helm/charts/Chart.yaml", "r") as f:
        chart = yaml.safe_load(f)
    
    app_version = chart.get("appVersion", "").strip('"')
    
    if pkg_version != app_version:
        print(f"❌ Version mismatch: package={pkg_version}, Chart.yaml appVersion={app_version}")
        sys.exit(1)
    
    print(f"✅ Version match: {pkg_version}")
    sys.exit(0)

if __name__ == "__main__":
    main()
