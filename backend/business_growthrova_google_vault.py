"""Explicitly keyed tenant grant vault; never reads env/files or grants execution.

The host supplies a dedicated Fernet key and fresh authority callback. Backup/key
rotation, installing the vault and connecting consumers are separate operator
work. Consumers must load with their exact version and recheck before releasing
observations or dispatch; a stored grant alone is never a paid adapter binding.
"""
from contextlib import closing
import hashlib

from business_growthrova_grants import BusinessGrantVault


class GoogleGrantVault(BusinessGrantVault):
    def __init__(self, repo, key, authorised, *, provider='google'):
        if provider not in ('google', 'search'):
            raise ValueError('Unsupported Google grant namespace')
        self.refresh_table = 'growthrova_' + provider + '_refreshes'
        super().__init__(repo, key, authorised, provider)
        with closing(repo._connect()) as con:
            con.execute(f'''CREATE TABLE IF NOT EXISTS {self.refresh_table}(
                owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL,
                version TEXT NOT NULL, token_hash TEXT NOT NULL,
                PRIMARY KEY(owner_id,organisation_id))''')
            con.commit()

    def refresh_pending(self, scope, version):
        self._check(scope)
        with closing(self.repo._connect()) as con:
            row = con.execute(f'SELECT version FROM {self.refresh_table} WHERE owner_id=? AND organisation_id=?', scope).fetchone()
        self._check(scope)
        return bool(row and row['version'] == version)

    def refresh(self, scope, version, grant, exchange):
        """One durable attempt; uncertain refresh requires a new consent version.

        No transaction spans HTTP. The intent survives a crash; grant replacement
        and intent removal commit together, so lost acknowledgement is recoverable.
        """
        token_hash = hashlib.sha256(grant['accessToken'].encode()).hexdigest()
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            self._check(scope)
            current = self.load(scope, version)
            if current != grant:
                return current  # Another completed refresh won before our claim.
            row = con.execute(f'SELECT version FROM {self.refresh_table} WHERE owner_id=? AND organisation_id=?', scope).fetchone()
            if row and row['version'] == version:
                raise ValueError('Refresh unconfirmed; reconnect through Google')
            con.execute(f'INSERT OR REPLACE INTO {self.refresh_table} VALUES(?,?,?,?)', (*scope, version, token_hash))
            self._check(scope)
            con.commit()
        updated = exchange(grant)
        encrypted = self.cipher.encrypt(self._payload(scope, version, updated))
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            self._check(scope)
            row = con.execute(f'SELECT version,token_hash FROM {self.refresh_table} WHERE owner_id=? AND organisation_id=?', scope).fetchone()
            if not row or (row['version'], row['token_hash']) != (version, token_hash) or self.load(scope, version) != grant:
                raise ValueError('Grant changed during refresh')
            con.execute(f'UPDATE {self.table} SET encrypted_grant=? WHERE owner_id=? AND organisation_id=? AND version=?', (encrypted, *scope, version))
            con.execute(f'DELETE FROM {self.refresh_table} WHERE owner_id=? AND organisation_id=?', scope)
            self._check(scope)
            con.commit()
        return self.load(scope, version)
