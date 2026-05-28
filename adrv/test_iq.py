import adi
import numpy as np
sdr = adi.ad9364(uri="ip:192.168.18.50")
sdr.rx_lo = int(105.2e6)
sdr.sample_rate = 2400000
sdr.rx_buffer_size = 65536
sdr.rx()
iq = sdr.rx()
np.save("test_iq.npy", iq)
print("Saved IQ samples, mean power:", np.mean(np.abs(iq)**2))