"""The journal's HTTP API as the captain's login, for the scripts that
write his entries: report.py (a report's entry) and release-import.py (a
version's, at each deploy and in the import). Moved here from report.py so
both read the login and the server one way.

    env_file_value(key)    key's value in ~/.env, never sourced
    journal_login()        (url, user, password)
    api(method, path, body=None, timeout=60) -> (status, parsed answer)

The login is LCARS_AUTH_USER and _PASS, the environment then ~/.env; the
server LCARS_URL, else ~/.env's LCARS_CREW_URL, else http://127.0.0.1:8080
(as crew_tool.py finds it).
"""

import base64
import json
import os
import urllib.error
import urllib.request


def env_file_value(key):
    """key's value in ~/.env (KEY=value lines, never sourced), or "": an
    engineer's shell, or Number One's, does not source it."""
    try:
        with open(os.path.join(os.path.expanduser("~"), ".env")) as f:
            for ln in f:
                k, eq, v = ln.strip().removeprefix("export ").partition("=")
                if eq and k.strip() == key:
                    return v.strip().strip("'\"")
    except OSError:
        pass
    return ""


def journal_login():
    """(url, user, password): the captain's login, from the environment, then
    ~/.env, the URL as crew_tool.py finds the server."""
    url = (os.environ.get("LCARS_URL") or env_file_value("LCARS_CREW_URL")
           or "http://127.0.0.1:8080").rstrip("/")
    if os.environ.get("LCARS_AUTH_USER"):
        return url, os.environ["LCARS_AUTH_USER"], os.environ.get("LCARS_AUTH_PASS", "")
    return url, env_file_value("LCARS_AUTH_USER"), env_file_value("LCARS_AUTH_PASS")


def api(method, path, body=None, timeout=60):
    """(status, parsed answer); status 0 when the server did not answer."""
    url, user, pw = journal_login()
    headers = {"Content-Type": "application/json"}
    if user:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
    # raw UTF-8, never \u escapes, which the server's reader keeps as letters
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(url + path, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, text = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, {"error": f"{url}: {e}"}
    try:
        return status, json.loads(text)
    except ValueError:
        return status, {"error": text[:300]}
