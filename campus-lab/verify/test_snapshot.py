"""The configs have to be coherent before any behavioral claim about them means anything."""

from __future__ import annotations


# Lines Batfish's IOS grammar does not model. They are kept in the configs because
# the switch needs them; they are listed here so an unexpected one fails the build
# instead of quietly reducing what the analysis actually covers.
KNOWN_UNMODELED = ("ip default-gateway",)


def test_every_config_parses_without_error(bf) -> None:
    issues = bf.q.initIssues().answer().frame()
    parsing = issues[issues["Type"].isin(["Parse error", "Parse warning"])]
    unexpected = parsing[
        ~parsing["Line_Text"].str.strip().str.startswith(KNOWN_UNMODELED)
    ]
    assert unexpected.empty, f"snapshot did not parse cleanly:\n{unexpected}"


def test_no_undefined_references(bf) -> None:
    """An ACL or route-map applied but never defined is a silent permit-any."""
    undefined = bf.q.undefinedReferences().answer().frame()
    assert undefined.empty, f"configuration references things that do not exist:\n{undefined}"


def test_every_device_is_present(bf) -> None:
    nodes = set(bf.q.nodeProperties(properties="Configuration_Format").answer().frame()["Node"])
    assert nodes == {"acc01", "acc02", "dist01", "dist02", "core01"}


def test_router_ids_are_unique(bf) -> None:
    ospf = bf.q.ospfProcessConfiguration(properties="Router_ID").answer().frame()
    router_ids = list(ospf["Router_ID"])
    assert len(router_ids) == len(set(router_ids)), f"duplicate OSPF router IDs: {router_ids}"


def test_every_device_restricts_management_access(bf) -> None:
    """MGMT-ACCESS has to exist on every device and be applied, not just defined."""
    defined = bf.q.definedStructures().answer().frame()
    mgmt = defined[defined["Structure_Name"] == "MGMT-ACCESS"]
    nodes = {line.split("/")[-1].split(".")[0] for entry in mgmt["Source_Lines"] for line in [entry.filename]}
    assert nodes == {"acc01", "acc02", "dist01", "dist02", "core01"}, f"MGMT-ACCESS missing from {nodes}"


def test_nothing_is_configured_and_left_unapplied(bf) -> None:
    """An ACL that is defined but never applied is a control somebody believes in wrongly."""
    unused = bf.q.unusedStructures().answer().frame()
    assert unused.empty, f"defined but never applied:\n{unused}"
