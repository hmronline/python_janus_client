import asyncio
import logging
import os

# from janus_client.transport import JanusTransportHTTP
from janus_client import JanusSession, JanusAudioBridgePlugin

format = "%(asctime)s: %(message)s"
logging.basicConfig(format=format, level=logging.INFO, datefmt="%H:%M:%S")
logger = logging.getLogger()


async def main():
    # transport = JanusTransportHTTP(
    #     uri="https://janusmy.josephgetmyip.com/janusbase/janus"
    # )
    session = JanusSession(base_url="wss://janusmy.josephgetmyip.com/janusbasews/janus")
    # session = JanusSession(base_url="https://janusmy.josephgetmyip.com/janusbase/janus")

    plugin_handle = JanusAudioBridgePlugin()

    await plugin_handle.attach(session=session)

    if os.path.exists("./echo.mp3"):
        os.remove("./echo.mp3")

    await plugin_handle.start(
        play_from="./sample.mp3", record_to="./echo.mp3"
    )

    response = await session.transport.ping()
    logger.info(response)

    await asyncio.sleep(15)

    await plugin_handle.close_stream()

    await plugin_handle.destroy()

    await session.destroy()


if __name__ == "__main__":
    try:
        # asyncio.run(main=main())
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        pass
