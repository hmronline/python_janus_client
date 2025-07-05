import asyncio, logging, os, av, math, fractions, numpy as np
from aiortc import RTCPeerConnection
from aiortc.contrib.media import MediaStreamTrack, MediaPlayer, MediaRecorder
from janus_client import JanusSession, JanusAudioBridgePlugin

format = "%(asctime)s: %(message)s"
logging.basicConfig(format=format, level=logging.INFO, datefmt="%H:%M:%S")
logger = logging.getLogger()

JANUS_BASE_URL = "wss://somewhere/janus"  # Replace with your Janus server URL
JANUS_API_TOKEN = "secret_token"  # Replace with your actual token
ROOM_ID = "1234"  # Replace with your actual room ID
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
        self.samples = 960
        self._timestamp = 0

    async def recv(self):
        # logger.info("SineAudioTrack: Generating frame")
        frame = av.AudioFrame(format="s16", layout="mono", samples=self.samples)
        tone = np.array(
            [
                int(
                    32767
                    * math.sin(
                        2
                        * math.pi
                        * self.frequency
                        * (self.phase + i)
                        / self.sample_rate
                    )
                )
                for i in range(self.samples)
            ],
            dtype=np.int16,
        )
        frame.planes[0].update(tone.tobytes())
        self.phase += self.samples
        frame.sample_rate = self.sample_rate
        frame.pts = self._timestamp
        frame.time_base = fractions.Fraction(1, self.sample_rate)
        self._timestamp += self.samples
        return frame


class SilenceAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self):
        super().__init__()
        self.sample_rate = 48000
        self.samples = 960
        self.channels = 1
        self._timestamp = 0

    async def recv(self):
        # logger.info("SilenceAudioTrack: Generating frame")
        await asyncio.sleep(self.samples / self.sample_rate)
        frame = av.AudioFrame(format="s16", layout="mono", samples=self.samples)
        frame.sample_rate = self.sample_rate
        frame.pts = self._timestamp
        frame.time_base = fractions.Fraction(1, self.sample_rate)
        self._timestamp += self.samples
        for p in frame.planes:
            p.update(bytes(self.samples * 2))  # 2 bytes per sample for s16
        return frame


async def FileAudioTrack(play_from: str) -> MediaStreamTrack:
    player = MediaPlayer(play_from)
    if player and player.audio:
        return player.audio
    else:
        logger.error(f"❌ Failed to create audio track from {play_from}")
        return None


async def on_track_created(pc: RTCPeerConnection, track: MediaStreamTrack):
    """
    This method will be called when the PC receives media.
    It can be used to start a recorder.
    It may be called multiple times with no input.
    """
    global recorder
    if track.kind == "audio":
        logger.info("🔔 Receiving from Janus")
        if not recorder and RECORD_TO:
            if os.path.exists(RECORD_TO):
                os.remove(RECORD_TO)
            recorder = MediaRecorder(RECORD_TO)
        if recorder:
            logger.info("🔊 Adding track to recorder")
            recorder.addTrack(track)
        else:
            logger.warning("⚠️ Recorder not initialized when track received")


async def on_media_receive():
    """
    This method will be called when the PC receives media.
    It can be used to start a recorder.
    It may be called multiple times with no input.
    """
    logger.info("🔔 Media received callback from plugin!")
    if recorder:
        await recorder.start()
        logger.info(f"✅ Recorder started, saving to {RECORD_TO}")


async def on_stream_ended():
    """
    This method will be called when the stream ends.
    It can be used to stop the recorder.
    """
    global recorder
    if recorder:
        await recorder.stop()
        logger.info(f"✅ Recorder stopped, saved to {RECORD_TO}")
        recorder = None
    else:
        logger.warning("⚠️ Recorder not initialized when stream ended")


async def main():
    # Create session
    session = JanusSession(base_url=JANUS_BASE_URL, token=JANUS_API_TOKEN)
    logger.info("✅ Session created")

    # Create plugin & attach to Janus session
    plugin_handle = JanusAudioBridgePlugin(
        on_media_receive_callback=on_media_receive,
        on_track_created_callback=on_track_created,
        on_stream_ended_callback=on_stream_ended,
    )
    await plugin_handle.attach(session=session)
    logger.info("✅ Plugin created & attached")

    # Check if room exists
    if not await plugin_handle.exists(ROOM_ID):
        logger.error("❌ room does not exist")
        return
    logger.info("✅ Room exists")

    # Join Room
    await plugin_handle.join(ROOM_ID, DISPLAY_NAME, JANUS_API_TOKEN)
    logger.info("✅ Joined room")

    # Publish our stream
    await plugin_handle.publish_stream(SilenceAudioTrack())
    #await plugin_handle.publish_stream(SineAudioTrack())
    #await plugin_handle.publish_stream(await FileAudioTrack(PLAY_FROM))
    logger.info("✅ Stream published")

    await plugin_handle.wait_webrtcup()

    # Ping Janus to check connection
    await session.transport.ping()

    # Wait awhile then hangup
    await asyncio.sleep(15)
    await plugin_handle.leave(ROOM_ID)

    # Destroy everything
    await plugin_handle.destroy()
    await session.destroy()

    logger.info("✅ Test completed")


if __name__ == "__main__":
    try:
        # asyncio.run(main=main())
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        pass
