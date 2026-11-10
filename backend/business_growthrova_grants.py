"""Shared explicitly keyed tenant vault. No ambient keys or execution binding."""
from contextlib import closing
import json
import re
from cryptography.fernet import Fernet


class BusinessGrantVault:
    def __init__(self, repo, key, authorised, provider):
        if provider not in ('google', 'meta', 'search'):
            raise ValueError('Unsupported grant provider')
        self.provider = provider
        self.table = 'growthrova_' + provider + '_grants'
        if not callable(authorised):
            raise ValueError('Dedicated grant storage authority required')
        self.repo, self.cipher, self.authorised = repo, Fernet(key), authorised
        with closing(repo._connect()) as con:
            con.execute(f'''CREATE TABLE IF NOT EXISTS {self.table}(
                owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL,
                version TEXT NOT NULL, encrypted_grant BLOB NOT NULL,
                PRIMARY KEY(owner_id,organisation_id))''')
            con.commit()

    def _check(self, scope):
        if (not isinstance(scope, tuple) or len(scope) != 2
                or any(not isinstance(v, str) or not v for v in scope)
                or self.authorised(*scope) is not True):
            raise PermissionError('Grant storage unavailable')

    def status(self, scope):
        self._check(scope)
        with closing(self.repo._connect()) as con:
            row = con.execute(f'SELECT version FROM {self.table} WHERE owner_id=? AND organisation_id=?', scope).fetchone()
        self._check(scope)
        return dict(version=row['version'] if row else None)

    def replace(self, scope, expected_version, version, grant):
        self._check(scope)
        if not isinstance(version, str) or not re.fullmatch(r'[a-f0-9]{32}', version):
            raise ValueError('Invalid grant version')
        # Encrypt the scope/version with the secret to prevent ciphertext swaps
        # from relabelling another business's otherwise valid token payload.
        encrypted = self.cipher.encrypt(self._payload(scope, version, grant))
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute(f'SELECT version FROM {self.table} WHERE owner_id=? AND organisation_id=?', scope).fetchone()
            old = row['version'] if row else None
            if old == version:
                return  # Recovery never rewrites a previously stored grant.
            if old != expected_version:
                raise ValueError('Grant version changed')
            self._check(scope)
            con.execute(f'INSERT OR REPLACE INTO {self.table} VALUES(?,?,?,?)', (*scope, version, encrypted))
            self._check(scope)
            con.commit()

    def load(self, scope, version):
        """Server-only, exact-version read for a separately authorised consumer."""
        self._check(scope)
        with closing(self.repo._connect()) as con:
            row = con.execute(f'SELECT version,encrypted_grant FROM {self.table} WHERE owner_id=? AND organisation_id=?', scope).fetchone()
        if not row or row['version'] != version:
            raise ValueError('Grant version changed')
        value = json.loads(self.cipher.decrypt(row['encrypted_grant']))
        if (value['scope'] != list(scope) or value['version'] != version
                or value.get('provider', 'google') != self.provider):
            raise ValueError('Grant scope changed')
        if self.status(scope)['version'] != version:
            raise ValueError('Grant version changed')
        return value['grant']

    def _payload(self, scope, version, grant):
        value = dict(scope=list(scope), version=version, grant=grant)
        # Google retains its existing ciphertext representation for compatibility.
        if self.provider != 'google':
            value['provider'] = self.provider
        return json.dumps(value).encode()
