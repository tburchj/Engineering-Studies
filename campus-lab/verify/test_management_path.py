"""The path the automation arrives on has to survive the change it is making.

A management ACL that excludes the address the runner comes from is the one
failure a rollback cannot undo: restoring the device needs exactly the path the
ACL just cut. So before any of this is trusted, the model's jump hosts are traced
to every device's management address, and the management ACL is asked directly
who it lets in.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pybatfish.datamodel.flow import HeaderConstraints

DESIGN = Path(__file__).resolve().parents[1] / "design"
MODEL = yaml.safe_load((DESIGN / "group_vars" / "all.yml").read_text())
JUMP_HOSTS = MODEL["jump_hosts"]
MGMT_VLAN = MODEL["mgmt_vlan"]

DEVICES = {
    path.stem: yaml.safe_load(path.read_text())["mgmt_address"]
    for path in sorted((DESIGN / "host_vars").glob("*.yml"))
}

# A workstation, and an address inside the management subnet that is not a jump
# host: being on the right VLAN must not be enough to reach a switch's CLI.
NOT_A_JUMP_HOST = ("10.10.10.50", "10.10.99.200")


def ssh_from(src: str, dst: str) -> HeaderConstraints:
    return HeaderConstraints(srcIps=src, dstIps=dst, ipProtocols=["tcp"], dstPorts="22")


@pytest.mark.parametrize("jump_host", JUMP_HOSTS)
@pytest.mark.parametrize("gateway", ["dist01", "dist02"])
@pytest.mark.parametrize(("device", "mgmt_address"), sorted(DEVICES.items()))
def test_runner_can_reach_every_device(bf, jump_host, gateway, device, mgmt_address) -> None:
    """Traced through both gateways: the runner must still get in after a failover."""
    traces = (
        bf.q.traceroute(
            startLocation=f"@enter({gateway}[Vlan{MGMT_VLAN}])",
            headers=ssh_from(jump_host, mgmt_address),
        )
        .answer()
        .frame()
    )
    dispositions = {trace.disposition for row in traces.itertuples() for trace in row.Traces}
    assert dispositions == {"ACCEPTED"}, (
        f"{jump_host} cannot SSH to {device} ({mgmt_address}) via {gateway}: {dispositions}"
    )


@pytest.mark.parametrize("device", sorted(DEVICES))
def test_management_acl_admits_only_the_jump_hosts(bf, device) -> None:
    def action(src: str) -> set[str]:
        frame = (
            bf.q.testFilters(nodes=device, filters="MGMT-ACCESS", headers=ssh_from(src, DEVICES[device]))
            .answer()
            .frame()
        )
        assert not frame.empty, f"MGMT-ACCESS not found on {device}"
        return set(frame["Action"])

    for host in JUMP_HOSTS:
        assert action(host) == {"PERMIT"}, f"{device} refuses its own jump host {host}"
    for host in NOT_A_JUMP_HOST:
        assert action(host) == {"DENY"}, f"{device} lets {host} at its CLI"
