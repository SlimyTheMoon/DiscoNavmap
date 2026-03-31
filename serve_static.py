import http.server
import os
import argparse


def main():
    parser = argparse.ArgumentParser(description="Serve static navmap files")
    parser.add_argument("-dir", default="docs", help="Directory to serve (default: dist)")
    parser.add_argument("-addr", default=":8080", help="Listen address (default: :8080)")
    args = parser.parse_args()

    os.chdir(args.dir)

    addr = args.addr.lstrip(":")
    port = int(addr) if addr.isdigit() else 8080

    handler = http.server.SimpleHTTPRequestHandler
    server = http.server.HTTPServer(("0.0.0.0", port), handler)
    print("Serving %s on http://localhost:%d" % (os.path.abspath("."), port))
    server.serve_forever()


if __name__ == "__main__":
    main()
