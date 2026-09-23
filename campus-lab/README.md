# campus-lab — an enterprise access/distribution/core design, generated and formally verified

A three-tier campus network — two access switches, a redundant distribution pair, and a
core router — described once as data, rendered into Cisco IOS-XE style configurations by
Ansible, and then checked by [Batfish](https://batfish.org), which builds a model of the
forwarding and filtering behaviour from the configurations themselves and answers
questions about it.

The point is the last part. Anyone can write a VLAN and an ACL. The interesting question
is how you know, before the change window, that the guest VLAN still cannot reach a
biomedical device, that both distribution switches enforce that identically, and that the
trunk you just edited still carries every VLAN on both ends. Here that is 38 tests that
run in five seconds:

```
$ pytest verify -q
38 passed in 5.38s
```

## The design

```
                         internet 198.51.100.1
                                |
                       +------------------+
                       |      core01      |  Catalyst 8300 style
                       |  10.255.0.1      |  OSPF area 0, default route out
                       +---+----------+---+
               10.255.1.0/31 |      | 10.255.1.2/31
                   +---------+      +---------+
                   |                          |
          +--------+--------+  10.255.1.4/31  +--------+--------+
          |     dist01      |-----------------|     dist02      |  Catalyst 9500 style
          | root VLAN 10,99 |   L3 peer link  | root VLAN 20,30 |  SVIs + HSRPv2 + ACLs
          | HSRP act 10,99  |                 | HSRP act 20,30  |
          +---+---------+---+                 +---+---------+---+
              |         |     802.1Q trunks       |         |
              |         +------------+------------+         |
              |                      |                      |
          +---+------+          +----+-----+                |
          |  acc01   |          |  acc02   |   Catalyst 9300 style
          +----------+          +----------+   access ports, no L3

VLAN 10 WORKSTATION 10.10.10.0/24   VLAN 20 BIOMED 10.10.20.0/24
VLAN 30 GUEST       10.10.30.0/24   VLAN 99 MGMT   10.10.99.0/24
```

Deliberate choices, each of which a reviewer can check in the configs:

- **Layer 3 stops at distribution.** Access switches have `no ip routing`, one management
  SVI and a default gateway. Every inter-VLAN decision happens in one tier, so there is
  one place to look when traffic goes where it should not.
- **STP root and HSRP active are the same switch, per VLAN.** dist01 is root and active
  for VLANs 10 and 99, dist02 for 20 and 30. When they disagree, traffic crosses the peer
  link to reach its own gateway and the link that was sized for failover carries steady
  state. `verify/test_routing.py` asserts they agree.
- **HSRP preempt has a 60 second delay** on the primary, so a switch that has just booted
  does not take the gateway back before its uplinks and OSPF have converged.
- **The distribution peer link is routed, not a trunk.** It carries OSPF, not VLANs, which
  keeps the spanning-tree domains small and the failure modes readable.
- **`passive-interface default`** with OSPF enabled only on the three routed links. User
  VLANs are advertised but never form an adjacency with something plugged into an access
  port.
- **Segmentation is applied inbound at the gateway SVI on both distribution switches**,
  not on one of them, because a policy enforced only on the HSRP active switch stops
  existing at failover. The tests check every flow at both.

## How it is built

Nothing is typed twice. `design/group_vars/all.yml` holds the VLANs, prefixes and OSPF
parameters; `design/host_vars/*.yml` holds each device's addresses, uplinks and port
assignments. From that one model, `design/render.yml` renders both the device
configurations *and* the Layer 1 cable map that the analysis uses — so a topology change
cannot silently disagree with the configuration it was verified against.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/ansible-galaxy collection install -r design/requirements.yml

# render build/configs/*.cfg and build/batfish/layer1_topology.json
cd design && ../.venv/bin/ansible-playbook -i inventory.yml render.yml

# start the analysis engine and check the design
docker run -d --name batfish -p 9996:9996 -p 9997:9997 batfish/allinone
.venv/bin/python -m pytest verify -q
```

## What the tests actually assert

| File | What it protects against |
| --- | --- |
| `verify/test_snapshot.py` | configs that do not parse, ACLs referenced but never defined, ACLs defined but never applied, duplicate OSPF router IDs, a device missing `MGMT-ACCESS` on its VTY lines |
| `verify/test_layer2.py` | allowed-VLAN lists that differ between the two ends of a trunk, access ports in a VLAN that does not exist, an access switch with no reachable management SVI |
| `verify/test_routing.py` | OSPF adjacencies that will not come up, OSPF where it does not belong, missing or mismatched HSRP groups, STP root and HSRP active disagreeing |
| `verify/test_segmentation.py` | every permitted and forbidden flow in the policy, evaluated at both distribution switches |

The segmentation tests read as the policy itself:

```python
(GUEST,       BIOMED_HOST, "443", "guest must not reach a biomed device"),
(WORKSTATION, MGMT_SWITCH, "22",  "switches are managed from the jump host only"),
(BIOMED,      INTERNET,    "443", "biomed devices have no reason to reach the internet"),
```

A troubleshooting walkthrough — what to look at, in what order, when each of these fails
on real hardware — is in [`docs/troubleshooting.md`](docs/troubleshooting.md).

## What this is and is not

- The configurations are **Cisco IOS-XE syntax for Catalyst 9300/9500/8300 platforms**,
  and they are parsed and modelled as IOS-XE by Batfish.
- They have **not been applied to physical Catalyst hardware**. Cisco does not publish
  freely runnable C9000/C8000 images, so behaviour here is proven by formal analysis of
  the configurations rather than by packets on a real switch. Batfish models routing,
  forwarding and ACL behaviour; it does not model control-plane timing, STP convergence,
  or hardware TCAM limits.
- Addressing, VLAN names and the segmentation policy are invented for the lab. There is
  no customer data here of any kind.
- This was built with AI-assisted implementation. The design, the failure modes it is
  built around, the choice of what to verify and the reading of the results are mine, and
  I can defend any line in it.
