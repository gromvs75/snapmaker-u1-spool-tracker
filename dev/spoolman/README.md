# Isolated Spoolman contract probe

This is a development harness, not a Tracker integration or a user installer.
It starts the actual pinned Spoolman backend on a reserved loopback socket with
a new temporary SQLite database. It cannot take a URL to an existing server.
It creates fake spools and deliberately double-charges them to establish API
semantics. It stops the server and removes its temporary inventory on exit.
No printer or Tracker process is used.

## Pin and setup

- Spoolman: `v0.27.1`, commit `ff8efd517b76a4b2783f29c89e9b9fbcd8cd167b`.
- Python tested: 3.12.16; dependencies installed from upstream `uv.lock`.
- `uv.lock` SHA256: `1217af987ae4063690a9dcb1b27cb4af59a19b5a0988cf567ce5e7ba3eae6c75`.
- Official `spoolman.zip` SHA256:
  `77ba10fa505a42cef606eabec1a7c9a5b93c51dc40067456a29a7d9480ef27d6`.

Use a fresh directory; do not run these commands in a user's Spoolman installation:

```sh
git clone --depth 1 --branch v0.27.1 https://github.com/Donkie/Spoolman.git /tmp/tracker-spoolman-upstream
cd /tmp/tracker-spoolman-upstream
UV_CACHE_DIR=/tmp/tracker-spoolman-cache UV_PYTHON_INSTALL_DIR=/tmp/tracker-spoolman-python uv sync --frozen --no-dev --python 3.12
curl -fL https://github.com/Donkie/Spoolman/releases/download/v0.27.1/spoolman.zip -o /tmp/tracker-spoolman-release.zip
```

Verify the archive checksum before extracting **only** `client_v2/build/` and
`client/dist/` into the source checkout. The upstream main application needs
these prebuilt client directories even when testing only REST endpoints. Do
not replace the pinned backend source or its lock file with archive contents.

From the Tracker checkout:

```sh
/tmp/tracker-spoolman-upstream/.venv/bin/python dev/spoolman/contract_probe.py \
  --upstream /tmp/tracker-spoolman-upstream \
  --output /tmp/tracker-spoolman-probe-results
```

The harness requires permission to bind local sockets. It currently targets
macOS/Linux (`pass_fds`); Windows execution has not been verified. It disables
external catalog downloads, update checks and automatic backups in the child
process. It does not change host environment settings. The normal upstream
startup, migrations, middleware and REST API are used without monkeypatching.

Outputs: `results.json`, live server `openapi.json`, and `server.log`. Keep these
generated files outside tracked source. Exit code 0 means all contract assertions
passed; some assertions intentionally prove unsafe server behavior. A lost
response test uses a loopback proxy that forwards the request, receives the
committed response and then closes the client connection without forwarding it.

The 403 test exercises upstream browser-origin protection, not authentication.
Reverse-proxy authentication, HTTPS, non-SQLite backends and Windows are outside
this probe. The shutdown observation records server unavailability separately.

Upstream remains an independent MIT-licensed project; its source/dependencies
are downloaded for testing and are not vendored into Tracker.
