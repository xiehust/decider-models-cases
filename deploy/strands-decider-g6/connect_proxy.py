"""Minimal HTTPS CONNECT proxy on 127.0.0.1 for the one-time setup over an SSH -R tunnel.

Only CONNECT to port 443 of an allowlisted host suffix is relayed; everything else is refused.
"""
import asyncio
import sys

ALLOW = (".pypi.org", "pypi.org", ".pythonhosted.org", ".huggingface.co", "huggingface.co",
         ".hf.co", "hf.co", ".xethub.hf.co", "download.pytorch.org")


def allowed(host: str) -> bool:
    return any(host == a or (a.startswith(".") and host.endswith(a)) for a in ALLOW)


async def pipe(r, w):
    try:
        while data := await r.read(65536):
            w.write(data)
            await w.drain()
    except Exception:
        pass
    finally:
        w.close()


async def handle(cr, cw):
    try:
        head = await cr.readuntil(b"\r\n\r\n")
        method, target, _ = head.split(b"\r\n", 1)[0].decode().split(" ", 2)
        host, _, port = target.rpartition(":")
        if method != "CONNECT" or port != "443" or not allowed(host):
            print("DENY", method, target, flush=True)
            cw.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            await cw.drain()
            cw.close()
            return
        ur, uw = await asyncio.open_connection(host, 443)
        cw.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await cw.drain()
        print("CONNECT", target, flush=True)
        await asyncio.gather(pipe(cr, uw), pipe(ur, cw))
    except Exception as exc:
        print("ERR", exc, flush=True)
        cw.close()


async def main(port: int):
    server = await asyncio.start_server(handle, "127.0.0.1", port)
    async with server:
        await server.serve_forever()


asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3128))
