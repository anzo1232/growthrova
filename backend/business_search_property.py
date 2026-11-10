"""Owner preparation only; no grant, property verification or read authority."""
import re
from urllib.parse import urlsplit


def normalise(value):
    from business_marketing_drafts import MarketingDraftError, _text
    if not isinstance(value, dict) or set(value) != {'propertyId', 'notes'}:
        raise MarketingDraftError('Use the supported search property request fields.')
    ident = _text(value['propertyId'], 'Search Console property', 512)
    notes = _text(value['notes'], 'search connection notes', 2000)
    if ident:
        # Preserve the exact prefix/path/trailing slash: these identify different
        # Search Console properties. A website URL is never silently converted.
        domain = ident.removeprefix('sc-domain:')
        if not ident.startswith('sc-domain:'):
            try:
                url = urlsplit(ident)
                domain = url.hostname or ''
                if (url.scheme not in ('https', 'http') or url.username or url.password
                        or url.query or url.fragment or url.port not in (None, 80, 443)):
                    raise ValueError()
            except ValueError:
                raise MarketingDraftError('Copy the exact domain or URL-prefix property from Search Console.') from None
        labels = domain.split('.')
        if (len(domain) > 253 or len(labels) < 2
                or any(not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', label) for label in labels)
                or (ident.startswith('sc-domain:') and domain != domain.lower())
                or '\\' in ident or any(ord(c) <= 32 or ord(c) == 127 for c in ident)):
            raise MarketingDraftError('Use a domain property such as sc-domain:example.com or the exact HTTP(S) URL-prefix property.')
    return {'propertyId': ident, 'notes': notes}
