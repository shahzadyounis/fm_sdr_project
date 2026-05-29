import socket
import pyaudio
import numpy as np
import threading
import queue

UDP_PORT = 12345
AUDIO_RATE = 48000          # Must match receiver's AUDIO_RATE
CHUNK_SIZE = 960            # Must match receiver's audio packet size
CHANNELS = 1

class AudioPlayer:
    def __init__(self, rate, channels, chunk_size):
        self.rate = rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.queue = queue.Queue(maxsize=50)
        self.running = True
        self.p = pyaudio.PyAudio()
        self.stream = self.p.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=rate,
            output=True,
            frames_per_buffer=chunk_size
        )
        threading.Thread(target=self._play, daemon=True).start()

    def _play(self):
        while self.running:
            try:
                data = self.queue.get(timeout=0.1)
                self.stream.write(data.tobytes())
            except queue.Empty:
                # Send silence
                silence = np.zeros(self.chunk_size, dtype=np.int16)
                self.stream.write(silence.tobytes())
            except Exception as e:
                print(f"Play error: {e}")

    def add(self, audio):
        try:
            self.queue.put_nowait(audio)
        except queue.Full:
            pass  # drop oldest if too slow

    def stop(self):
        self.running = False
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', UDP_PORT))
    player = AudioPlayer(AUDIO_RATE, CHANNELS, CHUNK_SIZE)
    print(f"Listening on port {UDP_PORT}...")
    try:
        while True:
            data, _ = sock.recvfrom(65535)
            audio = np.frombuffer(data, dtype=np.int16)
            if len(audio) == CHUNK_SIZE:
                player.add(audio)
    except KeyboardInterrupt:
        player.stop()
        sock.close()

if __name__ == "__main__":
    main()