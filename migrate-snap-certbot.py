#!/usr/bin/env python3
"""
Standalone tool to clean snapd off a jambonz instance and (re)wire certbot
renewal to a standard systemd timer.

What it does:
  - Inspects the target host for snapd, snap-installed certbot, the apt
    certbot package, nginx, and existing Let's Encrypt certificates.
  - In --apply mode:
      1. Installs the apt certbot package (plus python3-certbot-nginx if
         nginx is present).
      2. Removes the certbot snap (if present) and every other snap.
      3. Stops, disables, and purges snapd; cleans up /snap, /var/snap,
         /var/lib/snapd, /var/cache/snapd, and ~/snap.
      4. Enables certbot.timer (shipped with the apt certbot package) so
         renewals run via systemd instead of snapd's timer.
      5. Runs `certbot renew --dry-run` to verify.

  /etc/letsencrypt is preserved across the migration so existing certificates
  keep working; the apt certbot binary reads the same directory the snap did.

Usage:
    python migrate-snap-certbot.py --host 13.36.97.68 --key ~/.ssh/my-key.pem
    python migrate-snap-certbot.py --host 13.36.97.68 --key ~/.ssh/my-key.pem --apply

    # Reach a private instance through an SBC jump host
    python migrate-snap-certbot.py --host 10.0.1.5 --key ~/.ssh/fs.pem \
        --jump 203.0.113.10 --jump-key ~/.ssh/sbc.pem --apply

    # Open-source build (admin user instead of jambonz)
    python migrate-snap-certbot.py --host 1.2.3.4 --key ~/.ssh/k.pem --oss --apply
"""

import argparse
import shlex
import subprocess
import sys


# Snaps that other snaps depend on. These must be removed AFTER application
# snaps, in this order: cores → bare → snapd. (`snap list` returns alphabetical
# order, so naively reversing produces the wrong sequence.)
_BASE_SNAPS_EXACT = {"bare", "snapd"}


def _is_base_snap(name):
    return name in _BASE_SNAPS_EXACT or name.startswith("core")


def snap_remove_order(snaps):
    """Return snap names in safe removal order: apps first, then base snaps."""
    apps = [s for s in snaps if not _is_base_snap(s)]
    cores = sorted(s for s in snaps if s.startswith("core"))
    bare = [s for s in snaps if s == "bare"]
    snapd_snap = [s for s in snaps if s == "snapd"]
    return apps + cores + bare + snapd_snap


def run_ssh(host, key, user, command, timeout=60,
            proxy=None, proxy_key=None, proxy_user=None):
    """Run a command over SSH, optionally through a proxy/jump host.

    Returns (stdout, exit_code). stderr is merged into stdout so callers see
    apt/snap warnings without a second channel to plumb.
    """
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", f"ConnectTimeout={min(timeout, 30)}",
        "-o", "LogLevel=ERROR",
    ]
    if proxy:
        proxy_cmd = (
            "ssh -W %h:%p"
            " -o StrictHostKeyChecking=no"
            " -o UserKnownHostsFile=/dev/null"
            " -o LogLevel=ERROR"
        )
        if proxy_key:
            proxy_cmd += f" -i {proxy_key}"
        p_user = proxy_user or user
        proxy_cmd += f" {p_user}@{proxy}"
        cmd += ["-o", f"ProxyCommand={proxy_cmd}"]
    if key:
        cmd += ["-i", key]
    cmd += [f"{user}@{host}", command]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        # Merge stderr so apt/snap noise is visible to the caller.
        out = result.stdout
        if result.stderr:
            out = (out + "\n" + result.stderr) if out else result.stderr
        return out, result.returncode
    except subprocess.TimeoutExpired:
        return "", -1


def check(label, passed, detail=""):
    icon = "✅" if passed else "❌"
    msg = f"  {icon} {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return passed


def info(label, detail=""):
    msg = f"  ℹ️  {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)


def step(label):
    print(f"  → {label}")


def run_step(ssh, label, command, timeout=180):
    """Run a remote shell step in --apply mode and report pass/fail."""
    out, rc = ssh(command, timeout)
    ok = rc == 0
    detail = ""
    if not ok:
        # Surface the first non-empty stderr/stdout line so the operator
        # knows what blew up.
        first = next((ln for ln in out.splitlines() if ln.strip()), "")
        detail = first[:120]
    check(label, ok, detail)
    return ok, out


def inventory(ssh):
    """Inspect remote state. Returns a dict of findings."""
    state = {
        "os": "",
        "snapd_installed": False,
        "snapd_active": False,
        "snap_list": [],
        "snap_certbot": False,
        "snap_certbot_timer_active": False,
        "apt_certbot": False,
        "apt_certbot_nginx": False,
        "nginx_installed": False,
        "certbot_timer_unit": False,
        "certbot_timer_active": False,
        "letsencrypt_present": False,
        "cert_domains": [],
    }

    # OS / distro family
    out, _ = ssh(". /etc/os-release 2>/dev/null && echo \"$ID $VERSION_ID\"")
    state["os"] = out.strip()

    # snapd package + service
    _, rc = ssh("dpkg -s snapd >/dev/null 2>&1")
    state["snapd_installed"] = (rc == 0)

    out, _ = ssh("systemctl is-active snapd.socket 2>/dev/null")
    state["snapd_active"] = (out.strip() == "active")

    # Installed snaps (skip header line)
    if state["snapd_installed"]:
        out, rc = ssh("snap list 2>/dev/null")
        if rc == 0:
            for line in out.splitlines()[1:]:
                parts = line.split()
                if parts:
                    state["snap_list"].append(parts[0])
        state["snap_certbot"] = "certbot" in state["snap_list"]

        out, _ = ssh("systemctl is-active snap.certbot.renew.timer 2>/dev/null")
        state["snap_certbot_timer_active"] = (out.strip() == "active")

    # apt certbot + plugin + nginx
    _, rc = ssh("dpkg -s certbot >/dev/null 2>&1")
    state["apt_certbot"] = (rc == 0)
    _, rc = ssh("dpkg -s python3-certbot-nginx >/dev/null 2>&1")
    state["apt_certbot_nginx"] = (rc == 0)
    _, rc = ssh("dpkg -s nginx >/dev/null 2>&1 || dpkg -s nginx-core >/dev/null 2>&1")
    state["nginx_installed"] = (rc == 0)

    # certbot.timer (apt-installed) unit + active state
    _, rc = ssh("systemctl cat certbot.timer >/dev/null 2>&1")
    state["certbot_timer_unit"] = (rc == 0)
    out, _ = ssh("systemctl is-active certbot.timer 2>/dev/null")
    state["certbot_timer_active"] = (out.strip() == "active")

    # /etc/letsencrypt
    _, rc = ssh("sudo test -d /etc/letsencrypt/live")
    state["letsencrypt_present"] = (rc == 0)
    if state["letsencrypt_present"]:
        out, _ = ssh("sudo ls /etc/letsencrypt/live 2>/dev/null")
        state["cert_domains"] = [
            d for d in out.split() if d and d != "README"
        ]

    return state


def print_inventory(state):
    print("\n--- Inventory ---")
    info(f"OS: {state['os'] or 'unknown'}")

    if state["snapd_installed"]:
        active = "active" if state["snapd_active"] else "inactive"
        check("snapd installed (target for removal)", False, active)
    else:
        check("snapd not installed", True)

    if state["snap_list"]:
        info(f"Installed snaps: {', '.join(state['snap_list'])}")
    if state["snap_certbot"]:
        active = "timer active" if state["snap_certbot_timer_active"] else "timer inactive"
        check("certbot installed via snap (will migrate)", False, active)

    if state["apt_certbot"]:
        bits = ["certbot"]
        if state["apt_certbot_nginx"]:
            bits.append("python3-certbot-nginx")
        check(f"apt certbot present ({', '.join(bits)})", True)
    else:
        info("apt certbot not yet installed")

    if state["nginx_installed"]:
        info("nginx detected — will install python3-certbot-nginx")

    if state["certbot_timer_unit"]:
        active = "active" if state["certbot_timer_active"] else "inactive"
        check("certbot.timer (systemd) unit present", True, active)
    else:
        info("certbot.timer not yet on disk (ships with apt certbot)")

    if state["letsencrypt_present"]:
        if state["cert_domains"]:
            info(f"/etc/letsencrypt/live: {', '.join(state['cert_domains'])}")
        else:
            info("/etc/letsencrypt/live present but empty")
    else:
        info("/etc/letsencrypt/live not present (no existing certs)")


def apply_migration(ssh, state):
    """Perform the snapd removal + certbot migration. Returns (passed, total)."""
    passed = 0
    total = 0

    def run(label, command, timeout=180):
        nonlocal passed, total
        total += 1
        ok, _ = run_step(ssh, label, command, timeout)
        if ok:
            passed += 1
        return ok

    # ---- 1. Install apt certbot first so we never lose the binary -----------
    print("\n--- Install apt certbot ---")
    pkgs = ["certbot"]
    if state["nginx_installed"]:
        pkgs.append("python3-certbot-nginx")
    pkg_list = " ".join(pkgs)
    # `apt-get update` is intentionally non-fatal: third-party repos (e.g.
    # postgresql) sometimes fail update with legacy-keyring warnings or
    # transient errors. Cached package lists are enough to install certbot
    # from the debian main repo, so don't let an unrelated repo issue
    # short-circuit the install.
    run(
        f"apt-get install -y {pkg_list}",
        "sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq || true; "
        f"sudo DEBIAN_FRONTEND=noninteractive apt-get install -y {pkg_list}",
        timeout=300,
    )

    # Verify the apt binary sees the existing cert tree. Skip this check when
    # /usr/bin/certbot is a dangling snap symlink — the post-snap-purge
    # reinstall step below will repair it; running it now would spuriously fail.
    if state["letsencrypt_present"]:
        out, _ = ssh("test -L /usr/bin/certbot && readlink /usr/bin/certbot")
        is_snap_symlink = "/snap/" in out
        if not is_snap_symlink:
            run(
                "apt certbot sees existing /etc/letsencrypt certificates",
                "sudo /usr/bin/certbot certificates >/dev/null",
            )
        else:
            info("/usr/bin/certbot is a snap symlink — will repair after purge")

    # ---- 2. Stop snap certbot timer + remove the snaps ----------------------
    if state["snapd_installed"]:
        print("\n--- Remove snaps ---")

        if state["snap_certbot_timer_active"]:
            run(
                "stop snap.certbot.renew.timer",
                "sudo systemctl stop snap.certbot.renew.timer "
                "snap.certbot.renew.service 2>/dev/null; true",
            )

        # Remove application snaps first, then base snaps (cores → bare →
        # snapd-as-snap). `snap list` is alphabetical, so the certbot+core+core24
        # case would naively reverse to [core24, core, certbot] — wrong; certbot
        # depends on core24 and core can't be removed while dependents exist.
        if state["snap_list"]:
            for snap in snap_remove_order(state["snap_list"]):
                run(
                    f"snap remove {snap}",
                    f"sudo snap remove --purge {shlex.quote(snap)}",
                    timeout=180,
                )

        # ---- 3. Stop and purge snapd ---------------------------------------
        print("\n--- Disable and remove snapd ---")

        run(
            "disable snapd systemd units",
            "sudo systemctl disable --now "
            "snapd.socket snapd.service snapd.seeded.service "
            "snapd.apparmor.service 2>/dev/null; "
            "sudo systemctl mask snapd.service snapd.socket 2>/dev/null; true",
        )

        # Unmount any lingering squashfs snap mounts before purge.
        run(
            "unmount leftover /snap mounts",
            "for m in $(mount | awk '/ \\/snap\\// {print $3}' | sort -r); do "
            "  sudo umount -l \"$m\" 2>/dev/null || true; "
            "done; true",
        )

        run(
            "apt purge snapd",
            "sudo DEBIAN_FRONTEND=noninteractive apt-get purge -y snapd && "
            "sudo DEBIAN_FRONTEND=noninteractive apt-get autoremove -y --purge",
            timeout=300,
        )

        # Block snapd from being pulled back in by future apt installs of
        # transitional packages.
        run(
            "pin snapd to never reinstall (apt preferences)",
            "echo -e 'Package: snapd\\nPin: release a=*\\nPin-Priority: -10' | "
            "sudo tee /etc/apt/preferences.d/no-snapd >/dev/null",
        )

        run(
            "clean up /snap, /var/snap, /var/lib/snapd, ~/snap",
            "sudo rm -rf /snap /var/snap /var/lib/snapd /var/cache/snapd "
            "/root/snap ~/snap 2>/dev/null; true",
        )

        # ---- 3b. Repair /usr/bin/certbot ------------------------------------
        # The Let's Encrypt snap install instructions tell users to run
        # `ln -s /snap/bin/certbot /usr/bin/certbot`. That symlink shadows the
        # apt package's real binary; after `apt purge snapd` removes /snap,
        # the symlink dangles and `which certbot` returns nothing — even
        # though dpkg still reports the certbot package as installed.
        #
        # Drop the dangling symlink and force a reinstall so /usr/bin/certbot
        # is repopulated from the deb.
        print("\n--- Repair /usr/bin/certbot ---")
        run(
            "remove dangling /usr/bin/certbot symlink (if any)",
            "if [ -L /usr/bin/certbot ]; then sudo rm -f /usr/bin/certbot; fi; true",
        )
        run(
            f"apt-get install --reinstall -y {pkg_list}",
            f"sudo DEBIAN_FRONTEND=noninteractive apt-get install --reinstall -y {pkg_list}",
            timeout=300,
        )
        run(
            "/usr/bin/certbot is executable",
            "test -x /usr/bin/certbot && ! test -L /usr/bin/certbot",
        )

    # ---- 4. Enable certbot.timer (apt) -------------------------------------
    print("\n--- Configure certbot.timer (systemd) ---")
    run(
        "daemon-reload",
        "sudo systemctl daemon-reload",
    )

    # The apt certbot package ships /lib/systemd/system/certbot.timer with a
    # twice-daily schedule and randomized 12h delay — exactly what the snap's
    # timer did. Just enable it.
    run(
        "enable certbot.timer",
        "sudo systemctl enable --now certbot.timer",
    )

    out, _ = ssh("systemctl is-active certbot.timer 2>/dev/null")
    total += 1
    if check("certbot.timer is active", out.strip() == "active", out.strip()):
        passed += 1

    # ---- 5. Verification dry-run -------------------------------------------
    if state["letsencrypt_present"] and state["cert_domains"]:
        print("\n--- Verify renewal ---")
        # `certbot certificates` reads /etc/letsencrypt/renewal/*.conf, so it's
        # the canonical answer to "does certbot know how to renew anything?"
        out, _ = ssh("sudo /usr/bin/certbot certificates 2>&1")
        knows_certs = "No certificates found." not in out
        if knows_certs:
            run(
                "certbot renew --dry-run",
                "sudo /usr/bin/certbot renew --dry-run --no-random-sleep-on-renew",
                timeout=300,
            )
        else:
            # /etc/letsencrypt/live has cert files but /etc/letsencrypt/renewal
            # has no configs for them. The systemd timer will fire but won't
            # renew anything — operator needs to re-issue the cert (e.g.
            # `certbot --nginx -d <domain>`) to create a renewal config.
            info("certbot finds no renewable certs — /etc/letsencrypt/renewal "
                 "is missing configs for the certs in /etc/letsencrypt/live "
                 f"({', '.join(state['cert_domains'])}). Re-issue with "
                 "`certbot --nginx -d <domain>` to create a renewal config.")

    return passed, total


def main():
    parser = argparse.ArgumentParser(
        description="Remove snapd and migrate certbot to a systemd timer on a jambonz host.",
    )
    parser.add_argument("--host", required=True, help="Instance IP or hostname")
    parser.add_argument("--key", help="Path to SSH private key (omit to use default SSH agent)")
    parser.add_argument("--user", help="SSH user (default: jambonz, or admin with --oss)")
    parser.add_argument("--oss", action="store_true",
                        help="Open-source build (SSH user defaults to admin)")
    parser.add_argument("--jump",
                        help="SSH jump host (e.g. SBC public IP) to tunnel through")
    parser.add_argument("--jump-user",
                        help="SSH user for jump host (default: same as --user)")
    parser.add_argument("--jump-key",
                        help="SSH key for jump host (default: same as --key)")
    parser.add_argument("--apply", action="store_true",
                        help="Actually perform the migration. Without this flag the "
                             "tool runs in inventory-only (dry-run) mode.")
    args = parser.parse_args()

    if args.user is None:
        args.user = "admin" if args.oss else "jambonz"

    ssh = lambda cmd, t=60: run_ssh(
        args.host, args.key, args.user, cmd, t,
        proxy=args.jump,
        proxy_key=args.jump_key,
        proxy_user=args.jump_user,
    )

    print("=" * 60)
    mode = "APPLY" if args.apply else "inventory (dry-run)"
    print(f"snapd → systemd certbot migration [{mode}] — {args.host}")
    if args.jump:
        print(f"  (proxying through {args.jump})")
    print("=" * 60)

    # 1. SSH connectivity
    print("\n--- SSH Connectivity ---")
    out, rc = ssh("echo ok")
    if not check("SSH connection", rc == 0, out.strip() if rc == 0 else "unreachable"):
        print("\nCannot connect via SSH. Aborting.")
        sys.exit(1)

    # 2. Inventory
    state = inventory(ssh)
    print_inventory(state)

    # 3. Decide whether action is needed
    snap_certbot_migration = state["snap_certbot"]
    snapd_cleanup = state["snapd_installed"]
    needs_action = snapd_cleanup or snap_certbot_migration or (
        state["letsencrypt_present"] and not state["certbot_timer_active"]
    )

    if not needs_action:
        print("\n✅ Host is already clean — no snapd, no snap certbot, "
              "and certbot.timer (or no certs) is in the correct state.")
        sys.exit(0)

    print("\n--- Planned actions ---")
    if not state["apt_certbot"]:
        pkg = "certbot + python3-certbot-nginx" if state["nginx_installed"] else "certbot"
        step(f"apt install {pkg}")
    if state["snap_certbot"]:
        step("stop snap.certbot.renew.timer")
    for snap in snap_remove_order(state["snap_list"]):
        step(f"snap remove --purge {snap}")
    if state["snapd_installed"]:
        step("systemctl disable --now snapd.{socket,service,seeded.service}")
        step("apt-get purge -y snapd && autoremove")
        step("pin snapd via /etc/apt/preferences.d/no-snapd")
        step("rm -rf /snap /var/snap /var/lib/snapd /var/cache/snapd ~/snap")
        step("apt-get install --reinstall certbot (repair /usr/bin/certbot)")
    if not state["certbot_timer_active"]:
        step("systemctl enable --now certbot.timer")
    if state["letsencrypt_present"] and state["cert_domains"]:
        step("certbot renew --dry-run (verification)")

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to execute these steps.")
        sys.exit(0)

    # 4. Execute
    passed, total = apply_migration(ssh, state)

    # 5. Post-state summary
    print("\n--- Post-migration state ---")
    post = inventory(ssh)
    check("snapd removed", not post["snapd_installed"],
          "still installed" if post["snapd_installed"] else "")
    check("no snaps remain", not post["snap_list"],
          ", ".join(post["snap_list"]) if post["snap_list"] else "")
    check("apt certbot installed", post["apt_certbot"])
    check("certbot.timer active", post["certbot_timer_active"],
          "inactive" if not post["certbot_timer_active"] else "")
    if state["letsencrypt_present"]:
        check("certificates preserved", post["letsencrypt_present"] and
              set(post["cert_domains"]) == set(state["cert_domains"]),
              ", ".join(post["cert_domains"]))

    failed = total - passed
    print("\n" + "=" * 60)
    print(f"Results: {passed}/{total} steps succeeded, {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
