import asyncio
import gc
import logging
import socket

from json import loads

import pytest

from async_logstash import create_tcp_handler

asyncio.set_event_loop(None)


logging.getLogger().setLevel(logging.DEBUG)


def unused_port():
    """Return a port that is unused on the current host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@pytest.fixture
def event_loop(request):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    yield loop

    loop.close()
    gc.collect()
    asyncio.set_event_loop(None)
    return

    if not loop.is_closed():
        loop.call_soon(loop.stop)
        loop.run_forever()
        loop.close()

    gc.collect()
    asyncio.set_event_loop(None)


@pytest.fixture
def loop(event_loop):
    return event_loop


class FakeTcpServer:
    def __init__(self, loop):
        self.loop = loop
        self.data = bytearray()
        self.server = None
        self.futs = set()

    async def start(self):
        self.server = await asyncio.start_server(self.on_connect,
                                                 host='127.0.0.1',
                                                 loop=self.loop)

    @property
    def port(self):
        return self.server.sockets[0].getsockname()[1]

    @property
    def jsons(self):
        s = self.data.decode('utf8')
        return [loads(i) for i in s.split('\n') if i]

    async def close(self):
        if self.server is None:
            return
        self.server.close()
        await self.server.wait_closed()
        self.server = None

    async def on_connect(self, reader, writer):
        while True:
            data = await reader.read(1024)
            self.data.extend(data)
            for fut in self.futs:
                if not fut.done():
                    fut.set_result(None)

    async def wait(self):
        fut = self.loop.create_future()
        self.futs.add(fut)
        await fut
        self.futs.remove(fut)


@pytest.fixture
async def make_tcp_handler(loop):
    servers = []
    handlers = []

    async def go(*args, level=logging.DEBUG, **kwargs):
        server = FakeTcpServer(loop)
        await server.start()
        servers.append(server)
        handler = await create_tcp_handler('127.0.0.1', server.port, **kwargs)
        handlers.append(handler)
        return handler, server

    yield go

    for handler in handlers:
        handler.close()
        await handler.wait_closed()

    for server in servers:
        await server.close()


@pytest.fixture
def setup_logger(make_tcp_handler):
    async def go(*args, **kwargs):
        handler, server = await make_tcp_handler(*args, **kwargs)
        logger = logging.getLogger('async_logstash_test')
        logger.addHandler(handler)
        return logger, server
    yield go
