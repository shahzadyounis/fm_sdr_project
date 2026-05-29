import asyncio
import struct
import numpy as np
from scipy import signal
import sounddevice as sd

# =========================
# CONFIG
# =========================
FS = 1_000_000
AUDIO_FS = 48000

FREQ_START = 88e6
FREQ_END   = 108e6
STEP       = 0.2e6   # 200 kHz step

audio_buffer = np.zeros(0, dtype=np.float32)

# =========================
# GLOBAL SELECTED FREQ
# =========================
best_freq = None

# =========================
# PARSE PACKET
# =========================
def parse_packet(data):

    if len(data) < 12:
        return None

    tag, pid, length = struct.unpack("4sII", data[:12])

    if tag != b"FMIQ":
        return None

    raw = data[12:12+length]

    iq = np.frombuffer(raw, dtype=np.int16)
    iq = iq.reshape(-1, 2)

    iq = (
        iq[:, 0].astype(np.float32)
        + 1j * iq[:, 1].astype(np.float32)
    ) / 32768.0

    return iq

# =========================
# FM POWER METRIC (SNR ESTIMATE)
# =========================
def compute_score(iq):

    # signal power
    p = np.mean(np.abs(iq)**2)

    # "activity" metric (FM varies a lot when station exists)
    diff = np.mean(np.abs(np.diff(np.angle(iq))))

    score = p * diff
    return score

# =========================
# SCAN FUNCTION (FAKE IQ STREAM SIMULATION HOOK)
# =========================
def scan_frequencies(sdr):

    best_score = 0
    best_f = FREQ_START

    print("\n🔍 Scanning FM band...\n")

    for f in np.arange(FREQ_START, FREQ_END, STEP):

        sdr.rx_lo = int(f)

        iq = np.asarray(sdr.rx(), dtype=np.complex64)

        iq = iq / 32768.0

        score = compute_score(iq)

        print(f"Freq={f/1e6:.2f} MHz | Score={score:.6f}")

        if score > best_score:
            best_score = score
            best_f = f

    print("\n🎯 BEST FREQUENCY FOUND:")
    print(f"{best_f/1e6:.2f} MHz | Score={best_score:.6f}")

    return best_f

# =========================
# FM DEMOD
# =========================
def fm_demod(iq):
    iq = iq / (np.abs(iq) + 1e-12)
    return np.angle(iq[1:] * np.conj(iq[:-1]))

# =========================
# DE-EMPHASIS
# =========================
def deemphasis(x, fs, tau=75e-6):
    a = np.exp(-1/(fs*tau))
    y = np.zeros_like(x)
    for i in range(1, len(x)):
        y[i] = a*y[i-1] + (1-a)*x[i]
    return y

# =========================
# PROCESS AUDIO
# =========================
def process(iq):

    global audio_buffer

    audio = fm_demod(iq)

    audio = signal.decimate(audio, 10, ftype="fir")
    audio = signal.decimate(audio, 10, ftype="fir")

    audio = deemphasis(audio, AUDIO_FS)

    audio = audio / (np.max(np.abs(audio)) + 1e-12)

    audio_buffer = np.concatenate([audio_buffer, audio])

# =========================
# AUDIO OUTPUT
# =========================
def audio_callback(outdata, frames, time, status):

    global audio_buffer

    if len(audio_buffer) < frames:
        outdata[:] = np.zeros((frames, 1), dtype=np.float32)
        return

    outdata[:, 0] = audio_buffer[:frames]
    audio_buffer = audio_buffer[frames:]

# =========================
# UDP RECEIVER
# =========================
class UDP(asyncio.DatagramProtocol):

    def datagram_received(self, data, addr):

        iq = parse_packet(data)
        if iq is None:
            return

        process(iq)

        print(f"RX IQ={len(iq)} | audio={len(audio_buffer)}")

# =========================
# MAIN
# =========================
async def main():

    import adi

    print("🚀 FM Auto Scan + Receiver")

    sdr = adi.ad9364("local:")

    sdr.sample_rate = FS
    sdr.rx_buffer_size = 8192
    sdr.gain_control_mode_chan0 = "slow_attack"
    sdr.rx_hardwaregain_chan0 = 30

    # -------------------------
    # STEP 1: SCAN BAND
    # -------------------------
    best = scan_frequencies(sdr)

    # -------------------------
    # STEP 2: LOCK FREQUENCY
    # -------------------------
    sdr.rx_lo = int(best)

    print(f"\n📻 Locked to {best/1e6:.2f} MHz\n")

    # -------------------------
    # AUDIO STREAM START
    # -------------------------
    stream = sd.OutputStream(
        samplerate=AUDIO_FS,
        channels=1,
        dtype="float32",
        callback=audio_callback,
        blocksize=1024
    )

    stream.start()

    loop = asyncio.get_running_loop()

    await loop.create_datagram_endpoint(
        UDP,
        local_addr=("0.0.0.0", 5005)
    )

    while True:
        await asyncio.sleep(1)

asyncio.run(main())