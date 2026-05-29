
import adi
import numpy as np
import socket
import struct
import argparse
import signal
import sys

# ============================================================
# ARGUMENTS
# ============================================================

parser = argparse.ArgumentParser()

parser.add_argument(
    "--host",
    type=str,
    default="192.168.18.42"
)

parser.add_argument(
    "--port",
    type=int,
    default=5005
)

parser.add_argument(
    "--freq",
    type=float,
    default=100.0,
    help="FM station in MHz"
)

args = parser.parse_args()

# ============================================================
# SDR CONFIG
# ============================================================

SAMPLE_RATE = int(1e6)
RF_BW       = int(200e3)
BUFFER_SIZE = 8192

# ============================================================
# UDP SOCKET
# ============================================================

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# ============================================================
# SDR INITIALIZATION
# ============================================================

print("Connecting to AD9364...")

sdr = adi.ad9364("local:")

sdr.sample_rate = SAMPLE_RATE

# Tune FM station
sdr.rx_lo = int(args.freq * 1e6)

# FM channel bandwidth
sdr.rx_rf_bandwidth = RF_BW

sdr.rx_buffer_size = BUFFER_SIZE

# Moderate gain
sdr.gain_control_mode_chan0 = "slow_attack"
sdr.rx_hardwaregain_chan0 = 20

print("\n========== SDR CONFIG ==========")
print(f"FM Station     : {args.freq} MHz")
print(f"Sample Rate    : {SAMPLE_RATE}")
print(f"RF Bandwidth   : {RF_BW}")
print(f"Buffer Size    : {BUFFER_SIZE}")
print("================================\n")

running = True

# ============================================================
# CLEAN EXIT
# ============================================================

def cleanup(sig=None, frame=None):

    global running

    running = False

    print("\nStopping...")

signal.signal(signal.SIGINT, cleanup)

# ============================================================
# STREAM LOOP
# ============================================================

packet_counter = 0

while running:

    try:

        iq = sdr.rx()

        iq = np.asarray(iq, dtype=np.complex64)

        # Normalize IQ
        iq /= 32768.0

        # Convert to interleaved int16
        i = np.int16(np.real(iq) * 32767)
        q = np.int16(np.imag(iq) * 32767)

        interleaved = np.empty(i.size * 2, dtype=np.int16)

        interleaved[0::2] = i
        interleaved[1::2] = q

        payload = interleaved.tobytes()

        # Custom header
        header = struct.pack(
            "4sI",
            b"IQFM",
            len(payload)
        )

        packet = header + payload

        sock.sendto(
            packet,
            (args.host, args.port)
        )

        packet_counter += 1

        print(
            f"Packet={packet_counter} "
            f"IQ={len(iq)} "
            f"Freq={args.freq} MHz"
        )

    except Exception as e:

        print("Streaming error:", e)

        break

# ============================================================
# CLEANUP
# ============================================================

try:
    sdr.rx_destroy_buffer()
except:
    pass

sock.close()

del sdr

print("Resources released.")

