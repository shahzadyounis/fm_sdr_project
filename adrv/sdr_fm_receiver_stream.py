#!/usr/bin/env python3
"""
Optimized FM receiver for ADRV9364 – real-time on ARM.
"""

import adi
import numpy as np
import threading
import queue
import socket
import time
import sys
import signal as sig
import scipy.signal as sp_signal

# ---------- Configuration (OPTIMIZED) ----------
BOARD_IP = "192.168.18.50"
RX_FREQ = 105.2e6                   # or loaded from file
SAMPLE_RATE_RX = 2.4e6              # 2.4 MHz
BANDWIDTH = 200e3
GAIN = 30                           # lower gain to avoid distortion

AUDIO_RATE = 48000                  # 48 kHz for clear audio
FM_DEVIATION = 50000                # try 75000 if too quiet
DEEMPHASIS_TC = 50e-6

UDP_IP = "192.168.18.42"
UDP_PORT = 12345

# Lightweight block sizes (20 ms of IQ data)
IQ_BLOCK_SIZE = 48000               # 48000 samples = 20 ms at 2.4 MHz
AUDIO_BLOCK_SIZE = int(IQ_BLOCK_SIZE * AUDIO_RATE / SAMPLE_RATE_RX)   # = 960 samples
IQ_QUEUE_SIZE = 3
AUDIO_QUEUE_SIZE = 5

# ---------- Fast resampling (linear interpolation) ----------
def fast_resample(audio, old_fs, new_fs):
    """Linear interpolation resampling – very fast, no FFT."""
    old_len = len(audio)
    new_len = int(old_len * new_fs / old_fs)
    indices = np.linspace(0, old_len - 1, new_len)
    return np.interp(indices, np.arange(old_len), audio)

# ---------- Signal processing (optimised) ----------
def design_filter(cutoff, fs, numtaps=101):
    nyq = fs / 2
    return sp_signal.firwin(numtaps, cutoff/nyq, window='hamming')

def fm_demodulate(iq, fs, deviation):
    phase = np.angle(iq)
    demod = np.diff(np.unwrap(phase)) * fs / (2 * np.pi)
    return demod / deviation

def apply_deemphasis(audio, fs, tau=50e-6):
    dt = 1/fs
    alpha = dt / (tau + dt)
    out = np.zeros_like(audio)
    out[0] = audio[0]
    for i in range(1, len(audio)):
        out[i] = alpha * audio[i] + (1 - alpha) * out[i-1]
    return out

def iq_to_audio(iq_samples, fs_rx, fs_audio, deviation, deemphasis_tau):
    # 1. Demodulate
    audio_raw = fm_demodulate(iq_samples, fs_rx, deviation)
    # 2. De‑emphasis
    audio_deemph = apply_deemphasis(audio_raw, fs_rx, deemphasis_tau)
    # 3. Low‑pass filter (15 kHz)
    lpf = design_filter(15000, fs_rx)
    audio_filtered = sp_signal.lfilter(lpf, 1.0, audio_deemph)
    # 4. Fast resampling (linear interpolation, much lighter than FFT)
    audio_resampled = fast_resample(audio_filtered, fs_rx, fs_audio)
    # 5. Normalise and convert to int16
    max_val = np.max(np.abs(audio_resampled))
    if max_val > 0:
        audio_resampled = audio_resampled / max_val * 0.9
    return np.int16(audio_resampled * 32767)

# ---------- UDP streamer ----------
class AudioStreamer:
    def __init__(self, dest_ip, dest_port):
        self.dest_ip = dest_ip
        self.dest_port = dest_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.packets_sent = 0

    def send(self, audio_data):
        try:
            self.sock.sendto(audio_data.tobytes(), (self.dest_ip, self.dest_port))
            self.packets_sent += 1
            if self.packets_sent % 50 == 0:
                print(f"Sent {self.packets_sent} UDP packets (each {len(audio_data)} samples)")
        except Exception as e:
            print(f"UDP send error: {e}")

    def close(self):
        self.sock.close()

# ---------- Threads ----------
def rx_thread(stop_event, iq_queue, sdr):
    print("RX thread started")
    total_samples = 0
    while not stop_event.is_set():
        try:
            iq = sdr.rx()
            iq_queue.put(iq, timeout=0.2)
            total_samples += len(iq)
            if total_samples % (IQ_BLOCK_SIZE * 100) == 0:
                print(f"Captured {total_samples} IQ samples")
        except queue.Full:
            # This is expected if processing is slightly slower – not fatal
            pass
        except Exception as e:
            print(f"RX error: {e}")
            time.sleep(0.1)
    print("RX thread stopped")

def proc_thread(stop_event, iq_queue, audio_queue, fs_rx, fs_audio):
    print("Processing thread started")
    proc_count = 0
    while not stop_event.is_set():
        try:
            iq = iq_queue.get(timeout=0.2)
            audio = iq_to_audio(iq, fs_rx, fs_audio, FM_DEVIATION, DEEMPHASIS_TC)
            audio_queue.put(audio, timeout=0.2)
            proc_count += 1
            if proc_count % 20 == 0:
                print(f"Processed {proc_count} blocks → audio length {len(audio)} samples")
        except queue.Empty:
            continue
        except Exception as e:
            print(f"Processing error: {e}")
    print("Processing thread stopped")

def stream_thread(stop_event, audio_queue, streamer):
    print("Streamer thread started")
    while not stop_event.is_set():
        try:
            audio = audio_queue.get(timeout=0.2)
            streamer.send(audio)
        except queue.Empty:
            continue
    print("Streamer thread stopped")

# ---------- Main ----------
def main():
    # Load saved frequency
    try:
        with open("selected_channel.txt", "r") as f:
            rx_freq = float(f.read().strip())
        print(f"Using saved channel: {rx_freq/1e6:.3f} MHz")
    except FileNotFoundError:
        rx_freq = RX_FREQ
        print(f"No saved channel, using default: {rx_freq/1e6:.3f} MHz")

    print("Initialising ADRV9364...")
    sdr = adi.ad9364(uri=f"ip:{BOARD_IP}")

    # Configure receiver
    sdr.rx_lo = int(rx_freq)
    sdr.sample_rate = int(SAMPLE_RATE_RX)
    sdr.rx_rf_bandwidth = int(BANDWIDTH)
    sdr.gain_control_mode = 'slow_attack'
    sdr.rx_hardwaregain = GAIN
    sdr.rx_enabled_channels = [0]
    sdr.rx_buffer_size = IQ_BLOCK_SIZE

    print(f"Receiver configured:\n"
          f"  Frequency: {rx_freq/1e6:.3f} MHz\n"
          f"  Sample rate: {SAMPLE_RATE_RX/1e6:.1f} MHz\n"
          f"  IQ block size: {IQ_BLOCK_SIZE} samples ({IQ_BLOCK_SIZE/SAMPLE_RATE_RX*1000:.1f} ms)\n"
          f"  Audio packet size: ~{AUDIO_BLOCK_SIZE} samples\n"
          f"  UDP destination: {UDP_IP}:{UDP_PORT}")

    iq_queue = queue.Queue(maxsize=IQ_QUEUE_SIZE)
    audio_queue = queue.Queue(maxsize=AUDIO_QUEUE_SIZE)
    streamer = AudioStreamer(UDP_IP, UDP_PORT)

    stop_event = threading.Event()

    threads = [
        threading.Thread(target=rx_thread, args=(stop_event, iq_queue, sdr)),
        threading.Thread(target=proc_thread, args=(stop_event, iq_queue, audio_queue, SAMPLE_RATE_RX, AUDIO_RATE)),
        threading.Thread(target=stream_thread, args=(stop_event, audio_queue, streamer)),
    ]
    for t in threads:
        t.start()

    def shutdown(signum, frame):
        print("\nShutting down...")
        stop_event.set()
        time.sleep(1)
        streamer.close()
        sys.exit(0)

    sig.signal(sig.SIGINT, shutdown)
    print("Receiver running. Press Ctrl+C to stop.")
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()