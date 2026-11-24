"""Bridge a stdio MCP client to AIOS through the VM owner's private vsock backend."""
import argparse
import os
import socket
import sys
import threading


def relay(path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
        channel.settimeout(15)
        channel.connect(path)
        channel.sendall(b"CONNECT 4050\n")
        with channel.makefile("rb", buffering=0) as reader:
            response = reader.readline(100)
            if not (response.startswith(b"OK ") and response.endswith(b"\n")
                    and response[3:-1].isdigit()):
                raise ConnectionError("AIOS vsock service did not accept the connection")
        channel.settimeout(None)

        def upload():
            try:
                while data := os.read(sys.stdin.fileno(), 65536):
                    channel.sendall(data)
                channel.shutdown(socket.SHUT_WR)
            except OSError:
                try:
                    channel.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        threading.Thread(target=upload, daemon=True).start()
        while data := channel.recv(65536):
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("socket", help="vhost-device-vsock --uds-path")
    relay(parser.parse_args().socket)
