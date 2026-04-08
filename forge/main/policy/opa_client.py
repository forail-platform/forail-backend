"""Tiny HTTP wrapper around the OPA Data API.

Deliberately uses bare `requests` instead of pulling another dependency.
The OPA REST surface we need is small:
  PUT    /v1/policies/{id}        upload Rego module
  DELETE /v1/policies/{id}        remove Rego module
  POST   /v1/data/{path}          evaluate input against a package
"""

import json
import logging

logger = logging.getLogger('forge.main.policy.opa_client')


class OPAUnavailable(RuntimeError):
    """Raised when the OPA sidecar is unreachable or returns a non-2xx."""
    pass


def _post_json(url, payload, timeout):
    import requests
    r = requests.post(url, json=payload, timeout=timeout / 1000.0)
    if r.status_code >= 400:
        raise OPAUnavailable(f'OPA POST {url} returned {r.status_code}: {r.text[:200]}')
    return r.json()


def _put_text(url, body, timeout):
    import requests
    r = requests.put(url, data=body.encode('utf-8'),
                     headers={'Content-Type': 'text/plain'},
                     timeout=timeout / 1000.0)
    if r.status_code >= 400:
        raise OPAUnavailable(f'OPA PUT {url} returned {r.status_code}: {r.text[:200]}')


def _delete(url, timeout):
    import requests
    r = requests.delete(url, timeout=timeout / 1000.0)
    if r.status_code >= 400 and r.status_code != 404:
        raise OPAUnavailable(f'OPA DELETE {url} returned {r.status_code}: {r.text[:200]}')


def evaluate(server_url, package_path, input_doc, timeout_ms=2000):
    """Run input_doc against the package at package_path. Returns the parsed
    `result` value (typically a dict). Raises OPAUnavailable on errors."""
    if not server_url:
        raise OPAUnavailable('OPA_SERVER_URL is not set')
    path = package_path.replace('.', '/')
    url = f'{server_url.rstrip("/")}/v1/data/{path}'
    try:
        body = _post_json(url, {'input': input_doc}, timeout_ms)
    except OPAUnavailable:
        raise
    except Exception as e:
        raise OPAUnavailable(str(e)) from e
    if not isinstance(body, dict) or 'result' not in body:
        # OPA returns {} when the package doesn't exist — treat as no rules
        return {}
    return body['result']


def upload_policy(server_url, policy_id, rego_module, timeout_ms=2000):
    if not server_url:
        raise OPAUnavailable('OPA_SERVER_URL is not set')
    url = f'{server_url.rstrip("/")}/v1/policies/forge_{policy_id}'
    _put_text(url, rego_module, timeout_ms)


def delete_policy(server_url, policy_id, timeout_ms=2000):
    if not server_url:
        raise OPAUnavailable('OPA_SERVER_URL is not set')
    url = f'{server_url.rstrip("/")}/v1/policies/forge_{policy_id}'
    _delete(url, timeout_ms)


def parse_decision(result):
    """Normalize OPA output into (warns: list[str], denies: list[str]).

    OPA packages can expose any of:
      result.deny  -> set/list of strings
      result.warn  -> set/list of strings
      result.violations -> [{"severity": "warn"|"deny", "message": "..."}]

    A bare bool/string is also tolerated for the simplest "default deny := false"
    pattern.
    """
    warns = []
    denies = []
    if not result:
        return warns, denies

    if isinstance(result, bool):
        if result:
            denies.append('Policy denied launch.')
        return warns, denies

    if isinstance(result, str):
        denies.append(result)
        return warns, denies

    if isinstance(result, list):
        # Treat list as denies for compatibility
        for item in result:
            if isinstance(item, str):
                denies.append(item)
            elif isinstance(item, dict):
                msg = item.get('message') or json.dumps(item)
                if item.get('severity') == 'warn':
                    warns.append(msg)
                else:
                    denies.append(msg)
        return warns, denies

    if isinstance(result, dict):
        warn_val = result.get('warn')
        if isinstance(warn_val, (list, tuple, set)):
            for entry in warn_val:
                warns.append(entry if isinstance(entry, str) else str(entry))
        deny_val = result.get('deny')
        if isinstance(deny_val, (list, tuple, set)):
            for entry in deny_val:
                denies.append(entry if isinstance(entry, str) else str(entry))
        elif isinstance(deny_val, bool) and deny_val:
            denies.append('Policy denied launch.')
        violations = result.get('violations')
        if isinstance(violations, (list, tuple)):
            for v in violations:
                if not isinstance(v, dict):
                    continue
                msg = v.get('message') or json.dumps(v)
                if v.get('severity') == 'warn':
                    warns.append(msg)
                else:
                    denies.append(msg)

    return warns, denies
