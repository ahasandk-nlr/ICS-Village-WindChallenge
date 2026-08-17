# attacker box

A shell on the same Docker network as `master` and `slave`, reachable from
a browser — no SSH key or `docker exec` access needed. This exists
because `master`/`slave`'s Modbus conversation lives entirely on this
challenge's own private Docker network (`my_network`, 172.20.0.0/16),
which never reaches a physical wire — a participant's own laptop has no
way to get a NIC onto this specific segment. This container solves that by
already being on it.

## Access

Open `http://<host>:7681` in a browser. You get a `bash` shell inside this
container, on the same network segment as `master` (172.20.0.2) and
`slave` (172.20.0.3).

## Running the intended MITM attack

The repo ships an Ettercap filter (`etter.filter.modbus`, pre-compiled as
`etter.filter.modbuscomp`, both copied into this container's home
directory) that rewrites `0xFF` write values to `0x00` in Modbus traffic
passing through the poisoned link.

```bash
# confirm you can see both hosts
nmap -sn 172.20.0.0/24

# ARP-poison the link between master and slave, with the filter loaded
ettercap -T -q -i eth0 -F etter.filter.modbuscomp -M arp:remote /172.20.0.2// /172.20.0.3//
```

This exact command was run end-to-end while building this box: Ettercap
resolved both hosts' real MAC addresses, established ARP poisoning between
them, and printed `Correctly substituted and logged` as it caught and
altered a live Modbus write-coil packet in transit — the filter's `0xFF`
→`0x00` substitution actually happening on real traffic, not just a
config that looks right.

If you edit `etter.filter.modbus`, recompile it before loading — Ettercap
loads the compiled `.eft`-style output (`etter.filter.modbuscomp`), not
the source filter directly:

```bash
etterfilter etter.filter.modbus -o etter.filter.modbuscomp
```

## Notes

- This container runs `privileged: true`, not just
  `NET_ADMIN`/`NET_RAW` — those two capabilities alone weren't enough.
  Ettercap writes to `/proc/sys/net/ipv6/conf/all/forwarding` as part of
  its own startup safety routine, and `/proc/sys` stays read-only under
  Docker's default profile regardless of added capabilities (confirmed
  directly: Ettercap failed with `Read-only file system` on that path
  until `privileged: true` was set). If you're hardening this later,
  that's the specific wall you'll hit trying to narrow the privilege
  scope back down.
- No authentication on the web terminal — anyone reaching port 7681 gets a
  shell here, by design (same trust model as `audit-sidecar`'s write
  panel). Don't expose this port beyond the exhibit network.
- This box is intentionally generic (Ettercap + tcpdump + net-tools), not
  locked down to only the Modbus filter — participants can also just
  explore the segment from here if they get stuck on the ARP-spoofing
  approach specifically.
