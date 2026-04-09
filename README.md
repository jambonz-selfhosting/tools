# jambonz selfhosting tools

Standalone operational scripts for testing and managing self-hosted jambonz deployments. These tools work with any jambonz instance regardless of how it was provisioned (CloudFormation, Terraform, Packer, Docker, etc.).

## Scripts

### test-jambonz-startup.py

Verifies that a jambonz instance started up correctly by checking cloud-init completion, system services, PM2 applications, and listening ports.

**Requirements:** Python 3.6+, `ssh` on PATH. No pip dependencies.

**Usage:**

```bash
# Test a mini instance (default variant)
python test-jambonz-startup.py --host 13.36.97.68 --key ~/.ssh/my-key.pem

# Explicitly specify variant
python test-jambonz-startup.py --host 13.36.97.68 --key ~/.ssh/my-key.pem --variant mini

# Test a feature server
python test-jambonz-startup.py --host 10.0.1.5 --key ~/.ssh/my-key.pem --variant fs

# Test an SBC (combined sip+rtp)
python test-jambonz-startup.py --host 10.0.2.10 --key ~/.ssh/my-key.pem --variant sip-rtp
```

**Open-source builds:**

```bash
# Test an open-source feature server (different PM2 names, SSH user defaults to admin)
python test-jambonz-startup.py --host 18.204.245.251 --variant fs --oss
```

```
$ python test-jambonz-startup.py --host 18.204.245.251  --variant fs --oss
============================================================
jambonz fs (oss) startup test — 18.204.245.251
============================================================

--- SSH Connectivity ---
  ✅ SSH connection — ok

--- Cloud-Init ---
  ✅ cloud-init completed

--- System Services ---
  ✅ drachtio — active
  ✅ freeswitch — active

--- PM2 Services ---
  ✅ pm2: jambonz-feature-server — online

--- Ports ---
  ✅ port 3000 (feature-server)
  ✅ port 8021 (freeswitch ESL)
  ✅ port 9022 (drachtio)

============================================================
Results: 8/8 passed, 0 failed
============================================================
```

> With `--oss`, PM2 app names are remapped (e.g. `api-server` → `jambonz-api-server`, `inbound` → `sbc-inbound`) and the default SSH user is `admin` instead of `jambonz`.

**Supported variants:**

| Variant | Description |
|---------|-------------|
| `mini` | All-in-one single instance (default) |
| `fs` | Feature server (drachtio + freeswitch) |
| `sip` | SBC SIP signaling only |
| `rtp` | SBC RTP media only |
| `sip-rtp` | SBC combined SIP + RTP |
| `web` | Web UI + API server |
| `web-monitoring` | Web UI + API + monitoring stack |
| `monitoring` | Standalone monitoring server |
| `recording` | Recording server |

**Example output:**

```
$ python test-jambonz-startup.py --host 15.188.187.203 --key ~/aws/aws-jambones-eu-west-3.pem --variant mini
============================================================
jambonz mini startup test — 15.188.187.203
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
  ✅ mysql — active
  ✅ redis-server — active
  ✅ influxdb — active
  ✅ telegraf — active
  ✅ heplify-server — active
  ✅ cassandra — active

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
  ✅ port 5060 (SIP UDP/TCP)
  ❌ port 8443 (SIP WSS)
  ✅ port 9022 (drachtio)

============================================================
Results: 25/27 passed, 2 failed
============================================================
```

> Note: Ports 443 and 8443 require TLS certificates (certbot) to be configured after deployment.

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | (required) | Instance IP or hostname |
| `--key` | (required) | Path to SSH private key |
| `--user` | `jambonz` | SSH username |
| `--variant` | `mini` | Instance variant to test |
| `--oss` | off | Open-source build (different PM2 names, default user `admin`) |
| `--timeout` | `300` | Timeout in seconds for cloud-init wait |

## Related repositories

- [jambonz-selfhosting/packer](https://github.com/jambonz-selfhosting/packer) - AMI/image build scripts
- [jambonz-selfhosting/cloudformation](https://github.com/jambonz-selfhosting/cloudformation) - AWS CloudFormation templates
- [jambonz-selfhosting/terraform](https://github.com/jambonz-selfhosting/terraform) - Terraform deployment scripts