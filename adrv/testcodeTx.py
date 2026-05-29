import argparse
import signal
import socket
import struct
import time

import adi
import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None


def db(value):
    return 10.0 * np.log10(value + 1e-12)


def design_lpf(cutoff_hz, fs_hz, taps=129):
    # Simple lowpass FIR filter for audio decimation
    nyq = fs_hz / 2.0
    cutoff = min(cutoff_hz, nyq * 0.99) / nyq
    x = np.arange(taps) - (taps - 1) / 2.0
    h = np.sinc(2.0 * cutoff * x)
    window = np.hamming(taps)
    h *= window
    h /= np.sum(h)
    return h


def fm_demodulate(iq):
    phase = np.angle(iq[1:] * np.conj(iq[:-1]))
    return phase


def compute_power_snr(iq):
    iq = iq - np.mean(iq)
    window = np.hanning(len(iq))
    spectrum = np.abs(np.fft.fftshift(np.fft.fft(iq * window))) ** 2
    peak = np.max(spectrum)
    noise = np.median(spectrum)
    power = np.mean(np.abs(iq) ** 2)
    return db(power), db(peak / (noise + 1e-12))


def scan_spectrum(sdr, start_mhz, stop_mhz, step_mhz, read_size=4096):
    scan_points = np.arange(start_mhz, stop_mhz + step_mhz / 2.0, step_mhz)
    results = []
    print("Scanning FM band from %.1f MHz to %.1f MHz..." % (start_mhz, stop_mhz))
    for freq_mhz in scan_points:
        sdr.rx_lo = int(freq_mhz * 1e6)
        time.sleep(0.05)
        _ = sdr.rx()
        iq = np.asarray(sdr.rx(), dtype=np.complex64)
        power_db, snr_db = compute_power_snr(iq)
        print("  %.1f MHz  power=%.1f dB   snr=%.1f dB" % (freq_mhz, power_db, snr_db))
        results.append((freq_mhz, power_db, snr_db))
    best = max(results, key=lambda x: x[2])
    return best


def build_packet(packet_id, audio_rate, audio_samples):
    payload = audio_samples.tobytes()
    header = struct.pack(
        ">4sIIHH",
        b"FMAU",
        packet_id,
        len(payload),
        int(audio_rate),
        1,
    )
    return header + payload


def run_transmitter(args):
    sdr = adi.ad9364("local:")
    sdr.sample_rate = int(args.sample_rate)
    sdr.rx_buffer_size = 8192
    sdr.rx_rf_bandwidth = int(args.rf_bw)
    sdr.gain_control_mode_chan0 = "slow_attack"
    sdr.rx_hardwaregain_chan0 = 35

    best_freq, best_power, best_snr = scan_spectrum(
        sdr,
        args.scan_start,
        args.scan_end,
        args.scan_step,
    )
    print(
        "Best candidate: %.1f MHz  power=%.1f dB  snr=%.1f dB" %
        (best_freq, best_power, best_snr)
    )

    sdr.rx_lo = int(best_freq * 1e6)
    time.sleep(0.1)
    for _ in range(3):
        _ = sdr.rx()

    packet_id = 0
    running = True
    audio_rate = int(args.audio_rate)
    decim = int(args.sample_rate // audio_rate)
    if args.sample_rate % audio_rate != 0:
        raise ValueError("sample-rate must be an integer multiple of audio-rate")
    lpf = design_lpf(audio_rate * 0.45, args.sample_rate, taps=129)
    audio_packet_samples = int(audio_rate * 0.1)
    audio_buffer = np.empty(0, dtype=np.int16)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def stop_handler(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop_handler)

    print("Tuned to FM %.1f MHz, streaming %d Hz audio to %s:%d" %
          (best_freq, audio_rate, args.host, args.port))

    try:
        while running:
            iq = np.asarray(sdr.rx(), dtype=np.complex64)
            iq = iq / 32768.0
            demod = fm_demodulate(iq)
            demod = np.convolve(demod, lpf, mode="same")
            audio = demod[::decim]
            audio = audio * 10000.0
            audio = np.clip(audio, -32767, 32767).astype(np.int16)
            audio_buffer = np.concatenate((audio_buffer, audio))

            while len(audio_buffer) >= audio_packet_samples:
                packet_audio = audio_buffer[:audio_packet_samples]
                audio_buffer = audio_buffer[audio_packet_samples:]
                packet = build_packet(packet_id, audio_rate, packet_audio)
                sock.sendto(packet, (args.host, args.port))
                print("TX %d | audio_samples=%d" % (packet_id, audio_packet_samples))
                packet_id += 1

    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        sdr.rx_destroy_buffer()
        print("Stopped transmitter")


def run_receiver(args):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    print("Listening on %s:%d" % (args.host, args.port))

    stream = None
    if sd is not None:
        try:
            stream = sd.OutputStream(
                samplerate=int(args.audio_rate), channels=1, dtype="int16"
            )
            stream.start()
        except Exception:
            stream = None
            print("sounddevice stream unavailable, audio playback disabled")
    else:
        print("sounddevice package not installed, audio playback disabled")

    try:
        while True:
            data, addr = sock.recvfrom(65536)
            if len(data) < 16:
                continue
            magic, packet_id, payload_len, audio_rate, channels = struct.unpack(
                ">4sIIHH", data[:16]
            )
            if magic != b"FMAU":
                continue
            audio_data = np.frombuffer(data[16:], dtype=np.int16)
            print("RX %d | host=%s audio_samples=%d" % (packet_id, addr[0], len(audio_data)))
            if stream is not None:
                try:
                    stream.write(audio_data)
                except Exception:
                    pass
    except KeyboardInterrupt:
        pass
    finally:
        if stream is not None:
            stream.stop()
            stream.close()
        sock.close()
        print("Stopped receiver")


def main():
    parser = argparse.ArgumentParser(description="ADRV FM receiver and UDP audio streamer")
    parser.add_argument("--mode", choices=["tx", "rx"], default="tx")
    parser.add_argument("--host", default="192.168.18.42")
    parser.add_argument("--port", type=int, default=5005)
    parser.add_argument("--scan-start", type=float, default=88.0)
    parser.add_argument("--scan-end", type=float, default=108.0)
    parser.add_argument("--scan-step", type=float, default=0.5)
    parser.add_argument("--sample-rate", type=int, default=2400000)
    parser.add_argument("--rf-bw", type=float, default=200e3)
    parser.add_argument("--audio-rate", type=int, default=8000)
    args = parser.parse_args()

    if args.sample_rate < 521000:
        parser.error("sample-rate must be at least 521000 for this ADRV9364 system")

    if args.mode == "tx":
        run_transmitter(args)
    else:
        run_receiver(args)


if __name__ == "__main__":
    main()
