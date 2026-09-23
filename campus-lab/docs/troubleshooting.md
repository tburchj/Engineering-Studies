# Troubleshooting this network, layer by layer

Written the way I work a fault: start at the layer where the symptom can be reproduced,
prove or eliminate that layer before moving up, and never trust a single measurement that
says "clean". The commands are the ones you would run on the hardware; the Batfish
queries are what you can run against the configuration before the change window instead
of after the outage.

## Order of operations

1. Reproduce and scope it. One port, one VLAN, one switch, or everything? The scope names
   the layer before any command does. One port is L1 or port config; one VLAN everywhere
   is the SVI, the gateway or the ACL; everything on one switch is the uplink or STP.
2. Prove Layer 1 before touching configuration.
3. Prove Layer 2 reaches the gateway.
4. Prove Layer 3 has a route back.
5. Only then suspect policy.

Skipping step 2 is how a team spends two hours on OSPF for a dirty optic. I have watched
a clean copper pair test fine on a quick meter and still carry 39 V of cross-battery from
an adjacent line — the fault only appeared when the meter was held on the pair long
enough to force it. A single passing test is not a passed layer.

## Layer 1 — the link itself

```
show interfaces GigabitEthernet1/0/11 status
show interfaces GigabitEthernet1/0/11 counters errors
show interfaces transceiver detail        ! optics: Rx/Tx dBm against threshold
show logging | include %LINK|%LINEPROTO
```

What matters:

- **Input errors, CRC, runts, giants.** CRCs that climb with traffic mean the media, the
  connector or the optic — not the switch. Late collisions on a full-duplex link mean a
  duplex mismatch, which reads as "slow", not "down".
- **Rx power near the threshold** is a link that works until it is warm. Compare against
  the far end, not against zero.
- **Flapping.** `%LINEPROTO` messages with no configuration change are physical until
  proven otherwise.
- **err-disabled.** `show interfaces status err-disabled` plus `show errdisable recovery`.
  On this design a port-security violation is `restrict`, not `shutdown`, so a second MAC
  drops frames and logs rather than killing the port — but BPDU guard *will* shut a port
  that receives a BPDU, which is exactly what you want when somebody plugs in a switch.

## Layer 2 — VLANs, trunks and spanning tree

```
show vlan brief
show interfaces GigabitEthernet1/0/11 switchport      ! access VLAN, mode, nonegotiate
show interfaces trunk                                 ! allowed and active VLAN lists
show spanning-tree vlan 10
show mac address-table vlan 10 | include <mac>
show ip dhcp snooping binding
```

The two failures worth naming:

- **Allowed-VLAN mismatch on a trunk.** The link is up, most VLANs work, one VLAN is a
  black hole. `show interfaces trunk` on *both* ends and compare — the "allowed" and
  "forwarding" lists are different lines and you need both. This is checked statically by
  `test_trunk_allowed_vlans_match_on_both_ends`.
- **An unexpected STP root.** `show spanning-tree vlan 10` should show dist01 as root for
  VLAN 10 with priority 4096. If a cheap switch under a desk has become root, every user
  VLAN is now taking a path nobody designed. Root guard on the distribution trunks is what
  prevents it; loop guard is what prevents a unidirectional link from creating a loop when
  BPDUs stop arriving.

Because STP root and HSRP active are deliberately the same switch per VLAN, a root change
also means the gateway path now crosses the peer link. The symptom is "everything still
works but the peer link is suddenly busy" — worth an alert, not just a look.

## Layer 3 — adjacency, routes and first-hop redundancy

```
show ip ospf neighbor
show ip ospf interface TenGigabitEthernet1/0/1     ! area, network type, cost, timers
show ip route 10.20.0.0
show standby brief
show standby Vlan10
```

- **OSPF stuck in INIT/EXSTART.** INIT means hellos are one-way: check the ACL, the
  subnet mask and the area. EXSTART is an MTU mismatch nearly every time.
- **No neighbour at all** on a link that is up: `passive-interface default` is in this
  design, so a new routed link needs an explicit `no passive-interface`. That omission is
  the single most common way to add a link here and see nothing happen.
- **Both HSRP routers active** means they cannot hear each other in that VLAN — trunk or
  SVI problem, not an HSRP problem. `show standby Vlan10` shows the virtual IP, priority
  and preempt state; priority 110 with preempt delay 60 is the intended primary.
- **Traffic works one direction only** is a return-path problem. Check the route back on
  the far side before you touch anything on the side you can see.

## Policy — when the plumbing is right and it still fails

```
show ip access-lists WORKSTATION-IN        ! hit counters tell you which line matched
show ip interface Vlan10 | include access list
show logging | include denied
```

If a deny line's counter is climbing at the moment the user reproduces the problem, you
are done. If nothing increments, the traffic is not reaching this device and you are back
at Layer 2.

The same question answered from the configuration, without waiting for a user:

```bash
.venv/bin/python -m pytest verify/test_segmentation.py -q
```

or interactively, for one flow:

```python
bf.q.traceroute(
    startLocation="@enter(dist01[Vlan30])",
    headers=HeaderConstraints(srcIps="10.10.30.50", dstIps="10.10.20.50",
                              ipProtocols=["tcp"], dstPorts="443"),
).answer().frame()
# DENIED_IN at dist01 — GUEST-IN line 3
```

## The failure this design is trying not to repeat

A fibre install of mine once stalled because a zero-touch provisioning system failed to
authenticate the ONT. The physical layer was clean; the automation had failed; and the
architecture offered no field-side override, so troubleshooting hard-stopped and the
profile had to be rebuilt by a backlogged engineering team. A ten minute job became a
queue, and the cost landed on the customer and the technician rather than on whoever
designed it that way.

That is why this repository generates configurations rather than pushing them, why the
rendered configs are readable artefacts, and why every assertion the tests make is one a
person can also check by hand on the device with a `show` command. Automation that cannot
be inspected or overridden by the person holding the consequences is not an improvement
over doing it by hand.
