<<<<<<< HEAD

=======
>>>>>>> 198c24c (These are the updated codes so for)
import adi
import numpy as np
import socket
import struct
import argparse
import signal
import time

# =========================
# ARGS
# =========================
parser = argparse.ArgumentParser()
parser.add_argument("--freq", type=float, default=99.0)
parser.add_argument("--host", type=str, default="192.168.18.42")
parser.add_argument("--port", type=int, default=5005)
args = parser.parse_args()

# =========================
# UDP
# =========================
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# =========================
# SDR
# =========================
sdr = adi.ad9364("local:")

FS = 1_000_000

sdr.sample_rate = FS
sdr.rx_lo = int(args.freq * 1e6)
sdr.rx_rf_bandwidth = int(200e3)
sdr.rx_buffer_size = 8192
sdr.gain_control_mode_chan0 = "slow_attack"
sdr.rx_hardwaregain_chan0 = 35

print(f"Tuned to FM {args.freq} MHz")

packet_id = 0
running = True

def stop(*_):
    global running
    running = False

signal.signal(signal.SIGINT, stop)

# warm-up (IMPORTANT)
for _ in range(3):
    _ = sdr.rx()

try:
    while running:

        iq = np.asarray(sdr.rx(), dtype=np.complex64)

        iq = iq / 32768.0

        i = np.int16(np.real(iq) * 32767)
        q = np.int16(np.imag(iq) * 32767)

        payload_np = np.empty(len(iq) * 2, dtype=np.int16)
        payload_np[0::2] = i
        payload_np[1::2] = q

        payload = payload_np.tobytes()

        header = struct.pack("4sII", b"FMIQ", packet_id, len(payload))

        packet = header + payload

        sock.sendto(packet, (args.host, args.port))

        print(f"TX {packet_id} | IQ={len(iq)}")

        packet_id += 1

        time.sleep(0.01)

except KeyboardInterrupt:
    pass

<<<<<<< HEAD
sock.close()

del sdr

print("Resources released.")

=======
finally:
    sock.close()
    sdr.rx_destroy_buffer()
    print("Stopped TX")
>>>>>>> 198c24c (These are the updated codes so for)
