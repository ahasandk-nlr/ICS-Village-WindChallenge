#!/usr/bin/env python3
"""Pymodbus asynchronous master. CLIENT = MASTER or CLIENT = CONNECTS TO
DEVICES


usage: master.py

All options must be adapted in the code
The corresponding server must be started before e.g. as:
    python3 master.py
"""
import asyncio
import os
import time
import pymodbus.client as ModbusClient
from pymodbus import (
    ExceptionResponse,
    Framer,
    ModbusException,
    pymodbus_apply_logging_config,
)


async def run_async_master(comm, host, port, framer=Framer.SOCKET):
    """Run async client."""
    # activate debugging
    pymodbus_apply_logging_config("INFO")

    print("get client " + comm)
    if comm == "tcp":
        client = ModbusClient.AsyncModbusTcpClient(
            host,
            port=port,
            framer=framer,
            timeout=100000,
            retries=1000000,
            # retry_on_empty=False,
            # source_address=("localhost", 0),
        )
    elif comm == "udp":
        client = ModbusClient.AsyncModbusUdpClient(
            host,
            port=port,
            framer=framer,
        )
    elif comm == "serial":
        client = ModbusClient.AsyncModbusSerialClient(
            port,
            framer=framer,
            timeout=10000000,
            retries=100000,
            baudrate=9600,
            bytesize=8,
            parity="N",
            stopbits=1,
        )
    elif comm == "tls":
        client = ModbusClient.AsyncModbusTlsClient(
            host,
            port=port,
            framer=Framer.TLS,
            certfile="../examples/certificates/pymodbus.crt",
            keyfile="../examples/certificates/pymodbus.key",
            server_hostname="localhost",
        )
    else:
        print(f"Unknown client {comm} selected")
        return

    print("connect to server")
    # slave may not be up yet (no depends_on health check between the two
    # services) - retry instead of crashing outright on the first attempt.
    while not client.connected:
        await client.connect()
        if not client.connected:
            print("could not connect yet, retrying in 5s")
            await asyncio.sleep(5)

    print("get and verify data")
    # Keep writing coil 1 True every 5s, retrying indefinitely on any
    # Modbus-level error instead of the previous duplicated
    # try/except-with-a-second-copy-of-the-loop, which also left an
    # unreachable isError()/ExceptionResponse check after both loops that
    # could never be reached (and would reference `rr` before it was ever
    # assigned, if the very first write raised).
    while True:
        await asyncio.sleep(5)
        try:
            rr = await client.write_coil(1, True)
        except ModbusException as exc:
            print(f"Received ModbusException({exc}) from library, retrying")
            continue

        if rr.isError():
            print(f"Received Modbus library error({rr}), retrying")
            continue
        if isinstance(rr, ExceptionResponse):
            # THIS IS NOT A PYTHON EXCEPTION, but a valid modbus message
            print(f"Received Modbus library exception ({rr}), retrying")
            continue

        print(rr)
        print("restarting")


if __name__ == "__main__":
    time.sleep(5)
    asyncio.run(
        run_async_master("tcp", os.environ.get("SLAVE_HOST", "slave"), 502),
        debug=False,
    )
