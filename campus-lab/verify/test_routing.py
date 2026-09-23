"""Adjacencies and first-hop redundancy, computed from the configs rather than assumed."""

from __future__ import annotations

import pytest

EXPECTED_ADJACENCIES = {
    frozenset({"dist01", "core01"}),
    frozenset({"dist02", "core01"}),
    frozenset({"dist01", "dist02"}),
}


def test_every_ospf_session_is_compatible(bf) -> None:
    """Catches the classic mismatches — area, network type, MTU, timers — before deployment."""
    sessions = bf.q.ospfSessionCompatibility().answer().frame()
    broken = sessions[sessions["Session_Status"] != "ESTABLISHED"]
    assert broken.empty, f"OSPF sessions that will not come up:\n{broken}"

    formed = {frozenset({row.Interface.hostname, row.Remote_Interface.hostname}) for row in sessions.itertuples()}
    assert formed == EXPECTED_ADJACENCIES, f"unexpected OSPF adjacency set: {formed}"


def test_access_switches_run_no_routing_protocol(bf) -> None:
    ospf = bf.q.ospfProcessConfiguration().answer().frame()
    assert not set(ospf["Node"]) & {"acc01", "acc02"}


def test_one_hsrp_active_gateway_per_vlan(bf) -> None:
    """Both distribution switches offering the same priority is a coin-flip gateway."""
    try:
        hsrp = bf.q.hsrpProperties().answer().frame()
    except AttributeError:  # pragma: no cover - older pybatfish
        pytest.skip("hsrpProperties not available in this pybatfish")
    assert not hsrp.empty, "no HSRP groups found"
    for group, rows in hsrp.groupby("Group_Id"):
        priorities = sorted(rows["Priority"], reverse=True)
        assert len(priorities) == 2, f"HSRP group {group} is not a pair: {priorities}"
        assert priorities[0] != priorities[1], f"HSRP group {group} has a priority tie: {priorities}"
        virtual_ips = {str(ip) for row in rows.itertuples() for ip in row.Virtual_Addresses}
        assert len(virtual_ips) == 1, f"HSRP group {group} advertises more than one VIP: {virtual_ips}"


def test_gateway_and_spanning_tree_root_are_the_same_switch(bf) -> None:
    """A VLAN whose STP root is not its HSRP active switch sends every packet over the peer link."""
    import yaml
    from pathlib import Path

    design = Path(__file__).resolve().parents[1] / "design"
    vlans = yaml.safe_load((design / "group_vars" / "all.yml").read_text())["vlans"]
    for host in ("dist01", "dist02"):
        facts = yaml.safe_load((design / "host_vars" / f"{host}.yml").read_text())
        root_vlans = set(facts["stp_root_vlans"])
        primary_vlans = {vlan["id"] for vlan in vlans if vlan["primary"] == host}
        assert root_vlans == primary_vlans, (
            f"{host} is STP root for {sorted(root_vlans)} but HSRP active for {sorted(primary_vlans)}"
        )
