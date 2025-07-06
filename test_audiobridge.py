import asyncio, logging, os, av, math, fractions, io, numpy as np
from aiortc import RTCPeerConnection
from aiortc.contrib.media import MediaStreamTrack, MediaPlayer, MediaRecorder
from janus_client import JanusSession, JanusAudioBridgePlugin
from gtts import gTTS
from pydub import AudioSegment

JANUS_BASE_URL = "wss://somewhere/janus"  # Replace with your Janus server URL
JANUS_API_TOKEN = "secret_token"  # Replace with your actual token
ROOM_ID = "1234"  # Replace with your actual room ID
DISPLAY_NAME = "Test User"
PLAY_FROM = "./sample.mp3"  # Path to the audio file to play
RECORD_TO = "./echo.mp3"  # Path to save the recorded audio

format = "%(asctime)s: %(message)s"
logging.basicConfig(format=format, level=logging.INFO, datefmt="%H:%M:%S")
logger = logging.getLogger()
recorder: MediaRecorder = None


class SineAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, frequency: int = 440, sample_rate: int = 48000):
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


class GTTSStreamTrack(MediaStreamTrack):
    """
    Requires ffmpeg installed.
    """

    kind = "audio"

    def __init__(self, text: str, lang: str = "en", sample_rate: int = 48000):
        super().__init__()
        # Generate TTS audio in memory
        mp3_fp = io.BytesIO()
        gTTS(text=text, lang=lang).write_to_fp(mp3_fp)
        mp3_fp.seek(0)
        # Decode MP3 to PCM using pydub
        audio = (
            AudioSegment.from_file(mp3_fp, format="mp3")
            .set_frame_rate(sample_rate)
            .set_channels(1)
        )
        self.samples = audio.get_array_of_samples()
        self.sample_rate = sample_rate
        self._timestamp = 0
        self._frame_size = 960  # 20ms at 48kHz

    async def recv(self):
        if self._timestamp >= len(self.samples):
            await asyncio.sleep(0.02)
            raise asyncio.CancelledError  # End of stream
        # Get next frame
        frame_samples = self.samples[
            self._timestamp : self._timestamp + self._frame_size
        ]
        frame = av.AudioFrame(format="s16", layout="mono", samples=len(frame_samples))
        frame.planes[0].update(frame_samples.tobytes())
        frame.sample_rate = self.sample_rate
        frame.pts = self._timestamp
        frame.time_base = fractions.Fraction(1, self.sample_rate)
        self._timestamp += self._frame_size
        await asyncio.sleep(self._frame_size / self.sample_rate)
        return frame


async def on_track_created(pc: RTCPeerConnection, track: MediaStreamTrack):
    """
    This method will be called when the PC creates a new track.
    """
    global recorder
    if track.kind == "audio":
        logger.info("🔔 Received audio track from Janus")
        if not recorder and RECORD_TO:
            if os.path.exists(RECORD_TO):
                os.remove(RECORD_TO)
            recorder = MediaRecorder(RECORD_TO)
        if recorder:
            logger.info("🔊 Adding audio track to recorder")
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
        logger.info("✅ Recorder started, saving to: " + RECORD_TO)


async def on_stream_ended():
    """
    This method will be called when the stream ends.
    It can be used to stop the recorder.
    """
    global recorder
    if recorder:
        await recorder.stop()
        logger.info("✅ Recorder stopped, saved to: " + RECORD_TO)
        recorder = None
    else:
        logger.warning("⚠️ Recorder not initialized when stream ended")


async def main():
    # Create session
    session = JanusSession(base_url=JANUS_BASE_URL, token=JANUS_API_TOKEN)
    logger.info("✅ Janus session created")

    # Create plugin & attach to Janus session
    plugin_handle = JanusAudioBridgePlugin(
        on_media_receive_callback=on_media_receive,
        on_track_created_callback=on_track_created,
        on_stream_ended_callback=on_stream_ended,
    )
    await plugin_handle.attach(session=session)
    logger.info("✅ Janus AudioBridge Plugin attached")

    # Check if room exists
    if not await plugin_handle.exists(ROOM_ID):
        logger.error("❌ Janus AudioBridge Room does not exist: " + ROOM_ID)
        return
    logger.info("✅ Janus AudioBridge Room does exist: " + ROOM_ID)

    # Join Room
    await plugin_handle.join(ROOM_ID, DISPLAY_NAME, JANUS_API_TOKEN)
    logger.info("✅ Joined Janus AudioBridge Room: " + ROOM_ID)

    # Publish our stream
    # await plugin_handle.publish_stream(SilenceAudioTrack())
    # await plugin_handle.publish_stream(SineAudioTrack())
    # await plugin_handle.publish_stream(await FileAudioTrack(PLAY_FROM))
    await plugin_handle.publish_stream(GTTSStreamTrack("Hello, how are you?", "en"))
    logger.info("✅ Client stream published")

    await plugin_handle.wait_webrtcup()

    # Ping Janus to check connection
    await session.transport.ping()

    # Wait awhile then hangup
    await asyncio.sleep(10)
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
