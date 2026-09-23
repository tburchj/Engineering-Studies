"""Layer 2 consistency: the mismatches that produce a working link and a black hole."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "design"


def _model_vlans() -> set[int]:
    return {vlan["id"] for vlan in yaml.safe_load((DESIGN / "group_vars" / "all.yml").read_text())["vlans"]}


def _edges() -> list[tuple[tuple[str, str], tuple[str, str]]]:
    topology = json.loads((ROOT / "build" / "batfish" / "layer1_topology.json").read_text())
    return [
        ((edge["node1"]["hostname"], edge["node1"]["interfaceName"]),
         (edge["node2"]["hostname"], edge["node2"]["interfaceName"]))
        for edge in topology["edges"]
    ]


def test_trunk_allowed_vlans_match_on_both_ends(bf) -> None:
    """An allowed-VLAN list that differs by one VLAN is the classic silent outage."""
    props = bf.q.interfaceProperties(properties="Switchport_Mode,Allowed_VLANs").answer().frame()
    allowed = {
        (row.Interface.hostname, row.Interface.interface): row.Allowed_VLANs
        for row in props.itertuples()
        if row.Switchport_Mode == "TRUNK"
    }
    for near, far in _edges():
        if near in allowed and far in allowed:
            assert allowed[near] == allowed[far], (
                f"trunk mismatch: {near} allows {allowed[near]}, {far} allows {allowed[far]}"
            )


def test_every_access_port_lands_in_a_vlan_that_exists(bf) -> None:
    props = bf.q.interfaceProperties(properties="Switchport_Mode,Access_VLAN").answer().frame()
    defined = _model_vlans()
    for row in props.itertuples():
        if row.Switchport_Mode == "ACCESS":
            assert row.Access_VLAN in defined, f"{row.Interface} is in undefined VLAN {row.Access_VLAN}"


def test_trunks_carry_every_campus_vlan(bf) -> None:
    props = bf.q.interfaceProperties(properties="Switchport_Mode,Allowed_VLANs").answer().frame()
    expected = ",".join(str(vlan) for vlan in sorted(_model_vlans()))
    trunks = [row for row in props.itertuples() if row.Switchport_Mode == "TRUNK"]
    assert trunks, "no trunks found"
    for row in trunks:
        assert row.Allowed_VLANs == expected, f"{row.Interface} allows {row.Allowed_VLANs}, expected {expected}"


def test_access_switches_are_reachable_for_management(bf) -> None:
    props = bf.q.interfaceProperties(properties="Active,All_Prefixes").answer().frame()
    svis = [
        row
        for row in props.itertuples()
        if row.Interface.hostname in ("acc01", "acc02") and row.Interface.interface == "Vlan99"
    ]
    assert len(svis) == 2
    for row in svis:
        assert row.Active, f"{row.Interface} is down: the switch cannot be managed"
        assert row.All_Prefixes, f"{row.Interface} has no address"
