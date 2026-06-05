# jambonz mini startup test

A standalone script to verify that a jambonz **mini** instance started up correctly. Checks cloud-init completion, system services, application processes, and listening ports.

> **Note:** This tool is designed and tested for jambonz mini deployments. Other variants are included for convenience but may need adjustments.

## Quick Start

```bash
# Download the script
curl -O https://raw.githubusercontent.com/jambonz-selfhosting/tools/main/test-jambonz-startup.py

# Test a mini instance (AMI/packer build)
python test-jambonz-startup.py --host 13.36.97.68 --key ~/.ssh/my-key.pem

# Test a mini instance (Debian package install)
python test-jambonz-startup.py --host 13.36.97.68 --key ~/.ssh/my-key.pem --package
```

**Requirements:** Python 3.6+, SSH access to the instance. No pip dependencies.

## Usage

### AMI/Packer Builds (PM2-based)

For instances built with packer AMIs or cloud images, jambonz apps run under PM2:

```bash
python test-jambonz-startup.py --host <IP> --key ~/.ssh/my-key.pem
```

### Debian Package Installs (systemd-based)

For instances using the `jambonz-mini` Debian package, apps run as systemd services:

```bash
python test-jambonz-startup.py --host <IP> --key ~/.ssh/my-key.pem --package
```

### Open-Source Builds

Open-source builds use different app names and the `admin` user:

```bash
python test-jambonz-startup.py --host <IP> --key ~/.ssh/my-key.pem --oss
```

## Example Output

```
$ python test-jambonz-startup.py --host 15.188.187.203 --key ~/.ssh/my-key.pem
============================================================
jambonz mini (commercial, AMI) — 15.188.187.203
============================================================

--- SSH Connectivity ---
  ✅ SSH connection — ok

--- Cloud-Init ---
  ✅ cloud-init completed

--- System Services ---
  ✅ nginx — active
  ✅ drachtio — active
  ✅ freeswitch — active
  ✅ rtpengine — active
  ✅ mariadb — active
  ✅ redis-server — active
  ✅ influxdb — active
  ✅ telegraf — active
  ✅ grafana-server — active
  ✅ heplify-server — active
  ✅ pcap-server — active
  ✅ cassandra — active
  ✅ jaeger-collector — active
  ✅ jaeger-query — active

--- PM2 Services ---
  ✅ pm2: api-server — online
  ✅ pm2: webapp — online
  ✅ pm2: feature-server — online
  ✅ pm2: sbc-call-router — online
  ✅ pm2: sbc-sip-sidecar — online
  ✅ pm2: sbc-rtpengine-sidecar — online
  ✅ pm2: outbound — online
  ✅ pm2: inbound — online

--- Ports ---
  ✅ port 80 (nginx HTTP)
  ❌ port 443 (nginx HTTPS)
  ✅ port 3002 (api-server)
  ✅ port 3000 (feature-server)
  ✅ port 4000 (sbc-call-router)
  ✅ port 5060 (SIP UDP/TCP)
  ❌ port 8443 (SIP WSS)
  ✅ port 9022 (drachtio)

============================================================
Results: 28/30 passed, 2 failed
============================================================
```

> **Note:** Ports 443 and 8443 require TLS certificates to be configured after deployment.

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | (required) | Instance IP or hostname |
| `--key` | (optional) | Path to SSH private key (uses default if omitted) |
| `--user` | `jambonz` | SSH username (`admin` with `--oss`) |
| `--variant` | `mini` | Instance variant (see below) |
| `--package` | off | Debian package install (apps run as systemd) |
| `--oss` | off | Open-source build (different app names) |
| `--timeout` | `300` | Timeout in seconds for cloud-init wait |

## Other Variants

While this tool focuses on mini, these variants are available for convenience:

| Variant | Description |
|---------|-------------|
| `mini` | All-in-one single instance (**primary, tested**) |
| `fs` | Feature server (drachtio + freeswitch) |
| `sip` | SBC SIP signaling only |
| `rtp` | SBC RTP media only |
| `sip-rtp` | SBC combined SIP + RTP |
| `web` | Web UI + API server |
| `web-monitoring` | Web UI + API + monitoring stack |
| `monitoring` | Standalone monitoring server |
| `recording` | Recording server |

```bash
# Test a feature server
python test-jambonz-startup.py --host 10.0.1.5 --key ~/.ssh/my-key.pem --variant fs
```

## Other Tools

### migrate-snap-certbot.py

Migrates certbot from snap to apt installation (for older AMIs that used snap).

## Related Repositories

- [jambonz-selfhosting/packer](https://github.com/jambonz-selfhosting/packer) - AMI/image build scripts
- [jambonz-selfhosting/cloudformation](https://github.com/jambonz-selfhosting/cloudformation) - AWS CloudFormation templates
- [jambonz-selfhosting/terraform](https://github.com/jambonz-selfhosting/terraform) - Terraform deployment scripts
