# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Start the Developer Preview using only this checkout's private data directory."""
import argparse
import getpass
import ipaddress
import json
from pathlib import Path
import socket
import uvicorn
from router_api import create_router_app

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config.local.json')
    parser.add_argument('--api-token-prompt', action='store_true', help='Read a caller-created 32+ character Hub API token privately')
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8')) if args.config.exists() else {}
    if set(config) - {'port', 'device_host', 'monitor'}:
        parser.error('unknown configuration fields')
    port = config.get('port', 8765)
    if type(port) is not int or not 1024 <= port <= 65535:
        parser.error('port must be an integer between 1024 and 65535')
    monitor = config.get('monitor', True)
    if type(monitor) is not bool:
        parser.error('monitor must be boolean')
    hosts = ['127.0.0.1']
    if config.get('device_host'):
        address = ipaddress.ip_address(config['device_host'])
        if address.version != 4 or not any(address in ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):
            parser.error('device_host must be your specific RFC1918 LAN IPv4')
        hosts.append(str(address))
    token = getpass.getpass('Your Hub API token: ') if args.api_token_prompt else None
    if token is not None and (len(token) < 32 or not token.isascii() or any(c.isspace() for c in token)):
        parser.error('token must contain at least 32 ASCII non-whitespace characters')
    from device_text import title_font
    title_font()  # Warn before devices connect; ASCII fallback remains available.
    sockets = []
    try:
        for host in hosts:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sockets.append(sock)
            sock.bind((host, port))
            sock.listen(128)
        application = create_router_app(ROOT / '.build/preview-data', start_monitor=monitor,
                                         api_token=token, environment='developer-preview')
        print(f'Developer Preview listening on {hosts}:{port}; data=.build/preview-data', flush=True)
        uvicorn.Server(uvicorn.Config(application, log_level='info', access_log=False,
                                      proxy_headers=False)).run(sockets=sockets)
    finally:
        for sock in sockets:
            sock.close()

if __name__ == '__main__':
    main()
