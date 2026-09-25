class SignalingError(Exception):
    """Base class for all signaling-layer errors."""

    code = "SIGNALING_ERROR"

    def __init__(self, message: str, code: str | None = None):
        self.message = message
        # Per-instance override for the rare case where one class must report a
        # different wire code (e.g. a room-ownership failure is reported to the
        # client as AUTH_FAILED rather than UNAUTHORIZED_PEER).
        self.code = code or type(self).code
        super().__init__(message)


class InvalidMessage(SignalingError):
    code = "INVALID_MESSAGE"


class UnauthorizedPeer(SignalingError):
    code = "UNAUTHORIZED_PEER"


class RoomFull(SignalingError):
    code = "ROOM_FULL"


class RoomNotFound(SignalingError):
    code = "ROOM_NOT_FOUND"


class PeerNotConnected(SignalingError):
    code = "PEER_NOT_CONNECTED"
