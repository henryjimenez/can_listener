#!/usr/bin/env python3
import argparse
import socket
import struct
import time
# Linux struct can_frame
#
# struct can_frame {
#     canid_t can_id;   // 4 bytes
#     __u8    can_dlc;  // 1 byte
#     __u8    __pad;
#     __u8    __res0;
#     __u8    __res1;
#     __u8    data[8];
# };
#
FRAME_FMT = "=IB3x8s"
FRAME_SIZE = struct.calcsize(FRAME_FMT)
# Flags SocketCAN
CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_SFF_MASK = 0x000007FF
CAN_EFF_MASK = 0x1FFFFFFF


def open_can_socket(interface):
    sock = socket.socket(
        socket.AF_CAN,
        socket.SOCK_RAW,
        socket.CAN_RAW
    )

    sock.bind((interface,))
    return sock


def ascii_view(data):
    """
    Convierte bytes a una representación ASCII.
    Los caracteres no imprimibles se muestran como '.'
    """

    return "".join(
        chr(b) if 32 <= b <= 126 else "."
        for b in data
    )


def decode_can_id(raw_can_id):
    is_extended = bool(raw_can_id & CAN_EFF_FLAG)
    is_rtr = bool(raw_can_id & CAN_RTR_FLAG)
    is_error = bool(raw_can_id & CAN_ERR_FLAG)

    if is_extended:
        can_id = raw_can_id & CAN_EFF_MASK
    else:
        can_id = raw_can_id & CAN_SFF_MASK

    return can_id, is_extended, is_rtr, is_error


def main():
    parser = argparse.ArgumentParser(
        description="Generic SocketCAN sniffer using Python standard library"
    )

    parser.add_argument(
        "--iface",
        default="vcan0",
        help="CAN interface (default: vcan0)"
    )

    parser.add_argument(
        "--relative-time",
        action="store_true",
        help="Show elapsed time instead of wall clock"
    )

    args = parser.parse_args()

    sock = open_can_socket(args.iface)

    start_time = time.monotonic()

    print()
    print(f"Listening on interface: {args.iface}")
    print(f"CAN frame size      : {FRAME_SIZE} bytes")
    print()
    print(
        "TIME              TYPE ID         DLC DATA                     ASCII"
    )
    print(
        "--------------------------------------------------------------------------"
    )

    try:
        while True:

            frame = sock.recv(FRAME_SIZE)

            if len(frame) != FRAME_SIZE:
                print(
                    f"[WARNING] Received invalid frame size: "
                    f"{len(frame)}"
                )
                continue

            raw_can_id, dlc, raw_data = struct.unpack(
                FRAME_FMT,
                frame
            )

            can_id, extended, rtr, error = decode_can_id(
                raw_can_id
            )

            data = raw_data[:dlc]

            if args.relative_time:
                timestamp = (
                    f"{time.monotonic() - start_time:10.6f}"
                )
            else:
                timestamp = time.strftime(
                    "%H:%M:%S"
                ) + f".{int((time.time() % 1) * 1000):03d}"

            if error:
                frame_type = "ERR"

            elif rtr:
                frame_type = "RTR"

            elif extended:
                frame_type = "EXT"

            else:
                frame_type = "STD"

            if extended:
                id_string = f"{can_id:08X}"
            else:
                id_string = f"{can_id:03X}"

            hex_data = " ".join(
                f"{byte:02X}"
                for byte in data
            )

            ascii_data = ascii_view(data)

            print(
                f"{timestamp:<17} "
                f"{frame_type:<4} "
                f"{id_string:<10} "
                f"{dlc:<3} "
                f"{hex_data:<24} "
                f"{ascii_data}"
            )
    except KeyboardInterrupt:
        print()
        print("Sniffer stopped.")

    finally:
        sock.close()
if __name__ == "__main__":
    main()
