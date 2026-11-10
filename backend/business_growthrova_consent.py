"""Shared durable private consent protocol. Provider implementations own the wire.

No credentials in attempts or responses. Table names come only from fixed server
provider identifiers; no request value can select a table or callback.
"""
from contextlib import closing
from dataclasses import replace
import hashlib
import re
import secrets
from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError


def _plain(value, maximum):
    return isinstance(value, str) and 0 < len(value) <= maximum and not any(ord(c) < 33 for c in value)


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class BusinessConsent:
    def __init__(self, repo, config, provider):
        if provider not in ('google', 'meta', 'search'):
            raise ValueError('Unsupported business consent provider')
        self.table = 'growthrova_' + provider + '_connections'
        self.repo, self.config = repo, config
        if self.config.enabled is True and self.config.vault_key:
            if self.config.vault is not None:
                raise ValueError('Configure one dedicated business grant vault')
            vault = self.make_vault(repo, self.config.vault_key, self.config.authorised)
            self.config = replace(self.config, vault=vault, vault_key=b'')
        with closing(repo._connect()) as con:
            con.execute(f'''CREATE TABLE IF NOT EXISTS {self.table}(
              owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL, attempt_id TEXT PRIMARY KEY,
              state_hash TEXT NOT NULL UNIQUE, verifier TEXT, config_version TEXT NOT NULL,
              expected_version TEXT, created REAL NOT NULL, expires REAL NOT NULL,
              state TEXT NOT NULL)''')
            con.commit()

    def permitted(self, scope):
        if not self.available() or self.config.authorised(*scope) is not True:
            raise MarketingDraftError('Business connection is unavailable for this business. Saved preparation is preserved.', 'connection_unavailable', 503)

    def version(self, scope):
        value = self.config.vault.status(scope)
        if (not isinstance(value, dict) or set(value) != {'version'}
                or value['version'] is not None and not re.fullmatch(r'[a-f0-9]{32}', str(value['version']))):
            raise ValueError('Invalid vault metadata')
        return value['version']

    def status(self, scope):
        if not self.available():
            return dict(available=False, connected=False, connectionVersion=None, attempt=None)
        self.permitted(scope)
        version = self.version(scope)
        with closing(self.repo._connect()) as con:
            row = con.execute(f'SELECT * FROM {self.table} WHERE owner_id=? AND organisation_id=? ORDER BY created DESC, rowid DESC LIMIT 1', scope).fetchone()
        attempt = None
        if row:
            state = row['state']
            # Vault acknowledgement may have been lost after durable replacement.
            if version == row['attempt_id']:
                state = 'stored'
            elif state == 'issued' and row['expires'] <= self.config.clock():
                state = 'expired'
            attempt = dict(id=row['attempt_id'], state=state, expiresAt=row['expires'])
        self.permitted(scope)
        pending = getattr(self.config.vault, 'refresh_pending', None)
        refresh_review = bool(version and callable(pending) and pending(scope, version))
        self.permitted(scope)
        return dict(available=True, connected=version is not None, connectionVersion=version,
                    attempt=attempt, refreshNeedsReview=refresh_review)

    def start(self, con, scope):
        self.permitted(scope)
        now = self.config.clock()
        version = self.version(scope)
        con.execute(f"UPDATE {self.table} SET state='stored' WHERE owner_id=? AND organisation_id=? AND attempt_id=? AND state='exchanging'", (*scope, version))
        rows = con.execute(f'SELECT attempt_id,state FROM {self.table} WHERE owner_id=? AND organisation_id=?', scope).fetchall()
        if any(r['state'] == 'exchanging' and r['attempt_id'] != version for r in rows):
            raise MarketingDraftError('A connection is still being saved. Check connection status before starting again; support can review an interrupted exchange.', 'connection_pending', 409)
        # Retain a bounded day of recovery metadata. No tokens or codes persist.
        con.execute(f'DELETE FROM {self.table} WHERE owner_id=? AND organisation_id=? AND created<? AND state!=?', (*scope, now-86400, 'exchanging'))
        count = con.execute(f'SELECT COUNT(*) FROM {self.table} WHERE owner_id=? AND organisation_id=?', scope).fetchone()[0]
        if count >= 100:
            raise MarketingDraftError('Connection attempts reached the daily storage bound. Return later or request support.', 'connection_limit', 429)
        con.execute(f"UPDATE {self.table} SET state='superseded',verifier=NULL WHERE owner_id=? AND organisation_id=? AND state='issued'", scope)
        state, verifier, ident = secrets.token_urlsafe(32), secrets.token_urlsafe(48), secrets.token_hex(16)
        con.execute(f'INSERT INTO {self.table} VALUES(?,?,?,?,?,?,?,?,?,?)',
            (*scope, ident, _digest(state), verifier, self.config.version, version, now, now+600, 'issued'))
        url = self.authorization_url(state, verifier)
        return dict(url=url, state=state, attemptId=ident, expiresAt=now+600, redirectUri=self.config.redirect_uri)


def register_business_consent_routes(app, repo, service, provider, *, revalidate=None):
    if provider not in ('google', 'meta', 'search'):
        raise ValueError('Unsupported business consent provider')
    app.extensions['growthrova_' + provider + '_connection'] = service
    endpoint = '/api/growthrova/organisations/<organisation_id>/' + provider + '-connection'

    def checked(organisation_id, scope):
        error = revalidate() if revalidate else None
        if error is not None:
            return error
        if repo._scope(organisation_id) != scope:
            raise MarketingDraftError('Business access changed.', 'access_denied', 403)
        return None

    @app.get(endpoint, endpoint=provider+'_connection_status')
    def business_connection_status(organisation_id):
        scope = repo._scope(organisation_id)
        try:
            result = service.status(scope)
        except MarketingDraftError:
            raise
        except Exception:
            raise MarketingDraftError('Connection status could not be checked. Saved preparation is preserved.', 'connection_unavailable', 503)
        error = checked(organisation_id, scope)
        return error if error is not None else jsonify(result)

    @app.post(endpoint + '/start', endpoint=provider+'_connection_start')
    def business_connection_start(organisation_id):
        scope = repo._scope(organisation_id)
        if request.get_json(silent=True) != {}:
            raise MarketingDraftError('Start a connection for the selected business without credential or redirect overrides.')
        try:
            with closing(repo._connect()) as con:
                con.execute('BEGIN IMMEDIATE')
                error = checked(organisation_id, scope)
                if error is not None:
                    return error
                result = service.start(con, scope)
                error = checked(organisation_id, scope)
                if error is not None:
                    return error
                con.commit()
            return jsonify(result)
        except MarketingDraftError:
            raise
        except Exception:
            raise MarketingDraftError('A connection link could not be prepared. Check status before trying again.', 'connection_unavailable', 503)

    @app.post(endpoint + '/complete', endpoint=provider+'_connection_complete')
    def business_connection_complete(organisation_id):
        scope = repo._scope(organisation_id)
        payload = request.get_json(silent=True)
        if (not isinstance(payload, dict) or set(payload) != {'state', 'code'}
                or not _plain(payload['state'], 100) or not _plain(payload['code'], 8192)):
            raise MarketingDraftError('Return from the secure business connection page.')
        service.permitted(scope)
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error = checked(organisation_id, scope)
            if error is not None:
                return error
            row = con.execute(f'SELECT * FROM {service.table} WHERE owner_id=? AND organisation_id=? AND state_hash=?', (*scope, _digest(payload['state']))).fetchone()
            if (not row or row['state'] != 'issued' or row['expires'] <= service.config.clock()
                    or row['config_version'] != service.config.version):
                raise MarketingDraftError('This connection attempt expired or was already used. Check saved connection status.', 'connection_used', 409)
            if service.version(scope) != row['expected_version']:
                raise MarketingDraftError('The business connection changed. Check status and start a fresh connection.', 'revision_conflict', 409)
            # Durable intent before the one exchange. A crash cannot retry a code.
            con.execute(f"UPDATE {service.table} SET state='exchanging',verifier=NULL WHERE attempt_id=?", (row['attempt_id'],))
            con.commit()
        state = 'uncertain'
        try:
            grant = service.exchange(payload['code'], row['verifier'])
            error = checked(organisation_id, scope)
            if error is not None:
                return error
            service.permitted(scope)
            # Vault CAS supplies the concurrency boundary beyond SQLite. This
            # installs no discovery or execution binding by itself.
            service.config.vault.replace(scope, row['expected_version'], row['attempt_id'], grant)
            result = service.status(scope)
            if result['connectionVersion'] != row['attempt_id']:
                raise ValueError('Vault acknowledgement missing')
            state = 'stored'
        except Exception:
            # Do not release exception/provider/token content or repeat exchange.
            state = 'uncertain'
        finally:
            with closing(repo._connect()) as con:
                con.execute(f'UPDATE {service.table} SET state=? WHERE attempt_id=?', (state, row['attempt_id']))
                con.commit()
        error = checked(organisation_id, scope)
        if error is not None:
            return error
        if state != 'stored':
            raise MarketingDraftError('Connection confirmation is missing. Check status; this code will not be exchanged again. Saved preparation is preserved.', 'connection_uncertain', 503)
        return jsonify(result)
