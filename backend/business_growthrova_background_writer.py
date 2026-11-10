"""Bounded background Responses transport. No automatic submission retries."""
import json
import re
import time

import requests

URL = 'https://api.openai.com/v1/responses'
RESPONSE_SECONDS = 25


def diagnostic_identity(value, key, pattern):
    """Retain only bounded opaque provider IDs, never credentials or arbitrary text."""
    return value if isinstance(value, str) and key not in value and re.fullmatch(pattern, value) else None


def record_http_outcome(config, response, diagnostic):
    diagnostic['httpStatus'] = response.status_code
    request_id = diagnostic_identity(getattr(response, 'headers', {}).get('x-request-id'),
                                     config.key, r'[A-Za-z0-9_-]{1,200}')
    if request_id:
        diagnostic['requestId'] = request_id
    if response.status_code != 200:
        diagnostic['category'] = 'http_error'


def exchange(config, method, *, payload=None, response_id=None, http=None,
             client_request_id=None, diagnostic=None):
    if response_id is not None and (not isinstance(response_id, str)
            or not re.fullmatch(r'resp_[A-Za-z0-9_-]{8,200}', response_id)):
        raise ValueError('Invalid saved planning response ID')
    diagnostic = diagnostic if diagnostic is not None else {}
    diagnostic['category'] = 'transport_error'
    started = time.monotonic()
    try:
        with requests.Session() as session:
            session.trust_env = False
            options = dict(headers={'Authorization': 'Bearer '+config.key, 'Content-Type': 'application/json'},
                           timeout=(5, RESPONSE_SECONDS), allow_redirects=False, stream=True)
            if client_request_id is not None:
                if not isinstance(client_request_id, str) or not re.fullmatch(r'gw_[a-f0-9]{32}', client_request_id):
                    raise ValueError('Invalid planning correlation ID')
                options['headers']['X-Client-Request-Id'] = client_request_id
            if payload is not None:
                options['json'] = {**payload, 'background': True, 'store': True}
            with getattr(http or session, method)(URL+('/'+response_id if response_id else ''), **options) as response:
                record_http_outcome(config, response, diagnostic)
                if response.status_code != 200:
                    raise ValueError('Background planning request was rejected')
                body = bytearray()
                for chunk in response.iter_content(8192):
                    # The socket timeout limits inactivity, not aggregate time.
                    # Check elapsed time at each yielded chunk as well. This
                    # does not interrupt a read already in progress.
                    if time.monotonic() - started >= RESPONSE_SECONDS:
                        raise requests.Timeout('Background planning response exceeded elapsed budget')
                    body.extend(chunk)
                    if len(body) > 200000:
                        diagnostic['category'] = 'response_limit'
                        raise ValueError('Planning response exceeded limit')
                diagnostic['category'] = 'invalid_response'
                result = json.loads(body)
    except requests.Timeout:
        diagnostic['category'] = 'transport_timeout'
        raise
    if not isinstance(result, dict):
        raise ValueError('Invalid planning envelope')
    ident = result.get('id')
    if (not isinstance(ident, str) or not re.fullmatch(r'resp_[A-Za-z0-9_-]{8,200}', ident)
            or (response_id and ident != response_id)):
        raise ValueError('Planning response identity mismatch')
    return result
