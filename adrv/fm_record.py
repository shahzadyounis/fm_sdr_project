import time
import wave
import argparse

import adi
import numpy as np


def design_lpf(cutoff_hz, fs_hz, taps=257):
    nyq = fs_hz / 2.0
    cutoff = cutoff_hz / nyq

    x = np.arange(taps) - (taps - 1) / 2.0

    h = np.sinc(2 * cutoff * x)

    h *= np.hamming(taps)

    h /= np.sum(h)

    return h


def fm_demodulate(iq):
    phase = np.unwrap(np.angle(iq))
    demod = np.diff(phase)
    return demod


def save_wav(filename, audio, sample_rate):
    wf = wave.open(filename, 'wb')

    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(sample_rate)

    wf.writeframes(audio.tobytes())

    wf.close()


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument("--freq", type=float, default=101.0)
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--sample-rate", type=int, default=1920000)
    parser.add_argument("--audio-rate", type=int, default=48000)

    args = parser.parse_args()

    print("Initializing SDR...")

    sdr = adi.ad9364("local:")

    sdr.sample_rate = int(args.sample_rate)

    sdr.rx_lo = int(args.freq * 1e6)

    sdr.rx_rf_bandwidth = int(200e3)

    sdr.gain_control_mode_chan0 = "slow_attack"

    sdr.rx_buffer_size = 65536

    audio_rate = args.audio_rate

    decim = int(args.sample_rate // audio_rate)

    lpf = design_lpf(
        cutoff_hz=16000,
        fs_hz=args.sample_rate,
        taps=257
    )

    total_audio = []

    start = time.time()

    print(f"Recording FM {args.freq} MHz for {args.duration} seconds...")

    while (time.time() - start) < args.duration:

        iq = sdr.rx().astype(np.complex64)

        iq = iq / 32768.0

        demod = fm_demodulate(iq)

        filtered = np.convolve(
            demod,
            lpf,
            mode="same"
        )

        audio = filtered[::decim]

        # FM De-emphasis
        tau = 75e-6

        dt = 1.0 / audio_rate

        alpha = dt / (tau + dt)

        deemph = np.zeros_like(audio)

        for i in range(1, len(audio)):
            deemph[i] = deemph[i - 1] + alpha * (
                audio[i] - deemph[i - 1]
            )

        audio = deemph

        audio = audio / (np.max(np.abs(audio)) + 1e-9)

        audio = (audio * 28000).astype(np.int16)

        total_audio.append(audio)

        print(
            f"Captured {len(audio)} samples"
        )

    print("Combining audio...")

    final_audio = np.concatenate(total_audio)

    filename = "fm_recording.wav"

    save_wav(
        filename,
        final_audio,
        audio_rate
    )

    print(f"Saved {filename}")

    sdr.rx_destroy_buffer()


if __name__ == "__main__":
    main()
