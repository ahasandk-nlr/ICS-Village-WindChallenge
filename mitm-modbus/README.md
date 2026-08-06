# modbus defcon

A `master`/`slave` Modbus TCP pair, plus an in-network `attacker` box
(Ettercap, reachable from a browser at port 7681, no login needed) so you
can ARP-poison the link between them and alter traffic in flight with the
provided filter (`etter.filter.modbus`).

```
docker-compose up
```

For setup, functional testing, and how this ties into the shared
dashboard, see [`docs/ADMIN.md`](../docs/ADMIN.md). For how to actually
run the attack, see [`attacker/README.md`](attacker/README.md). If you're
a player looking for where to start, see
[`docs/PLAYER.md`](../docs/PLAYER.md).
