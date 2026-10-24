"""The confined runner of a learned script, started by ``Library.run`` in a child process.

    python -m probandia.library_run --script <file> --hosts a,b --state <dir> --args '<json>'

The parent has already reduced the environment to the declared variables. Here
the network is reduced to the declared hosts: every name resolution goes
through a guard, and ``http`` is the engine's client with ``allow_hosts``. The
script's ``run(args, http)`` returns rows; the last line printed is one JSON
object: ``{"ok": true, "rows": […]}`` or ``{"ok": false, "error": "…"}``.

What would get round this guard is refused before the script is kept or run
(``library.escapes``, an ``ast`` reading of its source): another process
(``subprocess``, ``multiprocessing``, ``os.system``, ``os.exec*``, ``os.spawn*``…),
a raw socket (``socket``, ``ssl``), native code (``ctypes``, ``cffi``), and the
imports the reading cannot follow (``importlib``, ``__import__``, ``exec``, ``eval``).

The limit that remains: there is no sandbox of the file system. The script runs
as the user, in the project's folder, and may read or write any file the user
can; only its network and its environment are reduced. A script is trusted
(``library trust``) by a person who has read it.
"""
import argparse
import importlib.util
import json
import socket
import sys


def confine(hosts):
    allowed = {h.lower() for h in hosts}
    real = socket.getaddrinfo

    def guard(host, *args, **kwargs):
        name = (host.decode() if isinstance(host, bytes) else str(host or "")).lower()
        if name not in allowed:
            raise PermissionError(f"host {name} is not declared by this script")
        return real(host, *args, **kwargs)
    socket.getaddrinfo = guard


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--script", required=True)
    p.add_argument("--hosts", default="")
    p.add_argument("--state", required=True)
    p.add_argument("--args", default="{}")
    a = p.parse_args(argv)
    hosts = [h for h in a.hosts.split(",") if h]
    confine(hosts)
    try:
        import probandia  # noqa: F401 — the vendored libraries
        from probandia.util.http import Client

        http = Client(a.state, allow_hosts=hosts)
        spec = importlib.util.spec_from_file_location("learned_script", a.script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not hasattr(module, "run"):
            raise RuntimeError("no run(args, http) entry point")
        rows = module.run(json.loads(a.args), http)
        if isinstance(rows, dict):
            rows = rows.get("rows", rows.get("results", [rows]))
        print(json.dumps({"ok": True, "rows": rows}, ensure_ascii=False, default=str))
        return 0
    except BaseException as err:  # noqa: BLE001 — every failure is the script's answer
        print(json.dumps({"ok": False, "error": f"{type(err).__name__}: {err}"[:400]}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
