"""What a generated configuration must never contain, and what it must always carry."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CONFIGS = sorted((Path(__file__).resolve().parents[1] / "build" / "configs").glob("*.cfg"))

# Anything that looks like a real credential. The build is committed and public,
# so a hash or key that is not an obvious placeholder is a leak even if it is a
# lab value: nobody reviewing the diff can tell the difference.
CREDENTIAL_SHAPES = [
    re.compile(r"secret [59] \$[19]\$"),
    re.compile(r"password 7 [0-9A-Fa-f]{4,}"),
    re.compile(r"^enable (password|secret) ", re.MULTILINE),
    re.compile(r"snmp-server community"),
    re.compile(r"key-string"),
    re.compile(r"ip ospf authentication-key"),
]

# The lines that make a change reversible and reconstructable after the fact.
EVIDENCE_LINES = (
    "archive",
    " log config",
    "  logging enable",
    "  notify syslog contenttype plaintext",
    "  hidekeys",
    "login on-failure log",
    "login on-success log",
)


@pytest.mark.parametrize("config", CONFIGS, ids=lambda path: path.stem)
def test_no_credential_material_in_the_build(config) -> None:
    text = config.read_text()
    found = [shape.pattern for shape in CREDENTIAL_SHAPES if shape.search(text)]
    assert not found, f"{config.name} contains credential-shaped material: {found}"


@pytest.mark.parametrize("config", CONFIGS, ids=lambda path: path.stem)
def test_every_change_is_archived_and_logged(config) -> None:
    lines = config.read_text().splitlines()
    missing = [line for line in EVIDENCE_LINES if line not in lines]
    assert not missing, f"{config.name} cannot be rolled back or reconstructed: missing {missing}"


@pytest.mark.parametrize("config", CONFIGS, ids=lambda path: path.stem)
def test_no_unencrypted_management_plane(config) -> None:
    lines = config.read_text().splitlines()
    assert "no ip http server" in lines and "no ip http secure-server" in lines
    assert "ip ssh version 2" in lines
    assert not any(line.strip() == "transport input telnet" or "transport input all" in line for line in lines)
