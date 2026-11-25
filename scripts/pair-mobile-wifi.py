"""Create a private AIOS Windows identity and a phone pairing file."""
import argparse
import base64
from ipaddress import IPv4Address, IPv4Network
import json
from pathlib import Path
import secrets
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", type=IPv4Address)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--openssl", default="openssl")
    parser.add_argument("--port", type=int, default=18120)
    args = parser.parse_args()
    if not any(args.host in IPv4Network(block) for block in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
        parser.error("use a private LAN IPv4 address")
    if not 1 <= args.port <= 65535:
        parser.error("invalid port")
    args.directory.mkdir(mode=0o700)
    cert = args.directory / "pc-cert.pem"
    key = args.directory / "pc-key.pem"
    subprocess.run([args.openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "365",
                    "-subj", "/CN=AIOS Windows Worker", "-addext", f"subjectAltName=IP:{args.host}",
                    "-addext", "extendedKeyUsage=serverAuth", "-keyout", str(key), "-out", str(cert)],
                   check=True, capture_output=True)
    der = subprocess.check_output([args.openssl, "x509", "-in", str(cert), "-outform", "DER"])
    with (args.directory / "pairing.json").open("x", encoding="utf-8") as pairing:
        json.dump({"host": str(args.host), "port": args.port, "token": secrets.token_hex(32),
                   "certificate_der": base64.b64encode(der).decode("ascii")}, pairing)
    print(f"Pairing file: {args.directory / 'pairing.json'}")


if __name__ == "__main__":
    main()
