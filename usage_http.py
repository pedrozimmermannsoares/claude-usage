"""HTTP client shared by the usage scripts."""

import json
import urllib.error
import urllib.parse
import urllib.request


def urlopen_same_origin(req, timeout):
    """Follow redirects only within the original scheme, host and port."""
    def origin(url):
        parts = urllib.parse.urlsplit(url)
        port = parts.port
        if port is None:
            port = {"http": 80, "https": 443}.get(parts.scheme)
        return parts.scheme, parts.hostname, port

    class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            # A refused redirect becomes HTTPError, preserving the 3xx response.
            if origin(request.full_url) != origin(newurl):
                return None
            return super().redirect_request(request, fp, code, msg, headers, newurl)

    return urllib.request.build_opener(SameOriginRedirectHandler()).open(req, timeout=timeout)


def api_get(url, access_token, beta_header):
    """GET a Claude OAuth endpoint. Return (status_int, json_or_text)."""
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", "Bearer %s" % access_token)
    req.add_header("anthropic-beta", beta_header)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "claude-usage-cli")
    try:
        with urlopen_same_origin(req, timeout=30) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body)
            except Exception:
                return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body
    except Exception as e:
        return 0, "network error: %s" % e
