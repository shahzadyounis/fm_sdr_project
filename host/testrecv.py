import socket
import struct
import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None


HOST = "0.0.0.0"      # Listen on all interfaces
PORT = 5005           # Must match transmitter port
BUFFER_SIZE = 65536


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORT))

    print(f"Listening for audio stream on {HOST}:{PORT}")

    if sd is None:
        print("ERROR: sounddevice not installed")
        print("Install with: pip install sounddevice")
        return

    stream = None

    try:
        while True:
            data, addr = sock.recvfrom(BUFFER_SIZE)

            # Header size:
            # >4sIIHH
            # magic(4) + packet_id(4) + payload_len(4)
            # + audio_rate(2) + channels(2)
            if len(data) < 16:
                continue

            header = data[:16]
            payload = data[16:]

            magic, packet_id, payload_len, audio_rate, channels = struct.unpack(
                ">4sIIHH",
                header
            )

            if magic != b"FMAU":
                print("Invalid packet")
                continue

            audio_samples = np.frombuffer(payload, dtype=np.int16)

            print(
                f"RX Packet={packet_id} "
                f"Samples={len(audio_samples)} "
                f"Rate={audio_rate} "
                f"From={addr[0]}"
            )

            # Create stream once
            if stream is None:
                stream = sd.OutputStream(
                    samplerate=audio_rate,
                    channels=channels,
                    dtype="int16",
                    blocksize=len(audio_samples)
                )
                stream.start()
                print("Audio playback started")

            # Play audio
            stream.write(audio_samples)

    except KeyboardInterrupt:
        print("\nStopping receiver...")

    finally:
        if stream is not None:
            stream.stop()
            stream.close()

        sock.close()


if __name__ == "__main__":
    main()