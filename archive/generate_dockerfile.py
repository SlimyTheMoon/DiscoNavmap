"""Generate a Dockerfile for serving DiscoNavmap.

Usage:
    python generate_dockerfile.py flask    # Full Flask app with game data parsing
    python generate_dockerfile.py static   # Static website (docs/) via nginx
"""

import sys
import os

FLASK_DOCKERFILE = r"""FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gamedata/ ./gamedata/
COPY templates/ ./templates/
COPY styles/ ./styles/
COPY scripts/ ./scripts/
COPY images/ ./images/
COPY textures/ ./textures/
COPY data/ ./data/
COPY main.py .

EXPOSE 8080

CMD ["python", "main.py", "-addr", ":8080"]
"""

STATIC_DOCKERFILE = r"""FROM nginx:alpine

COPY docs/ /usr/share/nginx/html/

RUN printf 'server {\n\
    listen 80;\n\
    server_name _;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
    location / {\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
    location ~* \.(json|gz)$ {\n\
        add_header Content-Type application/json;\n\
        add_header Access-Control-Allow-Origin *;\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
"""


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("flask", "static"):
        print(__doc__.strip())
        sys.exit(1)

    mode = sys.argv[1]
    content = FLASK_DOCKERFILE if mode == "flask" else STATIC_DOCKERFILE
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Dockerfile")

    with open(out_path, "w", newline="\n") as f:
        f.write(content)

    print(f"Wrote {mode} Dockerfile to {out_path}")


if __name__ == "__main__":
    main()
