import asyncio
import logging
import os
import math
import av
import numpy as np

# from janus_client.transport import JanusTransportHTTP
from janus_client import JanusSession, JanusAudioBridgePlugin
from aiortc import MediaStreamTrack
from aiortc.contrib.media import MediaPlayer, MediaRecorder

format = "%(asctime)s: %(message)s"
logging.basicConfig(format=format, level=logging.INFO, datefmt="%H:%M:%S")
logger = logging.getLogger()

JANUS_BASE_URL = "wss://somewhere/janus"  # Replace with your Janus server URL
JANUS_API_TOKEN = "secret_token"  # Replace with your actual token
ROOM_ID = "1234" # Replace with your actual room ID
DISPLAY_NAME = "Test User"
PLAY_FROM = "./sample.mp3"  # Path to the audio file to play
RECORD_TO = "./echo.mp3"  # Path to save the recorded audio

recorder: MediaRecorder = None

class SineAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, frequency=440, sample_rate=48000):
        super().__init__()
        self.sample_rate = sample_rate
        self.frequency = frequency
        self.phase = 0

    async def recv(self):
        frame = av.AudioFrame(format="s16", layout="mono", samples=960)
        tone = np.array([
            int(32767 * math.sin(2 * math.pi * self.frequency * (self.phase + i) / self.sample_rate))
            for i in range(960)
        ], dtype=np.int16)
        frame.planes[0].update(tone.tobytes())
        self.phase += 960
        frame.sample_rate = self.sample_rate
        return frame

async def FileAudioTrack(play_from: str) -> MediaStreamTrack:
    player = MediaPlayer(play_from)
    if player and player.audio:
        return player.audio
    else:
        logger.error(f"⚠️ Failed to create audio track from {play_from}")
        return None

async def on_media_receive()-> None:
    """
    This method will be called when the PC receives media.
    It can be used to start a recorder.
    It may be called multiple times with no input.
    """
    global recorder
    if not recorder and RECORD_TO:
        recorder = MediaRecorder(RECORD_TO)
        await recorder.start()
        logger.info(f"✅ Recorder started, saving to {RECORD_TO}")
    else:
        logger.info("🔔 Media received callback from plugin!")

async def on_track_created(track: MediaStreamTrack)-> None:
    """
    This method will be called when the PC receives media.
    It can be used to start a recorder.
    It may be called multiple times with no input.
    """
    global recorder
    if recorder and track.kind == "audio":
        recorder.addTrack(track)

async def on_stream_ended()-> None:
    """
    This method will be called when the stream ends.
    It can be used to stop the recorder.
    """
    global recorder
    if recorder:
        await recorder.stop()
        logger.info(f"✅ Recorder stopped, saved to {RECORD_TO}")
        recorder = None

async def main():
    # Create session
    session = JanusSession(base_url=JANUS_BASE_URL, token=JANUS_API_TOKEN)
    logger.info("✅ session created")

    # Create plugin
    plugin_handle = JanusAudioBridgePlugin(on_media_receive_callback=on_media_receive,
                                            on_track_created_callback=on_track_created,
                                            on_stream_ended_callback=on_stream_ended)
    logger.info("✅ plugin created")

    # Attach to Janus session
    await plugin_handle.attach(session=session)
    logger.info("✅ plugin attached")

    # Check if room exists
    room_exists = await plugin_handle.exists(ROOM_ID)
    if not room_exists:
        logger.error("❌ room does not exist")
        return
    logger.info("✅ room exists")

    # Join Room
    await plugin_handle.join(ROOM_ID, DISPLAY_NAME, JANUS_API_TOKEN)
    logger.info("✅ joined room")

    if os.path.exists(RECORD_TO):
        os.remove(RECORD_TO)

    # Publish our stream
    await plugin_handle.publish_stream([
        await FileAudioTrack(play_from=PLAY_FROM)
    ])
    logger.info("✅ stream published")

    # Ping Janus to check connection
    await session.transport.ping()

    # Wait awhile then hangup
    await asyncio.sleep(15)
    await plugin_handle.close_stream()
        
    # Destroy everything
    if recorder:
        await recorder.stop()
    await plugin_handle.destroy()
    await session.destroy()

    logger.info("✅ test completed")

if __name__ == "__main__":
    try:
        # asyncio.run(main=main())
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        pass
