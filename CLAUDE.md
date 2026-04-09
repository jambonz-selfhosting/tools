# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This repository contains standalone operational tools for testing and managing self-hosted jambonz deployments. jambonz is an open-source CPaaS (Communications Platform as a Service) for voice and messaging applications, built on drachtio (SIP application server) and FreeSWITCH.

## Repository Structure

Scripts in this repo are standalone with no shared dependencies. Each script should be self-contained and runnable with only Python 3 stdlib (no pip install required).

## jambonz Architecture

jambonz deployments come in several sizes:

- **mini** - All components on a single instance
- **medium** - Separate instances: SBC (sip-rtp), Feature Server (fs), Web+Monitoring (web-monitoring), Recording
- **large** - Separate instances: SBC SIP (sip), SBC RTP (rtp), Feature Server (fs), Web (web), Monitoring (monitoring), Recording

### Component Variants

| Variant | System Services | PM2 Apps | Key Ports |
|---------|----------------|----------|-----------|
| **mini** | nginx, drachtio, freeswitch, rtpengine, mysql, redis, influxdb, telegraf, heplify-server, cassandra | api-server, webapp, feature-server, sbc-call-router, sbc-sip-sidecar, sbc-rtpengine-sidecar, outbound, inbound | 80, 443, 3000, 3002, 5060, 8443, 9022 |
| **fs** | drachtio, freeswitch | feature-server | 3000, 8021, 9022 |
| **sip** | drachtio | sbc-call-router, sbc-sip-sidecar, sbc-rtpengine-sidecar, outbound, inbound | 4000, 5060, 8443, 9022 |
| **rtp** | rtpengine | sbc-rtpengine-sidecar | 22222 |
| **sip-rtp** | drachtio, rtpengine | sbc-call-router, sbc-sip-sidecar, sbc-rtpengine-sidecar, outbound, inbound | 4000, 5060, 8443, 9022, 22222 |
| **web** | nginx | api-server, webapp | 80, 443, 3002 |
| **web-monitoring** | nginx, influxdb, telegraf, grafana-server, heplify-server, cassandra | api-server, webapp | 80, 443, 3002, 3010, 9080 |
| **monitoring** | heplify-server, cassandra | (none) | 9060 |
| **recording** | upload_recordings | (none) | 3000 |

### Key Services

- **drachtio** - SIP application server (management port 9022)
- **freeswitch** - Media server (ESL port 8021)
- **rtpengine** - RTP proxy (NG API port 22222)
- **nginx** - Reverse proxy for web services
- **PM2** - Node.js process manager for all jambonz applications

### SSH Access

All jambonz instances use:
- User: `jambonz`
- PM2 apps run under the `jambonz` user
- System services run as root via systemd

## Design Principles

- Scripts must be standalone (no shared lib/ directory, no pip dependencies)
- Use Python 3 stdlib only — subprocess for SSH, json for parsing
- Support all deployment variants via command-line flags
- Exit code 0 on success, 1 on any failure
- Human-readable output with pass/fail indicators

## Related Repositories

- **packer** (sibling: `../packer/`) - Builds AMI/VM images for all variants
- **cloudformation** (sibling: `../cloudformation/`) - AWS CloudFormation templates
- **terraform** (sibling: `../terraform/`) - Terraform deployment scripts