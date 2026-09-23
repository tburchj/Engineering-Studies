"""The segmentation policy, written as traffic that must work and traffic that must not.

This is the part worth automating: nobody reading a 40-line ACL can tell you with
confidence whether the guest VLAN can still reach a biomed device. Batfish can,
straight from the configuration, before it is ever pushed to a switch.

Every flow is checked at both distribution switches, because a policy that is only
enforced on the HSRP active gateway stops being enforced the moment it fails over.
"""

from __future__ import annotations

import pytest
from pybatfish.datamodel.flow import HeaderConstraints

GATEWAYS = ("dist01", "dist02")

WORKSTATION = ("10.10.10.50", 10)
BIOMED = ("10.10.20.50", 20)
GUEST = ("10.10.30.50", 30)

DC_SERVER = "10.20.0.10"
MGMT_SWITCH = "10.10.99.2"
WORKSTATION_HOST = "10.10.10.50"
BIOMED_HOST = "10.10.20.50"
INTERNET = "8.8.8.8"

DELIVERED = {"ACCEPTED", "DELIVERED_TO_SUBNET", "EXITS_NETWORK"}


def dispositions(bf, source, dst: str, port: str, gateway: str) -> set[str]:
    src_ip, vlan = source
    traces = (
        bf.q.traceroute(
            startLocation=f"@enter({gateway}[Vlan{vlan}])",
            headers=HeaderConstraints(srcIps=src_ip, dstIps=dst, ipProtocols=["tcp"], dstPorts=port),
        )
        .answer()
        .frame()
    )
    found = {trace.disposition for row in traces.itertuples() for trace in row.Traces}
    assert found, f"no trace computed for {src_ip} -> {dst}:{port} at {gateway}"
    return found


@pytest.mark.parametrize("gateway", GATEWAYS)
@pytest.mark.parametrize(
    ("source", "dst", "port", "why"),
    [
        (WORKSTATION, DC_SERVER, "443", "workstations must reach the data center"),
        (WORKSTATION, INTERNET, "443", "workstations must reach the internet"),
        (BIOMED, DC_SERVER, "443", "biomed devices must reach their management servers"),
        (GUEST, INTERNET, "443", "guest wireless must reach the internet"),
    ],
)
def test_permitted_traffic_gets_through(bf, gateway, source, dst, port, why) -> None:
    found = dispositions(bf, source, dst, port, gateway)
    assert found <= DELIVERED, f"BLOCKED at {gateway} but should work ({why}): {found}"


@pytest.mark.parametrize("gateway", GATEWAYS)
@pytest.mark.parametrize(
    ("source", "dst", "port", "why"),
    [
        (GUEST, WORKSTATION_HOST, "445", "guest must not reach a workstation"),
        (GUEST, BIOMED_HOST, "443", "guest must not reach a biomed device"),
        (GUEST, DC_SERVER, "443", "guest must not reach the data center"),
        (GUEST, MGMT_SWITCH, "22", "guest must not reach the management network"),
        (WORKSTATION, MGMT_SWITCH, "22", "switches are managed from the jump host only"),
        (WORKSTATION, BIOMED_HOST, "443", "workstations must not reach biomed devices directly"),
        (BIOMED, WORKSTATION_HOST, "445", "a compromised device must not pivot to a workstation"),
        (BIOMED, INTERNET, "443", "biomed devices have no reason to reach the internet"),
    ],
)
def test_forbidden_traffic_is_dropped(bf, gateway, source, dst, port, why) -> None:
    found = dispositions(bf, source, dst, port, gateway)
    assert not (found & DELIVERED), f"ALLOWED at {gateway} but must not be ({why}): {found}"
