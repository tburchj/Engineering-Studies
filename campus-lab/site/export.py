"""Export the design and the Batfish verification results as data for the site.

The page is not a drawing of the network. Every node, link, VLAN row and policy
cell it renders comes from this file, which reads the same model the configs are
generated from and asks Batfish the same questions the test suite asks — so the
published page cannot show a topology or a policy the design does not actually have.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pybatfish.client.session import Session
from pybatfish.datamodel.flow import (
    DeliveredStepDetail,
    EnterInputIfaceStepDetail,
    ExitOutputIfaceStepDetail,
    FilterStepDetail,
    HeaderConstraints,
    RoutingStepDetail,
    Step,
)

LAB = Path(__file__).resolve().parents[1]
DESIGN = LAB / "design"
BUILD = LAB / "build"

ROLES = {
    "acc01": ("access", "Catalyst 9300"),
    "acc02": ("access", "Catalyst 9300"),
    "dist01": ("distribution", "Catalyst 9500"),
    "dist02": ("distribution", "Catalyst 9500"),
    "core01": ("core", "Catalyst 8300"),
}

LAYOUT = {
    "core01": (400, 60),
    "dist01": (230, 220),
    "dist02": (570, 220),
    "acc01": (230, 390),
    "acc02": (570, 390),
}

WORKSTATION = ("10.10.10.50", 10, "Workstation")
BIOMED = ("10.10.20.50", 20, "Biomed device")
GUEST = ("10.10.30.50", 30, "Guest wireless")

DESTINATIONS = [
    ("Data centre", "10.20.0.10", "443"),
    ("Internet", "8.8.8.8", "443"),
    ("Workstation", "10.10.10.50", "445"),
    ("Biomed device", "10.10.20.50", "443"),
    ("Switch mgmt", "10.10.99.2", "22"),
]

# Intent for cross-segment flows only. A host talking to its own segment never reaches
# the SVI the policy is applied to, so tracing it would answer a question the ACL was
# never asked and report a "failure" the design does not have.
INTENT = {
    ("Workstation", "Data centre"): True,
    ("Workstation", "Internet"): True,
    ("Workstation", "Biomed device"): False,
    ("Workstation", "Switch mgmt"): False,
    ("Biomed device", "Data centre"): True,
    ("Biomed device", "Internet"): False,
    ("Biomed device", "Workstation"): False,
    ("Biomed device", "Switch mgmt"): False,
    ("Guest wireless", "Data centre"): False,
    ("Guest wireless", "Internet"): True,
    ("Guest wireless", "Workstation"): False,
    ("Guest wireless", "Biomed device"): False,
    ("Guest wireless", "Switch mgmt"): False,
}

DELIVERED = {"ACCEPTED", "DELIVERED_TO_SUBNET", "EXITS_NETWORK"}


def load_model() -> tuple[dict, dict]:
    common = yaml.safe_load((DESIGN / "group_vars" / "all.yml").read_text())
    hosts = {
        name: yaml.safe_load((DESIGN / "host_vars" / f"{name}.yml").read_text())
        for name in ROLES
    }
    return common, hosts


def design_digest(common: dict, hosts: dict) -> str:
    """SHA-256 of the normalised model, not of the files: whitespace and key order
    do not change a design, and an approval bound to this digest is an approval of
    exactly these values."""
    canonical = json.dumps({"common": common, "hosts": hosts}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def build_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted((BUILD / "configs").glob("*.cfg")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def commit_sha() -> str:
    if sha := os.environ.get("GITHUB_SHA"):
        return sha
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=LAB, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def provenance(common: dict, hosts: dict, test_count: int) -> dict:
    return {
        "design_sha256": design_digest(common, hosts),
        "build_sha256": build_digest(),
        "commit": commit_sha(),
        "verified_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "tests": test_count,
    }


def count_tests() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "verify", "--collect-only", "-q"],
        cwd=LAB,
        capture_output=True,
        text=True,
        check=True,
    )
    return sum(1 for line in result.stdout.splitlines() if "::" in line)


def build_links(hosts: dict) -> list[dict]:
    links: list[dict] = []
    seen: set[frozenset[str]] = set()
    for name, facts in hosts.items():
        groups = [
            ("uplink", facts.get("uplinks", [])),
            ("downlink", facts.get("downlinks", [])),
            ("routed", facts.get("routed_links", [])),
            ("peer", [facts["peer_link"]] if "peer_link" in facts else []),
        ]
        for kind, entries in groups:
            for entry in entries:
                key = frozenset(
                    {f"{name}:{entry['interface']}", f"{entry['peer']}:{entry['peer_interface']}"}
                )
                if key in seen:
                    continue
                seen.add(key)
                links.append(
                    {
                        "a": name,
                        "a_interface": entry["interface"],
                        "b": entry["peer"],
                        "b_interface": entry["peer_interface"],
                        "kind": "routed" if kind in {"routed", "peer"} else "trunk",
                        "detail": (
                            f"routed /{entry['prefix_length']} point to point, OSPF area 0"
                            if "address" in entry
                            else "802.1Q trunk"
                        ),
                    }
                )
    return links


def device_entries(common: dict, hosts: dict) -> list[dict]:
    devices = []
    for name, (role, platform) in ROLES.items():
        facts = hosts[name]
        x, y = LAYOUT[name]
        roles_by_vlan = []
        for vlan in common["vlans"]:
            if role != "distribution":
                continue
            active = vlan["primary"] == name
            roles_by_vlan.append(
                {
                    "vlan": vlan["id"],
                    "name": vlan["name"],
                    "hsrp": "active" if active else "standby",
                    "stp": "root" if vlan["id"] in facts.get("stp_root_vlans", []) else "secondary",
                    "address": facts.get("svi_addresses", {}).get(vlan["id"]),
                }
            )
        devices.append(
            {
                "name": name,
                "role": role,
                "platform": platform,
                "x": x,
                "y": y,
                "mgmt": facts.get("mgmt_address"),
                "loopback": facts.get("loopback"),
                "vlan_roles": roles_by_vlan,
                "config": (BUILD / "configs" / f"{name}.cfg").read_text(),
            }
        )
    return devices


def describe(node: str, step: Step) -> str:
    """One readable line per step: the answer has to be legible to a human reviewer,
    not just true."""
    detail = step.detail
    if isinstance(detail, EnterInputIfaceStepDetail):
        return f"{node}  {step.action:<22} on {detail.inputInterface}"
    if isinstance(detail, FilterStepDetail):
        return f"{node}  {step.action:<22} by ACL {detail.filter} ({detail.filterType.lower()})"
    if isinstance(detail, RoutingStepDetail):
        routes = ", ".join(
            f"{route.protocol} {route.network}" for route in detail.routes
        )
        return f"{node}  {step.action:<22} out {detail.outputInterface} via {routes}"
    if isinstance(detail, ExitOutputIfaceStepDetail):
        return f"{node}  {step.action:<22} out {detail.outputInterface}"
    if isinstance(detail, DeliveredStepDetail):
        return f"{node}  {step.action:<22} out {detail.outputInterface}"
    return f"{node}  {step.action}"


def trace(session: Session, source: tuple[str, int, str], dst: str, port: str, gateway: str) -> dict:
    src_ip, vlan, _ = source
    frame = (
        session.q.traceroute(
            startLocation=f"@enter({gateway}[Vlan{vlan}])",
            headers=HeaderConstraints(srcIps=src_ip, dstIps=dst, ipProtocols=["tcp"], dstPorts=port),
        )
        .answer()
        .frame()
    )
    hops: list[str] = []
    dispositions: set[str] = set()
    for row in frame.itertuples():
        for item in row.Traces:
            dispositions.add(item.disposition)
            for hop in item.hops:
                for step in hop.steps:
                    hops.append(describe(hop.node, step))
    return {"hops": hops, "dispositions": sorted(dispositions)}


def policy_matrix(session: Session) -> list[dict]:
    rows = []
    for source in (WORKSTATION, BIOMED, GUEST):
        cells = []
        for label, dst, port in DESTINATIONS:
            if (source[2], label) not in INTENT:
                cells.append({"destination": label, "dst": dst, "port": port, "same_segment": True})
                continue
            expected = INTENT[(source[2], label)]
            per_gateway = {gw: trace(session, source, dst, port, gw) for gw in ("dist01", "dist02")}
            delivered = {
                gw: bool(set(result["dispositions"]) & DELIVERED)
                for gw, result in per_gateway.items()
            }
            cells.append(
                {
                    "destination": label,
                    "dst": dst,
                    "port": port,
                    "same_segment": False,
                    "expected": expected,
                    "delivered": delivered,
                    "matches_intent": all(value == expected for value in delivered.values()),
                    "traces": {gw: result["hops"] for gw, result in per_gateway.items()},
                    "dispositions": {
                        gw: result["dispositions"] for gw, result in per_gateway.items()
                    },
                }
            )
        rows.append({"source": source[2], "src_ip": source[0], "vlan": source[1], "cells": cells})
    return rows


def main() -> None:
    common, hosts = load_model()
    session = Session(host=os.environ.get("BATFISH_HOST", "localhost"))
    session.set_network("campus")
    session.init_snapshot(str(BUILD), name="campus-site", overwrite=True)

    data = {
        "vlans": common["vlans"],
        "devices": device_entries(common, hosts),
        "links": build_links(hosts),
        "destinations": [
            {"label": label, "ip": dst, "port": port} for label, dst, port in DESTINATIONS
        ],
        "policy": policy_matrix(session),
        "provenance": provenance(common, hosts, count_tests()),
    }
    out = Path(__file__).resolve().parent / "data.json"
    out.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
