```python
import asyncio
import struct
import argparse

import numpy as np
from scipy import signal
import sounddevice as sd

# ============================================================
# PARAMETERS
# ============================================================

AUDIO_RATE = 48000

# ============================================================
# PARSE UDP PACKET
# ============================================================

def parse_packet(data):

    if len(data) < 8:
        return None

    tag, plen = struct.unpack_from(
        "4sI",
        data,
        0
    )

    raw = data[8:8 + plen]

    iq = np.frombuffer(
        raw,
        dtype=np.int16
    )

    iq = iq.reshape(-1, 2)

    complex_iq = (
        iq[:, 0].astype(np.float32)
        + 1j * iq[:, 1].astype(np.float32)
    ) / 32768.0

    return complex_iq

# ============================================================
# FM DEMODULATION
# ============================================================

def fm_demod(iq):

    # Quadrature discriminator
    phase = np.angle(
        iq[1:] * np.conj(iq[:-1])
    )

    return phase

# ============================================================
# AUDIO FILTER
# ============================================================

def audio_filter(audio, fs):

    cutoff = 15000

    taps = signal.firwin(
        101,
        cutoff,
        fs=fs
    )

    return signal.lfilter(
        taps,
        1.0,
        audio
    )

# ============================================================
# ASYNC UDP RECEIVER
# ============================================================

class UDPProtocol(asyncio.DatagramProtocol):

    def datagram_received(self, data, addr):

        try:

            iq = parse_packet(data)

            if iq is None:
                return

            # FM demodulation
            audio = fm_demod(iq)

            # Filter audio
            audio = audio_filter(
                audio,
                fs=1e6
            )

            # Decimate
            decimation = int(1e6 / AUDIO_RATE)

            audio = signal.decimate(
                audio,
                decimation,
                ftype='fir'
            )

            # Normalize
            audio /= np.max(
                np.abs(audio)
            ) + 1e-12

            # Play audio
            sd.play(
                audio,
                AUDIO_RATE,
                blocking=False
            )

            print(
                f"Audio samples: {len(audio)}"
            )

        except Exception as e:

            print("Processing error:", e)

# ============================================================
# MAIN
# ============================================================

async def main(host, port):

    print(f"Listening on {host}:{port}")

    loop = asyncio.get_running_loop()

    transport, protocol = await loop.create_datagram_endpoint(
        UDPProtocol,
        local_addr=(host, port)
    )

    while True:
        await asyncio.sleep(1)

# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=5005
    )

    args = parser.parse_args()

    asyncio.run(
        main(
            args.host,
            args.port
        )
    )
```
