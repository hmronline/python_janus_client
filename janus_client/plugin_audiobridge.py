import asyncio
import logging
from typing import List

from .plugin_base import JanusPlugin
from .message_transaction import is_subset
from aiortc import RTCPeerConnection, MediaStreamTrack

logger = logging.getLogger(__name__)

class JanusAudioBridgePlugin(JanusPlugin):
    """
    Janus AudioBridge plugin implementation
    """

    name = "janus.plugin.audiobridge"

    class State:
        STREAMING_OUT_MEDIA = "streaming_out_media"
        STREAMING_IN_MEDIA = "streaming_in_media"
        IDLE = "idle"

    __state: State
    __webrtcup_event: asyncio.Event

    def __init__(self, on_media_receive_callback=None,
                 on_track_created_callback=None,
                 on_stream_ended_callback=None) -> None:
        super().__init__()

        self.__state = self.State.IDLE
        self.__webrtcup_event = asyncio.Event()
        self.__on_media_receive_callback = on_media_receive_callback
        self.__on_track_created_callback = on_track_created_callback
        self.__on_stream_ended_callback = on_stream_ended_callback

    async def __on_media_receive(self)-> None:
        """
        This method will be called when the PC receives media.
        It can be used to start a recorder.
        It may be called multiple times with no input.
        """
        logger.info("media received")
        if self.__on_media_receive_callback:
            # If the callback is async, await it; otherwise, just call it
            if asyncio.iscoroutinefunction(self.__on_media_receive_callback):
                await self.__on_media_receive_callback()
            else:
                self.__on_media_receive_callback()

    async def __on_track_created(self, track: MediaStreamTrack)-> None:
        logger.info(f"Track {track.kind} created")
        if self.__on_track_created_callback:
            # If the callback is async, await it; otherwise, just call it
            if asyncio.iscoroutinefunction(self.__on_track_created_callback):
                await self.__on_track_created_callback(self._pc, track)
            else:
                self.__on_track_created_callback(self._pc, track)

    async def __on_stream_ended(self)-> None:
        logger.info("stream ended")
        # Stream ended. Ok to close PC multiple times.
        if self._pc:
            await self._pc.close()
        
        if self.__on_stream_ended_callback:
            # If the callback is async, await it; otherwise, just call it
            if asyncio.iscoroutinefunction(self.__on_stream_ended_callback):
                await self.__on_stream_ended_callback()
            else:
                self.__on_stream_ended_callback()

    async def wait_webrtcup(self) -> None:
        logger.info("webrtc up")
        await self.__webrtcup_event.wait()
        self.__webrtcup_event.clear()

    async def on_receive(self, response: dict)-> None:
        """
        Handle asynchronous messages
        """
        logger.info(f"on_receive: {response}")

        if "jsep" in response:
            await self.on_receive_jsep(jsep=response["jsep"])

        janus_code = response["janus"]

        if janus_code == "media":
            if response["receiving"]:
                # It's ok to start multiple times, only the track that
                # has not been started will start
                if self.__state == self.State.STREAMING_IN_MEDIA:
                    self.__on_media_receive()
                elif self.__state == self.State.IDLE:
                    raise Exception("Media streaming when idle")

        if janus_code == "webrtcup":
            self.__webrtcup_event.set()

        if janus_code == "event":
            logger.info(f"Event response: {response}")
            # if "plugindata" in response:
            #     if response["plugindata"]["data"]["videoroom"] == "attached":
            #         # Subscriber attached
            #         self.joined_event.set()
            #     elif response["plugindata"]["data"]["videoroom"] == "joined":
            #         # Participant joined (joined as publisher but may not publish)
            #         self.joined_event.set()
            plugin_data = response["plugindata"]["data"]

            if plugin_data["audiobridge"] != "event":
                # This plugin will only get events
                logger.error(f"Invalid response: {response}")
                return

            if "result" in plugin_data:
                if plugin_data["result"] == "ok":
                    # Successful start stream request. Do nothing.
                    pass

                if plugin_data["result"] == "done":
                    self.__on_stream_ended();
                    self.__state = self.State.IDLE

            if "errorcode" in plugin_data:
                logger.error(f"Plugin Error: {response}")
        else:
            logger.info(f"Unimplemented response handle: {response}")

    async def __send_wrapper(self, message: dict, matcher: dict, jsep: dict = {}) -> dict:
        def function_matcher(message: dict):
            return (
                is_subset(message, matcher)
                or is_subset(
                    message,
                    {
                        "janus": "success",
                        "plugindata": {
                            "plugin": self.name,
                            "data": {
                                "videoroom": "event",
                                "error_code": None,
                                "error": None,
                            },
                        },
                    },
                )
                or is_subset(
                    message,
                    {
                        "janus": "event",
                        "plugindata": {
                            "plugin": self.name,
                            "data": {
                                "videoroom": "event",
                                "error_code": None,
                                "error": None,
                            },
                        },
                    },
                )
                or is_subset(message, {"janus": "error", "error": {}})
            )

        full_message = message
        if jsep:
            full_message = {**message, "jsep": jsep}

        message_transaction = await self.send(
            message=full_message,
        )
        response = await message_transaction.get(matcher=function_matcher, timeout=15)
        await message_transaction.done()

        if is_subset(response, {"janus": "error", "error": {}}):
            raise Exception(f"Janus error: {response}")

        return response

    async def exists(self, room_id: int) -> bool:
        """
        Check if a room exists.
        """

        success_matcher = {
            "janus": "success",
            "plugindata": {
                "plugin": self.name,
                "data": {"audiobridge": "success", "room": room_id, "exists": None},
            },
        }
        response = await self.__send_wrapper(
            message={
                "janus": "message",
                "body": {
                    "request": "exists",
                    "room": room_id,
                },
            },
            matcher=success_matcher,
        )

        return (
            is_subset(response, success_matcher)
            and response["plugindata"]["data"]["exists"]
        )

    async def join(self, room_id: int, display_name: str = "", token: str = None) -> bool:
        """
        Join a room

        :param room_id: unique ID of the room to join.
        :param display_name: display name for the participant; optional.
        :param token: invitation token, in case the room has an ACL; optional.

        :return: True if room is created.
        """

        body = {
            "request": "join",
            "room": room_id,
            "display": display_name,
        }
        if token:
            body["token"] = token
        success_matcher = {
            "janus": "event",
            "plugindata": {
                "plugin": self.name,
                "data": {"audiobridge": "joined", "room": room_id},
            },
        }

        response = await self.__send_wrapper(
            message={
                "janus": "message",
                "body": body,
            },
            matcher=success_matcher,
        )

        return is_subset(response, success_matcher)

    async def leave(self) -> bool:
        """
        Leave the room. Will unpublish if publishing.

        :return: True if successfully leave.
        """

        success_matcher = {
            "janus": "event",
            "plugindata": {
                "plugin": self.name,
                "data": {"audiobridge": "left"},
            },
        }
        response = await self.__send_wrapper(
            message={
                "janus": "message",
                "body": {
                    "request": "leave",
                },
            },
            matcher=success_matcher,
        )

        await self._pc.close()

        return is_subset(response, success_matcher)

    async def __configure_pc(self, stream_track: List[MediaStreamTrack] = []) -> RTCPeerConnection:
        """
        Configure a PeerConnection with media tracks.
        """
        
        for track in stream_track:
            self._pc.addTrack(track=track)
        
        # Must configure on track event before setRemoteDescription
        self._pc.on("track")(self.__on_track_created)

        return self._pc

    async def publish_stream(self, stream_track: List[MediaStreamTrack] = [])-> bool:
        """
        Stream audio to the room

        Should already have joined a room before this.
        """

        self._pc = await self.__configure_pc(stream_track=stream_track)

        # create & send offer
        await self._pc.setLocalDescription(await self._pc.createOffer())
        self.__state = self.State.STREAMING_OUT_MEDIA


        body = {
            "request": "configure",
            "muted": False,
        }
        success_matcher = {
            "janus": "event",
            "plugindata": {
                "plugin": self.name,
                "data": {"audiobridge": "event", "result": "ok"},
            },
        }
        response = await self.__send_wrapper(
            message={
                "janus": "message",
                "body": body,
            },
            matcher=success_matcher,
            jsep=await self.create_jsep(pc=self._pc),
        )

        if is_subset(response, success_matcher):
            jsep = response.get("jsep")
            if jsep and "sdp" in jsep and "type" in jsep:
                logger.info("Received SDP:\n%s", jsep["sdp"].replace("\r\n", "\n"))
                await self.on_receive_jsep(jsep=jsep)
            else:
                logger.error("No valid JSEP in Janus response: %s", response)
                return False
            return True
        else:
            return False

    async def close_stream(self)-> None:
        """
        lose stream

        This should cause the stream to stop and a done event to be received.
        """
        if self._pc:
            await self._pc.close()
