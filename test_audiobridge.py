import asyncio
import logging
import os

# from janus_client.transport import JanusTransportHTTP
from janus_client import JanusSession, JanusAudioBridgePlugin

format = "%(asctime)s: %(message)s"
logging.basicConfig(format=format, level=logging.INFO, datefmt="%H:%M:%S")
logger = logging.getLogger()

JANUS_BASE_URL = "wss://somewhere/janus"  # Replace with your Janus server URL
JANUS_API_TOKEN = "secret_token"  # Replace with your actual token
ROOM_ID = "1234" # Replace with your actual room ID
DISPLAY_NAME = "Test User"

async def main():
    # Create session
    session = JanusSession(base_url=JANUS_BASE_URL, token=JANUS_API_TOKEN)
    logger.info("✅ session created")

    # Create plugin
    plugin_handle = JanusAudioBridgePlugin()
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

    if os.path.exists("./echo.mp3"):
        os.remove("./echo.mp3")

    # Publish our stream
    await plugin_handle.publish_stream(
        play_from="./sample.mp3", record_to="./echo.mp3"
    )
    logger.info("✅ stream published")

    # Ping Janus to check connection
    await session.transport.ping()

    # Wait awhile then hangup
    await asyncio.sleep(15)
    await plugin_handle.close_stream()

    # Destroy plugin & session
    await plugin_handle.destroy()
    await session.destroy()
    logger.info("✅ test completed")

if __name__ == "__main__":
    try:
        # asyncio.run(main=main())
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        pass
