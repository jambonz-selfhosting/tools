#!/usr/bin/env python3
"""
Standalone test for jambonz mini instance startup verification.

Tests that cloud-init completed, system services are running,
jambonz apps are online (PM2 or systemd), and key ports are listening.

This script is designed and tested for jambonz mini deployments.
Other variants (fs, sip-rtp, etc.) are included for convenience but
may require adjustments for specific deployment configurations.

Usage:
    # Test a mini instance (AMI/packer build with PM2)
    python test-jambonz-startup.py --host 13.36.97.68 --key ~/.ssh/my-key.pem

    # Test a mini instance (Debian package install with systemd)
    python test-jambonz-startup.py --host 13.36.97.68 --package

    # Using default SSH key (from ssh-agent or ~/.ssh/id_rsa)
    python test-jambonz-startup.py --host 13.36.97.68

    # Test an open-source mini build (different app names)
    python test-jambonz-startup.py --host 13.36.97.68 --oss

Requirements:
    - Python 3.6+
    - SSH access to the target instance
    - The jambonz user must exist on the target (or admin user with --oss)
"""

import argparse
import subprocess
import sys
import json

# Map from commercial PM2 app names to open-source equivalents
OSS_PM2_NAMES = {
    "api-server": "jambonz-api-server",
    "webapp": "jambonz-webapp",
    "feature-server": "jambonz-feature-server",
    "inbound": "sbc-inbound",
    "outbound": "sbc-outbound",
}

# Per-variant definitions for AMI/packer builds (PM2-based)
# Note: The 'mini' variant is the primary tested configuration.
VARIANTS = {
    "mini": {
        "services": [
            "nginx", "drachtio", "freeswitch", "rtpengine",
            "mariadb", "redis-server", "influxdb", "telegraf",
            "grafana-server", "heplify-server", "pcap-server",
            "cassandra", "jaeger-collector", "jaeger-query",
        ],
        "pm2": [
            "api-server", "webapp", "feature-server",
            "sbc-call-router", "sbc-sip-sidecar", "sbc-rtpengine-sidecar",
            "outbound", "inbound",
        ],
        "ports": [
            (80, "nginx HTTP"),
            (443, "nginx HTTPS"),
            (3002, "api-server"),
            (3000, "feature-server"),
            (4000, "sbc-call-router"),
            (5060, "SIP UDP/TCP"),
            (8443, "SIP WSS"),
            (9022, "drachtio"),
        ],
    },
    "fs": {
        "services": ["drachtio", "freeswitch", "telegraf"],
        "pm2": ["feature-server"],
        "ports": [
            (3000, "feature-server"),
            (8021, "freeswitch ESL"),
            (9022, "drachtio"),
        ],
    },
    "sip": {
        "services": ["drachtio", "telegraf"],
        "pm2": [
            "sbc-call-router", "sbc-sip-sidecar",
            "outbound", "inbound",
        ],
        "ports": [
            (5060, "SIP UDP/TCP"),
            (8443, "SIP WSS"),
            (9022, "drachtio"),
            (4000, "sbc-call-router"),
        ],
    },
    "rtp": {
        "services": ["rtpengine", "telegraf"],
        "pm2": ["sbc-rtpengine-sidecar"],
        "ports": [],
    },
    "sip-rtp": {
        "services": ["drachtio", "rtpengine", "telegraf"],
        "pm2": [
            "sbc-call-router", "sbc-sip-sidecar", "sbc-rtpengine-sidecar",
            "outbound", "inbound",
        ],
        "ports": [
            (5060, "SIP UDP/TCP"),
            (8443, "SIP WSS"),
            (9022, "drachtio"),
            (4000, "sbc-call-router"),
        ],
    },
    "web": {
        "services": ["nginx", "telegraf"],
        "pm2": ["api-server", "webapp"],
        "ports": [
            (80, "nginx HTTP"),
            (443, "nginx HTTPS"),
            (3002, "api-server"),
        ],
    },
    "web-monitoring": {
        "services": [
            "nginx", "influxdb", "telegraf", "grafana-server",
            "heplify-server", "pcap-server", "cassandra",
            "jaeger-collector", "jaeger-query",
        ],
        "pm2": ["api-server", "webapp"],
        "ports": [
            (80, "nginx HTTP"),
            (443, "nginx HTTPS"),
            (3002, "api-server"),
            (9080, "homer"),
        ],
    },
    "monitoring": {
        "services": [
            "influxdb", "telegraf", "grafana-server",
            "heplify-server", "pcap-server", "cassandra",
            "jaeger-collector", "jaeger-query",
        ],
        "pm2": [],
        "ports": [
            (9060, "heplify HEP"),
            (9080, "homer"),
        ],
    },
    "recording": {
        "services": ["telegraf"],
        "pm2": ["upload-recordings"],
        "ports": [
            (3000, "upload-recordings"),
        ],
    },
}

# Debian package installs use systemd services instead of PM2
# These are the jambonz app services (in addition to base services)
PACKAGE_JAMBONZ_SERVICES = {
    "mini": [
        "jambonz-api-server", "jambonz-feature-server",
        "jambonz-sbc-call-router", "jambonz-sbc-sip-sidecar",
        "jambonz-sbc-rtpengine-sidecar", "jambonz-inbound", "jambonz-outbound",
    ],
}

# Service name overrides for package installs
PACKAGE_SERVICE_OVERRIDES = {
    "drachtio": "drachtio-5070",  # Package uses drachtio-5070, not drachtio
}


def run_ssh(host, key, user, command, timeout=30):
    """Run a command over SSH. Returns (stdout, exit_code)."""
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", f"ConnectTimeout={timeout}",
        "-o", "LogLevel=ERROR",
    ]
    if key:
        cmd += ["-i", key]
    cmd += [f"{user}@{host}", command]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout, result.returncode
    except subprocess.TimeoutExpired:
        return "", -1


def check(label, passed, detail=""):
    """Print a check result."""
    icon = "✅" if passed else "❌"
    msg = f"  {icon} {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return passed


def main():
    parser = argparse.ArgumentParser(
        description="Test jambonz mini instance startup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --host 13.36.97.68 --key ~/.ssh/my-key.pem
  %(prog)s --host 13.36.97.68                          # use default SSH key
  %(prog)s --host 13.36.97.68 --package                # Debian package install
  %(prog)s --host 13.36.97.68 --oss                    # open-source build
  %(prog)s --host 10.0.1.5 --variant fs                # feature server
        """
    )
    parser.add_argument("--host", required=True, help="Instance IP or hostname")
    parser.add_argument("--key", help="Path to SSH private key (omit to use default)")
    parser.add_argument("--user", help="SSH user (default: jambonz, or admin with --oss)")
    parser.add_argument("--variant", default="mini",
                        choices=list(VARIANTS.keys()),
                        help="Instance variant (default: mini)")
    parser.add_argument("--oss", action="store_true",
                        help="Open-source build (different app names)")
    parser.add_argument("--package", action="store_true",
                        help="Debian package install (apps run as systemd, not PM2)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Timeout for cloud-init wait in seconds (default: 300)")
    args = parser.parse_args()

    if args.user is None:
        args.user = "admin" if args.oss else "jambonz"

    variant = VARIANTS[args.variant]

    # Build the services list
    services = list(variant["services"])

    # Apply package-specific overrides
    if args.package:
        services = [PACKAGE_SERVICE_OVERRIDES.get(s, s) for s in services]
        # Add jambonz app services (they run as systemd instead of PM2)
        if args.variant in PACKAGE_JAMBONZ_SERVICES:
            services.extend(PACKAGE_JAMBONZ_SERVICES[args.variant])

    # Remap PM2 names for open-source builds
    pm2_apps = list(variant["pm2"])
    if args.oss:
        pm2_apps = [OSS_PM2_NAMES.get(name, name) for name in pm2_apps]

    passed = 0
    failed = 0
    total = 0

    def tally(label, ok, detail=""):
        nonlocal passed, failed, total
        total += 1
        if check(label, ok, detail):
            passed += 1
        else:
            failed += 1

    ssh = lambda cmd, t=30: run_ssh(args.host, args.key, args.user, cmd, t)

    print("=" * 60)
    edition = "oss" if args.oss else "commercial"
    install_type = "package" if args.package else "AMI"
    print(f"jambonz {args.variant} ({edition}, {install_type}) — {args.host}")
    print("=" * 60)

    # 1. SSH connectivity
    print("\n--- SSH Connectivity ---")
    out, rc = ssh("echo ok")
    tally("SSH connection", rc == 0, out.strip() if rc == 0 else "unreachable")
    if rc != 0:
        print("\nCannot connect via SSH. Aborting.")
        sys.exit(1)

    # 2. Cloud-init
    print("\n--- Cloud-Init ---")
    out, rc = ssh("cloud-init status --wait 2>/dev/null || echo 'no cloud-init'", args.timeout)
    if "status: done" in out.lower():
        tally("cloud-init completed", True)
    elif "no cloud-init" in out:
        tally("cloud-init completed", True, "cloud-init not present (bare metal?)")
    else:
        tally("cloud-init completed", False, out.strip()[:80])

    # 3. System services
    if services:
        print("\n--- System Services ---")
        for svc in services:
            out, rc = ssh(f"systemctl is-active {svc} 2>/dev/null")
            status = out.strip()
            tally(svc, status == "active", status)

    # 4. PM2 services (only for AMI/packer builds, not package installs)
    if pm2_apps and not args.package:
        print("\n--- PM2 Services ---")
        out, rc = ssh("pm2 jlist 2>/dev/null")
        if rc == 0:
            try:
                pm2_data = json.loads(out)
                pm2_status = {p["name"]: p.get("pm2_env", {}).get("status", "unknown")
                              for p in pm2_data}
            except (json.JSONDecodeError, KeyError):
                pm2_status = {}

            for svc in pm2_apps:
                status = pm2_status.get(svc, "not found")
                tally(f"pm2: {svc}", status == "online", status)
        else:
            tally("pm2 accessible", False, "pm2 jlist failed")

    # 5. Key ports listening
    if variant["ports"]:
        print("\n--- Ports ---")
        out, rc = ssh("sudo ss -tlnp 2>/dev/null || sudo netstat -tlnp 2>/dev/null")
        for port, label in variant["ports"]:
            listening = f":{port} " in out or f":{port}\t" in out
            tally(f"port {port} ({label})", listening)

    # Summary
    print("\n" + "=" * 60)
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
