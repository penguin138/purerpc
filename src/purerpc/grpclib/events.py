import base64
import datetime
from .exceptions import ProtocolError


class Event:
    pass


class RequestReceived(Event):
    def __init__(self, stream_id: int, scheme: str, service_name: str, method_name: str,
                 content_type: str):
        self.stream_id = stream_id
        self.scheme = scheme
        self.service_name = service_name
        self.method_name = method_name
        self.content_type = content_type
        self.authority = None
        self.timeout = None
        self.message_type = None
        self.message_encoding = None
        self.message_accept_encoding = None
        self.user_agent = None
        self.custom_metadata = {}

    @staticmethod
    def parse_from_stream_id_and_headers_destructive(stream_id: int, headers: dict):
        if headers.pop(":method") != "POST":
            raise ProtocolError("Unsupported method {}".format(headers[":method"]))

        scheme = headers.pop(":scheme")
        if scheme not in ["http", "https"]:
            raise ProtocolError("Scheme should be either http or https")

        if headers[":path"].startswith("/"):
            service_name, method_name = headers.pop(":path")[1:].split("/")
        else:
            raise ProtocolError("Path should be /<service_name>/<method_name>")

        if "te" not in headers or headers["te"] != "trailers":
            raise ProtocolError("te header not found or not equal to 'trailers', "
                                "using incompatible proxy?")
        else:
            headers.pop("te")

        content_type = headers.pop("content-type")
        if not content_type.startswith("application/grpc"):
            raise ProtocolError("Content type should start with application/grpc")

        event = RequestReceived(stream_id, scheme, service_name, method_name, content_type)

        if ":authority" in headers:
            event.authority = headers.pop(":authority")

        if "grpc-timeout" in headers:
            timeout_string = headers.pop("grpc-timeout")
            timeout_value, timeout_unit = int(timeout_string[:-1]), timeout_string[-1:]
            if timeout_unit == "H":
                event.timeout = datetime.timedelta(hours=timeout_value)
            elif timeout_unit == "M":
                event.timeout = datetime.timedelta(minutes=timeout_value)
            elif timeout_unit == "S":
                event.timeout = datetime.timedelta(seconds=timeout_value)
            elif timeout_unit == "m":
                event.timeout = datetime.timedelta(milliseconds=timeout_value)
            elif timeout_unit == "u":
                event.timeout = datetime.timedelta(microseconds=timeout_value)
            elif timeout_unit == "n":
                event.timeout = datetime.timedelta(microseconds=timeout_value / 1000)
            else:
                raise ProtocolError("Unknown timeout unit: {}".format(timeout_unit))

        if "grpc-encoding" in headers:
            event.message_encoding = headers.pop("grpc-encoding")

        if "grpc-accept-encoding" in headers:
            event.message_accept_encoding = headers.pop("grpc-accept-encoding").split(",")

        if "user-agent" in headers:
            event.user_agent = headers.pop("user-agent")

        if "grpc-message-type" in headers:
            event.message_type = headers.pop("grpc-message-type")

        for header_name in list(headers.keys()):
            if header_name.endswith("-bin"):
                event.custom_metadata[header_name] = base64.b64decode(headers.pop(header_name))
            else:
                event.custom_metadata[header_name] = headers.pop(header_name)
        return event


class MessageReceived(Event):
    def __init__(self, stream_id: int, data: bytes):
        self.stream_id = stream_id
        self.data = data


class RequestEnded(Event):
    def __init__(self, stream_id: int):
        self.stream_id = stream_id


class ResponseReceived(Event):
    def __init__(self, stream_id: int, content_type: str):
        self.stream_id = stream_id
        self.content_type = content_type
        self.message_encoding = None
        self.message_accept_encoding = None
        self.custom_metadata = {}

    @staticmethod
    def parse_from_stream_id_and_headers_destructive(stream_id: int, headers: dict):
        if int(headers.pop(":status")) != 200:
            raise ProtocolError("http status is not 200")

        content_type = headers.pop("content-type")
        if not content_type.startswith("application/grpc"):
            raise ProtocolError("Content type should start with application/grpc")

        event = ResponseReceived(stream_id, content_type)

        if "grpc-encoding" in headers:
            event.message_encoding = headers.pop("grpc-encoding")

        if "grpc-accept-encoding" in headers:
            event.message_accept_encoding = headers.pop("grpc-accept-encoding").split(",")

        for header_name in list(headers.keys()):
            if header_name in ["grpc-status", "grpc-message"]:
                # is not metadata, will be parsed in ResponseEnded
                continue
            if header_name.endswith("-bin"):
                event.custom_metadata[header_name] = base64.b64decode(headers.pop(header_name))
            else:
                event.custom_metadata[header_name] = headers.pop(header_name)
        return event


class ResponseEnded(Event):
    def __init__(self, stream_id: int, status: int):
        self.stream_id = stream_id
        self.status = status
        self.status_message = None
        self.custom_metadata = {}

    @staticmethod
    def parse_from_stream_id_and_headers_destructive(stream_id: int, headers: dict):
        if "grpc-status" not in headers:
            raise ProtocolError("Expected grpc-status in trailers")

        status = int(headers.pop("grpc-status"))
        event = ResponseEnded(stream_id, status)

        if "grpc-message" in headers:
            # TODO: is percent encoded
            event.status_message = headers.pop("grpc-message")

        for header_name in list(headers.keys()):
            if header_name.endswith("-bin"):
                event.custom_metadata[header_name] = base64.b64decode(headers.pop(header_name))
            else:
                event.custom_metadata[header_name] = headers.pop(header_name)
        return event
