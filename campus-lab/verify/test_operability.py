"""Controls that are worse than useless if they are subtly wrong.

Segmentation tests prove the policy blocks what it should. These prove the same
configuration does not also block the things the network needs in order to work
at all — the failure mode where every security control is present and correct
and nobody can get an address or log in.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pybatfish.datamodel.flow import HeaderConstraints

CONFIGS = Path(__file__).resolve().parents[1] / "build" / "configs"

CLIENT_FILTERS = [
    ("dist01", "GUEST-IN", "10.10.30.50"),
    ("dist02", "GUEST-IN", "10.10.30.50"),
    ("dist01", "BIOMED-IN", "10.10.20.50"),
    ("dist02", "BIOMED-IN", "10.10.20.50"),
    ("dist01", "WORKSTATION-IN", "10.10.10.50"),
    ("dist02", "WORKSTATION-IN", "10.10.10.50"),
]

DHCP_SERVER = "10.20.0.10"


def permitted(bf, node: str, filter_name: str, headers: HeaderConstraints) -> bool:
    frame = bf.q.testFilters(nodes=node, filters=filter_name, headers=headers).answer().frame()
    assert not frame.empty, f"{filter_name} not found on {node}"
    return all(row == "PERMIT" for row in frame["Action"])


@pytest.mark.parametrize(("node", "filter_name", "client"), CLIENT_FILTERS)
def test_a_client_with_no_address_can_still_ask_for_one(bf, node, filter_name, client) -> None:
    """DISCOVER is sourced from 0.0.0.0 and hits the SVI ACL before the relay."""
    headers = HeaderConstraints(
        srcIps="0.0.0.0",
        dstIps="255.255.255.255",
        ipProtocols=["udp"],
        srcPorts="68",
        dstPorts="67",
    )
    assert permitted(bf, node, filter_name, headers), (
        f"{filter_name} on {node} drops DHCP DISCOVER: the segment can never get a lease"
    )


@pytest.mark.parametrize(("node", "filter_name", "client"), CLIENT_FILTERS)
def test_a_client_can_renew_its_lease(bf, node, filter_name, client) -> None:
    """Renewal is unicast to the server, so the internal-prefix denies can eat it."""
    headers = HeaderConstraints(
        srcIps=client,
        dstIps=DHCP_SERVER,
        ipProtocols=["udp"],
        srcPorts="68",
        dstPorts="67",
    )
    assert permitted(bf, node, filter_name, headers), (
        f"{filter_name} on {node} drops the unicast renewal: leases expire and never come back"
    )


def test_guest_can_resolve_names(bf) -> None:
    """Guest DNS has to reach the resolvers, not the gateway address."""
    headers = HeaderConstraints(
        srcIps="10.10.30.50", dstIps="10.20.0.10", ipProtocols=["udp"], dstPorts="53"
    )
    for node in ("dist01", "dist02"):
        assert permitted(bf, node, "GUEST-IN", headers), (
            f"GUEST-IN on {node} denies DNS to the configured resolver"
        )


@pytest.mark.parametrize("config", sorted(CONFIGS.glob("*.cfg")))
def test_local_authentication_has_an_account_to_authenticate_against(config) -> None:
    """'aaa authentication login default local' with no local user is a lockout."""
    text = config.read_text()
    if "aaa authentication login default local" not in text:
        pytest.skip("device does not use local authentication")
    assert "username " in text, f"{config.name} authenticates locally but defines no account"


@pytest.mark.parametrize("config", sorted(CONFIGS.glob("*.cfg")))
def test_root_guard_is_not_applied_to_campus_trunks(config) -> None:
    """The inter-distribution Layer 2 path runs through the access layer, because
    the peer link is routed. Root guard on those trunks blocks the intended root."""
    lines = config.read_text().splitlines()
    guarded = [
        index for index, line in enumerate(lines) if line.strip() == "spanning-tree guard root"
    ]
    for index in guarded:
        stanza = "\n".join(lines[max(0, index - 8) : index])
        assert "switchport mode trunk" not in stanza, (
            f"{config.name}: root guard on a campus trunk will block the configured root\n{stanza}"
        )
