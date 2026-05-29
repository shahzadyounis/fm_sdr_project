import argparse
import socket
import struct
import sys

import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None

HEADER_FMT = ">4sIIHH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)


def main():
    parser = argparse.ArgumentParser(description="UDP audio receiver for FM transmitter packets")
    parser.add_argument("--host", default="0.0.0.0", help="Local bind address")
    parser.add_argument("--port", type=int, default=5005, help="UDP port to listen on")
    parser.add_argument("--audio-rate", type=int, default=8000, help="Expected audio sample rate")
    args = parser.parse_args()

    print(f"Listening for UDP packets on {args.host}:{args.port}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))

    stream = None
    if sd is not None:
        try:
            stream = sd.OutputStream(
                samplerate=args.audio_rate,
                channels=1,
                dtype="int16",
                latency="low",
            )
            stream.start()
            print(f"Audio playback enabled at {args.audio_rate} Hz")
        except Exception as exc:
            print(f"Warning: sounddevice playback unavailable: {exc}")
            stream = None
    else:
        print("Warning: sounddevice package not installed. Audio playback disabled.")

    try:
        while True:
            packet, addr = sock.recvfrom(65536)
            if len(packet) < HEADER_SIZE:
                continue

            header = packet[:HEADER_SIZE]
            payload = packet[HEADER_SIZE:]
            magic, packet_id, payload_len, audio_rate, channels = struct.unpack(
                HEADER_FMT, header
            )

            if magic != b"FMAU":
                print(f"Ignoring unknown packet type from {addr}")
                continue

            if payload_len != len(payload):
                print(
                    f"Bad packet length: expected {payload_len}, got {len(payload)} from {addr}"
                )
                continue

            audio_data = np.frombuffer(payload, dtype=np.int16)

            print(
                f"RX packet={packet_id} from={addr[0]}:{addr[1]} samples={len(audio_data)} rate={audio_rate} channels={channels}"
            )

            if stream is not None:
                if audio_rate != args.audio_rate:
                    print(
                        f"Warning: packet audio_rate {audio_rate} differs from configured {args.audio_rate}."
                    )
                try:
                    stream.write(audio_data)
                except Exception as exc:
                    print(f"Audio output error: {exc}")

    except KeyboardInterrupt:
        print("Stopping receiver")

    finally:
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        sock.close()


if __name__ == "__main__":
    main()
