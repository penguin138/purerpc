import curio.meta
from purerpc.grpc_proto import GRPCProtoStream
from purerpc.grpclib.events import ResponseEnded


async def extract_message_from_singleton_stream(stream):
    msg = await stream.receive_message()
    if msg is None:
        event = stream.end_stream_event
        if isinstance(event, ResponseEnded) and event.status != 0:
            raise RuntimeError(f"RPC failed with code {event.status}: {event.status_message}")
        raise RuntimeError("Expected one message, got zero")
    if await stream.receive_message() is not None:
        raise RuntimeError("Expected one message, got multiple")
    return msg


async def stream_to_async_iterator(stream: GRPCProtoStream):
    while True:
        msg = await stream.receive_message()
        if msg is None:
            event = stream.end_stream_event
            if isinstance(event, ResponseEnded) and event.status != 0:
                raise RuntimeError(f"RPC failed with code {event.status}: {event.status_message}")
            return
        yield msg


async def send_multiple_messages_server(stream, agen):
    async with curio.meta.finalize(agen) as tmp:
        async for message in tmp:
            await stream.send_message(message)
    await stream.close(0)


async def send_multiple_messages_client(stream, agen):
    try:
        async with curio.meta.finalize(agen) as tmp:
            async for message in tmp:
                await stream.send_message(message)
    finally:
        await stream.close()


async def send_single_message(stream, message):
    await stream.send_message(message)
    await stream.close(0)


async def call_server_unary_unary(func, stream):
    msg = await extract_message_from_singleton_stream(stream)
    await send_single_message(stream, await func(msg))


async def call_server_unary_stream(func, stream):
    msg = await extract_message_from_singleton_stream(stream)
    await send_multiple_messages_server(stream, func(msg))


async def call_server_stream_unary(func, stream):
    input_message_stream = stream_to_async_iterator(stream)
    await send_single_message(stream, await func(input_message_stream))


async def call_server_stream_stream(func, stream):
    input_message_stream = stream_to_async_iterator(stream)
    await send_multiple_messages_server(stream, func(input_message_stream))


class ClientStub:
    def __init__(self, stream_fn):
        self._stream_fn = stream_fn


class ClientStubUnaryUnary(ClientStub):
    async def __call__(self, message):
        stream = await self._stream_fn()
        await send_single_message(stream, message)
        return await extract_message_from_singleton_stream(stream)


class ClientStubUnaryStream(ClientStub):
    async def __call__(self, message):
        stream = await self._stream_fn()
        await send_single_message(stream, message)
        async for message in stream_to_async_iterator(stream):
            yield message


class ClientStubStreamUnary(ClientStub):
    async def __call__(self, message_aiter):
        stream = await self._stream_fn()
        await curio.spawn(send_multiple_messages_client, stream, message_aiter, daemon=True)
        return await extract_message_from_singleton_stream(stream)


class ClientStubStreamStream(ClientStub):
    async def call_aiter(self, message_aiter):
        stream = await self._stream_fn()
        if message_aiter is not None:
            await curio.spawn(send_multiple_messages_client, stream, message_aiter, daemon=True)
            async for message in stream_to_async_iterator(stream):
                yield message

    async def call_stream(self):
        return await self._stream_fn()

    def __call__(self, message_aiter=None):
        if message_aiter is None:
            return self.call_stream()
        else:
            return self.call_aiter(message_aiter)
