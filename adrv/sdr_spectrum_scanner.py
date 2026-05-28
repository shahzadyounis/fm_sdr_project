#!/usr/bin/env python3
"""
sdr_spectrum_scanner.py - Fixed for AD9364 API
"""

import adi
import numpy as np
import time
import sys
from scipy.signal import find_peaks

def create_sdr(uri="ip:192.168.18.50"):
    """Initialize the ADRV9364 device connection."""
    try:
        sdr = adi.ad9364(uri=uri)
        print(f"Connected to SDR at {uri}")
        return sdr
    except Exception as e:
        print(f"Failed to connect to SDR: {e}")
        sys.exit(1)

def configure_scan(sdr, center_freq, sample_rate=2e6, bandwidth=1e6):
    """
    Configure the SDR for a spectrum measurement at a specific center frequency.
    """
    # Set the RX center frequency
    sdr.rx_lo = int(center_freq)
    
    # Set sample rate (must be done before other settings that depend on it)
    sdr.sample_rate = int(sample_rate)
    
    # Set the RF bandwidth of the front-end filter
    sdr.rx_rf_bandwidth = int(bandwidth)
    
    # Use manual gain for consistent power measurements
    sdr.gain_control_mode = 'manual'
    sdr.rx_hardwaregain = 40  # dB
    
    # Set buffer size for capturing samples (default is often 1024)
    sdr.rx_buffer_size = 4096
    
    # Allow time for hardware to settle
    time.sleep(0.05)

def measure_power(sdr):
    """Capture IQ samples and compute the average power in dBFS."""
    try:
        # Capture samples (rx() takes no arguments; buffer size is preset)
        samples = sdr.rx()
        
        # Convert to numpy array
        iq_samples = np.array(samples)
        
        # Compute average power
        avg_power = np.mean(np.abs(iq_samples) ** 2)
        
        # Convert to dBFS (avoid log(0))
        if avg_power > 0:
            power_dbfs = 10 * np.log10(avg_power)
        else:
            power_dbfs = -120
        
        return power_dbfs
    except Exception as e:
        print(f"Error measuring power: {e}")
        return -120

def scan_spectrum(sdr, start_freq, end_freq, step_size=200e3, sample_rate=2e6, bandwidth=1e6):
    """
    Sweep across frequency range and collect power measurements.
    Returns lists of frequencies and powers.
    """
    frequencies = np.arange(start_freq, end_freq, step_size)
    powers = []
    
    total_steps = len(frequencies)
    print(f"Scanning {total_steps} frequencies from {start_freq/1e6:.1f} to {end_freq/1e6:.1f} MHz...")
    
    for i, freq in enumerate(frequencies):
        # Configure SDR for this frequency
        configure_scan(sdr, freq, sample_rate, bandwidth)
        
        # Measure power
        power = measure_power(sdr)
        powers.append(power)
        
        # Print progress every 10 steps or at the end
        if (i + 1) % 10 == 0 or i == total_steps - 1:
            print(f"  Progress: {i+1}/{total_steps} - {freq/1e6:.1f} MHz: {power:.1f} dBFS")
    
    return frequencies, powers

def find_strongest_channels(frequencies, powers, num_channels=5, min_power_threshold=-80):
    """
    Find the strongest channels using peak detection.
    Returns list of (frequency, power) sorted by power descending.
    """
    powers_array = np.array(powers)
    
    # Find peaks (local maxima) above threshold and with minimum distance
    peaks, _ = find_peaks(powers_array, height=min_power_threshold, distance=5)
    
    candidates = [(frequencies[p], powers_array[p]) for p in peaks]
    candidates.sort(key=lambda x: x[1], reverse=True)
    
    return candidates[:num_channels]

def main():
    # Connection settings (update to your board's IP)
    BOARD_IP = "192.168.18.50"  # Your board's IP
    
    # Frequency range (FM broadcast band)
    FM_START = 88e6
    FM_END = 108e6
    STEP_SIZE = 200e3   # 200 kHz steps
    
    # Initialize SDR
    sdr = create_sdr(uri=f"ip:{BOARD_IP}")
    
    # Perform spectrum scan
    frequencies, powers = scan_spectrum(
        sdr,
        start_freq=FM_START,
        end_freq=FM_END,
        step_size=STEP_SIZE,
        sample_rate=2e6,
        bandwidth=1e6
    )
    
    # Find strongest channels
    strong_channels = find_strongest_channels(frequencies, powers, num_channels=5)
    
    print("\n=== Spectrum Scan Complete ===")
    print(f"{'Frequency (MHz)':<15} {'Power (dBFS)':<15}")
    print("-" * 30)
    for freq, power in zip(frequencies, powers):
        print(f"{freq/1e6:<15.1f} {power:<15.1f}")
    
    print("\n=== Strongest Channels Found ===")
    for idx, (freq, power) in enumerate(strong_channels):
        print(f"{idx+1}. {freq/1e6:.3f} MHz - {power:.1f} dBFS")
    
    # Save the best channel
    if strong_channels:
        best_freq = strong_channels[0][0]
        with open("selected_channel.txt", "w") as f:
            f.write(str(best_freq))
        print(f"\nBest channel: {best_freq/1e6:.3f} MHz")
        print("Selected frequency saved to 'selected_channel.txt'")
    else:
        print("\nNo strong channels found. Try adjusting gain or antenna.")
    
    # Optionally plot (if matplotlib installed)
    try:
        import matplotlib.pyplot as plt
        plt.figure(figsize=(12, 6))
        plt.plot(frequencies/1e6, powers)
        plt.xlabel('Frequency (MHz)')
        plt.ylabel('Power (dBFS)')
        plt.title('FM Band Spectrum Scan')
        plt.grid(True)
        plt.savefig('spectrum_scan.png')
        print("Spectrum plot saved to 'spectrum_scan.png'")
    except ImportError:
        print("matplotlib not available - skipping plot")

if __name__ == "__main__":
    main()