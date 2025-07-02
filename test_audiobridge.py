import asyncio
import logging
import os

# from janus_client.transport import JanusTransportHTTP
from janus_client import JanusSession, JanusAudioBridgePlugin

format = "%(asctime)s: %(message)s"
logging.basicConfig(format=format, level=logging.INFO, datefmt="%H:%M:%S")
logger = logging.getLogger()

JANUS_BASE_URL = "wss://janusmy.josephgetmyip.com/janusbasews/janus"
JANUS_API_TOKEN = "sosecret"
ROOM_ID = "1234"
DISPLAY_NAME = "Test"

async def main():
    # Create session
    session = JanusSession(base_url=JANUS_BASE_URL, token=JANUS_API_TOKEN)
    logger.info("session created")

    # Create plugin
    plugin_handle = JanusAudioBridgePlugin()
    logger.info("plugin created")

    # Attach to Janus session
    await plugin_handle.attach(session=session)
    logger.info("plugin attached")

    # Join Room
    await plugin_handle.join(ROOM_ID, DISPLAY_NAME)
    logger.info("room joined")

    if os.path.exists("./echo.mp3"):
        os.remove("./echo.mp3")

    await plugin_handle.start(
        play_from="./sample.mp3", record_to="./echo.mp3"
    )

    response = await session.transport.ping()
    logger.info(response)

    await asyncio.sleep(15)

    await plugin_handle.close_stream()

    # Destroy plugin
    await plugin_handle.destroy()

    # Destroy session
    await session.destroy()


if __name__ == "__main__":
    try:
        # asyncio.run(main=main())
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        pass
