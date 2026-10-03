#!/usr/bin/env python3

import argparse
import selectors
import socket
import struct
import time


TELEMETRY_BASE = 0x100
FAULT_ID = 0x1F0

NOISE_LO = 0x200
NOISE_HI = 0x2FF

DIAG_BASE = 0x6F0
NUM_MODULES = 4

MAX_DIAG_LEN = 128
DIAG_TIMEOUT = 0.15

# Linux struct can_frame:
# can_id: uint32
# can_dlc: uint8
# padding: 3 bytes
# data: 8 bytes
FRAME_FMT = "=IB3x8s"
FRAME_SIZE = struct.calcsize(FRAME_FMT)


def open_can_socket(interface):
    sock = socket.socket(
        socket.AF_CAN,
        socket.SOCK_RAW,
        socket.CAN_RAW
    )

    sock.bind((interface,))

    return sock


def unpack_can_frame(frame):
    can_id, dlc, data = struct.unpack(
        FRAME_FMT,
        frame
    )

    # Eliminar flags de SocketCAN
    can_id &= 0x1FFFFFFF

    return can_id, dlc, data[:dlc]


def decode_telemetry(can_id, data):
    """
    Payload:
        uint16 voltage_raw
        uint16 current_raw
        uint8  temp_raw
        uint8  status
        uint16 seq
    """

    if len(data) < 8:
        print(
            f"[TELEMETRY] trama demasiado corta "
            f"ID=0x{can_id:03X}"
        )
        return

    v_raw, c_raw, t_raw, status, seq = struct.unpack(
        "<HHBBH",
        data[:8]
    )

    voltage = v_raw * 0.1
    current = c_raw * 0.01
    temperature = t_raw - 40

    module = can_id - TELEMETRY_BASE

    enabled = bool(
        status & 0x01
    )

    fault = bool(
        status & 0x02
    )

    print(
        f"[TELEMETRY] "
        f"module={module} "
        f"id=0x{can_id:03X} "
        f"seq={seq:5d} "
        f"V={voltage:7.1f} V "
        f"I={current:7.2f} A "
        f"T={temperature:4d} C "
        f"enabled={enabled} "
        f"fault={fault}"
    )


def decode_fault(data):
    if len(data) < 2:
        print(
            "[FAULT] trama demasiado corta"
        )
        return

    module = data[0]
    code = data[1]

    print(
        f"[FAULT] "
        f"module={module} "
        f"code={code}"
    )


class DiagnosticReassembler:

    def __init__(self):
        # Un contexto independiente por CAN ID
        self.contexts = {}

    def cleanup_timeouts(self):
        now = time.monotonic()

        expired = []

        for can_id, ctx in self.contexts.items():

            elapsed = (
                now
                - ctx["last_time"]
            )

            if elapsed > DIAG_TIMEOUT:
                expired.append(
                    can_id
                )

        for can_id in expired:

            ctx = self.contexts.pop(
                can_id
            )

            print(
                f"[DIAG] timeout "
                f"id=0x{can_id:03X} "
                f"received={len(ctx['buffer'])}/"
                f"{ctx['expected_len']}"
            )

    def process(self, can_id, data):

        if not data:
            return

        pci_type = (
            data[0] >> 4
        )

        if pci_type == 0x1:

            self.process_first_frame(
                can_id,
                data
            )

        elif pci_type == 0x2:

            self.process_consecutive_frame(
                can_id,
                data
            )

        else:

            print(
                f"[DIAG] unsupported PCI "
                f"id=0x{can_id:03X} "
                f"type=0x{pci_type:X}"
            )

    def process_first_frame(
        self,
        can_id,
        data
    ):

        if len(data) < 8:

            print(
                f"[DIAG] invalid First Frame "
                f"id=0x{can_id:03X}"
            )

            return

        total_len = (
            ((data[0] & 0x0F) << 8)
            | data[1]
        )

        # Si había una transferencia activa,
        # un nuevo FF reinicia ese contexto.
        if can_id in self.contexts:

            old = self.contexts[
                can_id
            ]

            print(
                f"[DIAG] restart "
                f"id=0x{can_id:03X} "
                f"old={len(old['buffer'])}/"
                f"{old['expected_len']}"
            )

            del self.contexts[
                can_id
            ]

        if total_len <= 6:

            print(
                f"[DIAG] invalid FF length "
                f"id=0x{can_id:03X} "
                f"len={total_len}"
            )

            return

        if total_len > MAX_DIAG_LEN:

            print(
                f"[DIAG] oversized message rejected "
                f"id=0x{can_id:03X} "
                f"len={total_len}"
            )

            return

        first_payload = (
            data[2:8]
        )

        self.contexts[
            can_id
        ] = {
            "expected_len": total_len,
            "buffer": bytearray(
                first_payload
            ),
            "next_seq": 1,
            "last_time": time.monotonic(),
        }

        print(
            f"[DIAG] FF "
            f"id=0x{can_id:03X} "
            f"len={total_len}"
        )

        self.check_complete(
            can_id
        )

    def process_consecutive_frame(
        self,
        can_id,
        data
    ):

        if can_id not in self.contexts:

            seq = (
                data[0] & 0x0F
            )

            print(
                f"[DIAG] orphan CF ignored "
                f"id=0x{can_id:03X} "
                f"seq={seq}"
            )

            return

        ctx = self.contexts[
            can_id
        ]

        seq = (
            data[0] & 0x0F
        )

        expected = ctx[
            "next_seq"
        ]

        if seq != expected:

            print(
                f"[DIAG] sequence error "
                f"id=0x{can_id:03X} "
                f"expected={expected} "
                f"received={seq} "
                f"-> abort"
            )

            del self.contexts[
                can_id
            ]

            return

        payload = (
            data[1:8]
        )

        remaining = (
            ctx["expected_len"]
            - len(ctx["buffer"])
        )

        ctx["buffer"].extend(
            payload[:remaining]
        )

        ctx["next_seq"] = (
            ctx["next_seq"] + 1
        ) & 0x0F

        ctx["last_time"] = (
            time.monotonic()
        )

        print(
            f"[DIAG] CF "
            f"id=0x{can_id:03X} "
            f"seq={seq} "
            f"bytes={len(ctx['buffer'])}/"
            f"{ctx['expected_len']}"
        )

        self.check_complete(
            can_id
        )

    def check_complete(
        self,
        can_id
    ):

        if can_id not in self.contexts:
            return

        ctx = self.contexts[
            can_id
        ]

        if (
            len(ctx["buffer"])
            < ctx["expected_len"]
        ):
            return

        payload = bytes(
            ctx["buffer"][
                :ctx["expected_len"]
            ]
        )

        del self.contexts[
            can_id
        ]

        try:

            text = payload.decode(
                "ascii"
            )

        except UnicodeDecodeError:

            text = payload.decode(
                "ascii",
                errors="replace"
            )

        print(
            "\n"
            "========================================\n"
            "[DIAG COMPLETE]\n"
            f"CAN ID : 0x{can_id:03X}\n"
            f"TEXT   : {text}\n"
            "========================================\n"
        )


def is_telemetry(can_id):

    return (
        TELEMETRY_BASE
        <= can_id
        < TELEMETRY_BASE + NUM_MODULES
    )


def is_diagnostic(can_id):

    return (
        DIAG_BASE
        <= can_id
        < DIAG_BASE + NUM_MODULES
    )


def process_frame(
    frame,
    diag,
    show_noise
):

    if len(frame) != FRAME_SIZE:

        print(
            f"[WARN] invalid frame size: "
            f"{len(frame)}"
        )

        return

    can_id, dlc, data = (
        unpack_can_frame(
            frame
        )
    )

    if is_telemetry(
        can_id
    ):

        decode_telemetry(
            can_id,
            data
        )

    elif can_id == FAULT_ID:

        decode_fault(
            data
        )

    elif is_diagnostic(
        can_id
    ):

        diag.process(
            can_id,
            data
        )

    elif (
        NOISE_LO
        <= can_id
        <= NOISE_HI
    ):

        if show_noise:

            print(
                f"[NOISE] "
                f"id=0x{can_id:03X} "
                f"dlc={dlc} "
                f"data={data.hex(' ')}"
            )

    else:

        print(
            f"[UNKNOWN] "
            f"id=0x{can_id:03X} "
            f"dlc={dlc} "
            f"data={data.hex(' ')}"
        )


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Non-blocking CAN receiver "
            "using Python standard library only"
        )
    )

    parser.add_argument(
        "--iface",
        default="vcan0",
        help=(
            "SocketCAN interface, "
            "default: vcan0"
        )
    )

    parser.add_argument(
        "--show-noise",
        action="store_true",
        help="Print noise frames"
    )

    parser.add_argument(
        "--poll-timeout",
        type=float,
        default=0.05,
        help=(
            "Selector timeout in seconds, "
            "default: 0.05"
        )
    )

    args = parser.parse_args()

    sock = open_can_socket(
        args.iface
    )

    # Convertimos el socket a no bloqueante.
    sock.setblocking(
        False
    )

    diag = (
        DiagnosticReassembler()
    )

    selector = (
        selectors.DefaultSelector()
    )

    selector.register(
        sock,
        selectors.EVENT_READ
    )

    print(
        f"[Receiver] "
        f"listening on {args.iface}"
    )

    print(
        f"[Receiver] "
        f"non-blocking mode, "
        f"poll_timeout="
        f"{args.poll_timeout}s"
    )

    running = True

    try:

        while running:

            # Espera como máximo poll_timeout.
            # Nunca queda bloqueado
            # indefinidamente esperando CAN.
            events = selector.select(
                timeout=args.poll_timeout
            )

            # Esto se ejecuta incluso si
            # no llega ninguna trama.
            diag.cleanup_timeouts()

            for key, mask in events:

                if (
                    mask
                    & selectors.EVENT_READ
                ):

                    # Leemos todas las tramas
                    # que ya estén disponibles.
                    #
                    # Debido a setblocking(False),
                    # recv() nunca espera:
                    # cuando se vacía la cola
                    # lanza BlockingIOError.
                    while True:

                        try:

                            frame = (
                                sock.recv(
                                    FRAME_SIZE
                                )
                            )

                        except BlockingIOError:

                            # No quedan más
                            # tramas disponibles.
                            break

                        except OSError as exc:

                            print(
                                f"[ERROR] "
                                f"socket recv failed: "
                                f"{exc}"
                            )

                            running = False
                            break

                        process_frame(
                            frame,
                            diag,
                            args.show_noise
                        )

    except KeyboardInterrupt:

        print(
            "\n[Receiver] stopped"
        )

    finally:

        try:

            selector.unregister(
                sock
            )

        except Exception:
            pass

        selector.close()
        sock.close()


if __name__ == "__main__":
    main()
