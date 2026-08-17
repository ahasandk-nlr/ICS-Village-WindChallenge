#!/usr/bin/env python3
"""Pymodbus asynchronous slave. SLAVE = SERVER OR SERVER = SERVES DATA.

An  multi threaded asynchronous server.

usage::

    master.py [-h] [--comm {tcp,udp,serial,tls}]
                    [--framer {ascii,rtu,socket,tls}]
                    [--log {critical,error,warning,info,debug}]
                    [--port PORT] [--store {sequential,sparse,factory,none}]
                    [--slaves SLAVES]

    -h, --help
        show this help message and exit
    -c, --comm {tcp,udp,serial,tls}
        set communication, default is tcp
    -f, --framer {ascii,rtu,socket,tls}
        set framer, default depends on --comm
    -l, --log {critical,error,warning,info,debug}
        set log level, default is info
    -p, --port PORT
        set port
        set serial device baud rate
    --store {sequential,sparse,factory,none}
        set datastore type
    --slaves SLAVES
        set number of slaves to respond to

The corresponding client can be started as:

    python3 master.py

"""
import asyncio
import logging
import os
import sys
import time
import paho.mqtt.client as mqtt

try:
    import RPi.GPIO as GPIO
except (ImportError, RuntimeError) as exc:
    # RPi.GPIO raises RuntimeError (not just ImportError) off real Pi
    # hardware, so this needs to catch both. Falls back to a no-op mock so
    # this module can still run - and be tested - off a Raspberry Pi (e.g.
    # in this repo's simulation environment). On real hardware this branch
    # never triggers; the actual import above succeeds instead.
    print(f"RPi.GPIO unavailable ({exc}), using no-op GPIO mock")

    class _MockGPIO:
        BCM = "BCM"
        OUT = "OUT"
        HIGH = 1
        LOW = 0

        def setmode(self, mode):
            print(f"[mock GPIO] setmode({mode})")

        def setup(self, pin, mode):
            print(f"[mock GPIO] setup(pin={pin}, mode={mode})")

        def output(self, pin, value):
            print(f"[mock GPIO] output(pin={pin}, value={value})")

    GPIO = _MockGPIO()

try:
    import helper
except Exception as e:
    print(e)
    print("*** ERROR --> THIS EXAMPLE needs the example directory, please see \n\
          https://pymodbus.readthedocs.io/en/latest/source/examples.html\n\
          for more information.")
    sys.exit(-1)

from pymodbus import __version__ as pymodbus_version
from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
    ModbusSparseDataBlock,
)
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.server import (
    StartAsyncSerialServer,
    StartAsyncTcpServer,
    StartAsyncTlsServer,
    StartAsyncUdpServer,
)
# BCM12 (physical pin 32) - CH3 in docs/PINOUT_MAP.md. Was previously set
# up as pin 17 here while changeON() below wrote to pin 12, a mismatch
# that made changeON() raise "channel not set up" the moment it ran.
RELAY_PIN = int(os.environ.get("RELAY_PIN", "12"))

GPIO.setmode(GPIO.BCM)  # Use BCM pin numbering
GPIO.setup(RELAY_PIN, GPIO.OUT)



_logger = logging.getLogger(__file__)
_logger.setLevel(logging.DEBUG)


def setup_server(description=None, context=None, cmdline=None):
    """Run server setup."""
    args = helper.get_commandline(server=True, description=description, cmdline=cmdline)
    if context:
        args.context = context
    datablock = None
    turnoff = None
    _logger.debug("### heloooo \n\n")
    if not args.context:
        _logger.info("### Create datastore")
        # The datastores only respond to the addresses that are initialized
        # If you initialize a DataBlock to addresses of 0x00 to 0xFF, a request to
        # 0x100 will respond with an invalid address exception.
        # This is because many devices exhibit this kind of behavior (but not all)
        if args.store == "sequential":
            # Continuing, use a sequential block without gaps.
            datablock = lambda : ModbusSequentialDataBlock(0x00, [17] * 100)  # pylint: disable=unnecessary-lambda-assignment
            ## setting the slave context to be false at certain coil
            turnoff = lambda : ModbusSequentialDataBlock(0x00, [False] * 100)
        elif args.store == "sparse":
            # Continuing, or use a sparse DataBlock which can have gaps
            datablock = lambda : ModbusSparseDataBlock({0x00: 0, 0x05: 1})  # pylint: disable=unnecessary-lambda-assignment
        elif args.store == "factory":
            # Alternately, use the factory methods to initialize the DataBlocks
            # or simply do not pass them to have them initialized to 0x00 on the
            # full address range::
            datablock = lambda : ModbusSequentialDataBlock.create()  # pylint: disable=unnecessary-lambda-assignment,unnecessary-lambda

        if args.slaves:
            # The server then makes use of a server context that allows the server
            # to respond with different slave contexts for different slave ids.
            # By default it will return the same context for every slave id supplied
            # (broadcast mode).
            # However, this can be overloaded by setting the single flag to False and
            # then supplying a dictionary of slave id to context mapping::
            #
            # The slave context can also be initialized in zero_mode which means
            # that a request to address(0-7) will map to the address (0-7).
            # The default is False which is based on section 4.4 of the
            # specification, so address(0-7) will map to (1-8)::
            context = {
                0x01: ModbusSlaveContext(
                    di=datablock(),
                    co=datablock(),
                    hr=datablock(),
                    ir=datablock(),
                ),
                0x02: ModbusSlaveContext(
                    di=datablock(),
                    co=datablock(),
                    hr=datablock(),
                    ir=datablock(),
                ),
                0x03: ModbusSlaveContext(
                    di=datablock(),
                    co=datablock(),
                    hr=datablock(),
                    ir=datablock(),
                    zero_mode=True,
                ),
            }
            single = False
        else:
            if not turnoff:
                context = ModbusSlaveContext(
                    di=datablock(), co=datablock(), hr=datablock(), ir=datablock()
                )
            else:
                context = ModbusSlaveContext(
                    di=datablock(), co=turnoff(), hr=datablock(), ir=datablock()
                )

            single = True

        # Build data storage
        args.context = ModbusServerContext(slaves=context, single=single)

    # ----------------------------------------------------------------------- #
    # initialize the server information
    # ----------------------------------------------------------------------- #
    # If you don't set this or any fields, they are defaulted to empty strings.
    # ----------------------------------------------------------------------- #
    args.identity = ModbusDeviceIdentification(
        info_name={
            "VendorName": "Pymodbus",
            "ProductCode": "PM",
            "VendorUrl": "https://github.com/pymodbus-dev/pymodbus/",
            "ProductName": "Pymodbus Server",
            "ModelName": "Pymodbus Server",
            "MajorMinorRevision": pymodbus_version,
        }
    )
    return args


async def run_async_server(args):
    """Run server."""
    txt = f"### start ASYNC server, listening on {args.port} - {args.comm}"
    _logger.info(txt)
    server = None
    _logger.debug("-> -> ARGS in run server " + args.comm)
    if args.comm == "tcp":
        address = (args.host if args.host else "", args.port if args.port else None)
        server = await StartAsyncTcpServer(
            context=args.context,  # Data storage
            identity=args.identity,  # server identify
            # TBD host=
            # TBD port=
            address=address,  # listen address
            # custom_functions=[],  # allow custom handling
            framer=args.framer,  # The framer strategy to use
            # ignore_missing_slaves=True,  # ignore request to a missing slave
            # broadcast_enable=False,  # treat slave_id 0 as broadcast address,
            # timeout=1,  # waiting time for request to complete
        )
    elif args.comm == "udp":
        address = (
            args.host if args.host else "127.0.0.1",
            args.port if args.port else None,
        )
        server = await StartAsyncUdpServer(
            context=args.context,  # Data storage
            identity=args.identity,  # server identify
            address=address,  # listen address
            # custom_functions=[],  # allow custom handling
            framer=args.framer,  # The framer strategy to use
            # ignore_missing_slaves=True,  # ignore request to a missing slave
            # broadcast_enable=False,  # treat slave_id 0 as broadcast address,
            # timeout=1,  # waiting time for request to complete
        )
    elif args.comm == "serial":
        # socat -d -d PTY,link=/tmp/ptyp0,raw,echo=0,ispeed=9600
        #             PTY,link=/tmp/ttyp0,raw,echo=0,ospeed=9600
        server = await StartAsyncSerialServer(
            context=args.context,  # Data storage
            identity=args.identity,  # server identify
            # timeout=1,  # waiting time for request to complete
            port=args.port,  # serial port
            # custom_functions=[],  # allow custom handling
            framer=args.framer,  # The framer strategy to use
            # stopbits=1,  # The number of stop bits to use
            # bytesize=8,  # The bytesize of the serial messages
            # parity="N",  # Which kind of parity to use
            baudrate=args.baudrate,  # The baud rate to use for the serial device
            # handle_local_echo=False,  # Handle local echo of the USB-to-RS485 adaptor
            # ignore_missing_slaves=True,  # ignore request to a missing slave
            # broadcast_enable=False,  # treat slave_id 0 as broadcast address,
            # strict=True,  # use strict timing, t1.5 for Modbus RTU
        )
    return server

async def shutdown_coil(args):
    """Continuously mirror coil 1's real value onto the physical relay/
    dashboard: True (the value master.py's keep-alive write sets, and what
    Ettercap's filter tampers with) means the turbine keeps running; False
    means stopped.

    This used to be one-directional (only ever called changeON(0), never
    changeON(1)) and read the wrong Modbus datastore entirely - see the
    two comments below for what was actually wrong and why.
    """
    while True:
        print("Waiting 5 seconds")
        # time.sleep() here would block the whole asyncio event loop -
        # including the Modbus server this coroutine runs alongside - for
        # the full 5 seconds on every iteration. asyncio.sleep() yields
        # control back to the loop instead.
        await asyncio.sleep(5)
        print("Reading value")
        # fx=1 reads the *coils* datastore - the one master.py's
        # write_coil(1, True) and Ettercap's filter actually touch. This
        # previously used fx=2 (discrete inputs), a separate datastore
        # nothing in this codebase ever writes to (it stays at its
        # initial placeholder value, 17, forever) - so this could never
        # actually detect anything, confirmed by testing: with fx=2, this
        # print statement's value never changed no matter what master
        # wrote or Ettercap altered.
        coil_value = args.context[0].getValues(1, 1, count=1)[0]
        print(f"coil 1 (keep-alive) reads: {coil_value}")
        # Previously only ever called changeON(0) here, never changeON(1)
        # - meaning once triggered (including a false trigger from reading
        # the coil's default False value before master's first write
        # lands, a real race at boot) the relay could never turn back on
        # even once the coil read True again. Mirroring the value both
        # ways makes this self-correcting.
        changeON(1 if coil_value else 0)


# mqtt's broker is viz's Mosquitto instance, reached the same way
# bh-intellirupter/dnpchallenge reach services outside their own compose
# project: via Docker's host-gateway hostname and viz's host-published
# port (see docker-compose.yml's extra_hosts entry for this service).
MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "host.docker.internal")
MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))

# viz's Mosquitto doesn't set `require_certificate true` (see
# viz/mosquitto.conf), so it never asks connecting clients for a client
# certificate - only the CA used to verify viz's own server certificate is
# needed here. See mqtt-certs/CERTS.md for why this is a copy of viz's
# actual CA rather than this module's own previously-mismatched one.
CA_CERT = os.path.join(os.path.dirname(__file__), "mqtt-certs", "ca.pem")


def changeON(on):
    # The dashboard being unreachable (viz not started yet, briefly down,
    # etc.) shouldn't be fatal here - this function runs before the Modbus
    # server even starts (see async_helper()), so letting an MQTT error
    # propagate would previously crash the whole slave before it ever
    # opened its Modbus port.
    try:
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        client.tls_set(ca_certs=CA_CERT)
        client.tls_insecure_set(True)  # skip hostname check; CA validation still applies
        client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, 60)
        client.loop_start()
        client.publish("zone1", on)
        client.loop_stop()
        client.disconnect()
    except OSError as exc:
        _logger.warning(f"couldn't reach MQTT broker at {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}: {exc}")

    if on == 0:
        GPIO.output(RELAY_PIN, GPIO.LOW)
        _logger.info("gpio off")
    else:
        GPIO.output(RELAY_PIN, GPIO.HIGH)
        _logger.info("gpio on")



    



async def async_helper():
    """Combine setup and run."""
    _logger.info("Starting...")
    changeON(1)
    
    run_args = setup_server(description="Run asynchronous server.")
    print("monitoring the coil")
    # run_async_server() does NOT return once the Modbus server starts -
    # pymodbus's StartAsyncTcpServer() awaits the server's serve-forever
    # loop internally, for the lifetime of the process. Previously this
    # was `await run_async_server(run_args)` followed by
    # `shutdown_coil(run_args)` (missing its own `await` too) - meaning
    # shutdown_coil() could never even start, since the line before it
    # never finishes. Confirmed directly: with the old code, shutdown_coil
    # never printed anything even minutes after startup, despite the
    # Modbus server itself working fine. asyncio.gather() runs both
    # concurrently instead of one-after-the-other.
    await asyncio.gather(run_async_server(run_args), shutdown_coil(run_args))

if __name__ == "__main__":
    asyncio.run(async_helper(), debug=True)
