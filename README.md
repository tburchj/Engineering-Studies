# Engineering Studies

Network engineering work I build to answer a question properly rather than approximately.
Each study is self-contained: a design, the reasoning behind it, and automated proof that
the design does what it claims.

| Study | What it is |
| --- | --- |
| [`campus-lab/`](campus-lab/) — [click through it](https://tburchj.github.io/Engineering-Studies/) | A three-tier enterprise campus — two access switches, a redundant distribution pair, a core router — in Cisco IOS-XE syntax. VLANs and 802.1Q trunks, Rapid-PVST root placement, OSPF area 0, HSRPv2 gateways and ACL segmentation, all generated from one data model by Ansible and verified with Batfish before anything could reach a device. Includes a Layer 1–3 troubleshooting walkthrough. |

Related work in other repositories:

- [`vertex-poc`](https://github.com/tburchj/vertex-poc) — a change-delivery pipeline that
  plans, stops at a named human approver, applies a multi-vendor baseline, verifies from the
  device, and packages hashed evidence of what it did.
