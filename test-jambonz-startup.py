#!/usr/bin/env python3
"""
Standalone test for jambonz instance startup verification.

Tests that cloud-init completed, system services are running,
PM2 apps are online, and key ports are listening.

Usage:
    # Test a mini (default)
    python test-mini.py --host 13.36.97.68 --key ~/.ssh/my-key.pem

    # Test a feature server
    python test-mini.py --host 10.0.1.5 --key ~/.ssh/my-key.pem --variant fs

    # Test an SBC (combined sip+rtp)
    python test-mini.py --host 10.0.2.10 --key ~/.ssh/my-key.pem --variant sip-rtp

    # All variants: mini, fs, sip, rtp, sip-rtp, web, web-monitoring, monitoring, recording
"""

import argparse
import subprocess
import sys
import json

# Per-variant definitions: system services, PM2 apps, listening ports
VARIANTS = {
    "mini": {
        "services": [
            "nginx", "drachtio", "freeswitch", "rtpengine",
            "mysql", "redis-server", "influxdb", "telegraf",
            "heplify-server", "cassandra",
            "jaeger-collector", "jaeger-query",
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
            (5060, "SIP UDP/TCP"),
            (8443, "SIP WSS"),
            (9022, "drachtio"),
        ],
    },
    "fs": {
        "services": ["drachtio", "freeswitch"],
        "pm2": ["feature-server"],
        "ports": [
            (3000, "feature-server"),
            (8021, "freeswitch ESL"),
            (9022, "drachtio"),
        ],
    },
    "sip": {
        "services": ["drachtio"],
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
    "rtp": {
        "services": ["rtpengine"],
        "pm2": ["sbc-rtpengine-sidecar"],
        "ports": [
            (22222, "rtpengine"),
        ],
    },
    "sip-rtp": {
        "services": ["drachtio", "rtpengine"],
        "pm2": [
            "sbc-call-router", "sbc-sip-sidecar", "sbc-rtpengine-sidecar",
            "outbound", "inbound",
        ],
        "ports": [
            (5060, "SIP UDP/TCP"),
            (8443, "SIP WSS"),
            (9022, "drachtio"),
            (22222, "rtpengine"),
            (4000, "sbc-call-router"),
        ],
    },
    "web": {
        "services": ["nginx"],
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
            "heplify-server", "cassandra",
            "jaeger-collector", "jaeger-query",
        ],
        "pm2": ["api-server", "webapp"],
        "ports": [
            (80, "nginx HTTP"),
            (443, "nginx HTTPS"),
            (3002, "api-server"),
            (3010, "grafana"),
            (9080, "homer"),
        ],
    },
    "monitoring": {
        "services": ["heplify-server", "cassandra", "jaeger-collector", "jaeger-query"],
        "pm2": [],
        "ports": [
            (9060, "heplify HEP"),
        ],
    },
    "recording": {
        "services": ["upload_recordings"],
        "pm2": [],
        "ports": [
            (3000, "upload_recordings"),
        ],
    },
}


def run_ssh(host, key, user, command, timeout=30):
    """Run a command over SSH. Returns (stdout, exit_code)."""
    cmd = [
        "ssh",
        "-i", key,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", f"ConnectTimeout={timeout}",
        "-o", "LogLevel=ERROR",
        f"{user}@{host}",
        command
    ]
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
    parser = argparse.ArgumentParser(description="Test jambonz instance startup")
    parser.add_argument("--host", required=True, help="Instance IP or hostname")
    parser.add_argument("--key", required=True, help="Path to SSH private key")
    parser.add_argument("--user", default="jambonz", help="SSH user (default: jambonz)")
    parser.add_argument("--variant", default="mini",
                        choices=list(VARIANTS.keys()),
                        help="Instance variant (default: mini)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Timeout for cloud-init wait (default: 300)")
    args = parser.parse_args()

    variant = VARIANTS[args.variant]
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
    print(f"jambonz {args.variant} startup test — {args.host}")
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
        tally("cloud-init completed", False, "cloud-init not available")
    else:
        tally("cloud-init completed", False, out.strip()[:80])

    # 3. System services
    if variant["services"]:
        print("\n--- System Services ---")
        for svc in variant["services"]:
            out, rc = ssh(f"systemctl is-active {svc} 2>/dev/null")
            status = out.strip()
            tally(svc, status == "active", status)

    # 4. PM2 services
    if variant["pm2"]:
        print("\n--- PM2 Services ---")
        out, rc = ssh("pm2 jlist 2>/dev/null")
        if rc == 0:
            try:
                pm2_data = json.loads(out)
                pm2_status = {p["name"]: p.get("pm2_env", {}).get("status", "unknown")
                              for p in pm2_data}
            except (json.JSONDecodeError, KeyError):
                pm2_status = {}

            for svc in variant["pm2"]:
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
