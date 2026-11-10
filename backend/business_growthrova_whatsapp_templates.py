"""Bounded text-only templates from explicit operator configuration, never HTTP input.

The operator must verify the exact twilio/text body, language and WhatsApp approval
against this dedicated account, rotate version on edits, and remove paused/rejected
templates. Fresh grants, suppression and template costs need separate authority.
No provider discovery, credentials, template registration or default permission.
"""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class WhatsAppTextTemplate:
    owner_id: str
    organisation_id: str
    account_id: str
    sender_version: str
    content_sid: str
    version: str
    name: str
    language: str
    body: str
    variable_labels: tuple = ()
    approved: bool = False


def text(value, maximum):
    return (isinstance(value, str) and 0 < len(value) <= maximum and bool(value.strip())
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def catalogue(binding, resolver):
    if not binding or not callable(resolver):
        return []
    try:
        values = resolver(binding)
        if not isinstance(values, (tuple, list)) or len(values) > 30:
            return []
        result = []
        for item in values:
            if (not isinstance(item, WhatsAppTextTemplate) or item.approved is not True
                    or (item.owner_id, item.organisation_id, item.account_id, item.sender_version) !=
                    (binding.owner_id, binding.organisation_id, binding.account_id, binding.version)
                    or not isinstance(item.content_sid, str) or not re.fullmatch(r'HX[a-fA-F0-9]{32}', item.content_sid)
                    or not text(item.version, 100) or not text(item.name, 100) or not text(item.language, 35)
                    or not isinstance(item.body, str) or not 0 < len(item.body) <= 1600
                    or not item.body.strip() or any((ord(c) < 32 and c != '\n') or ord(c) == 127 for c in item.body)
                    or not isinstance(item.variable_labels, tuple) or len(item.variable_labels) > 10
                    or any(not text(label, 100) for label in item.variable_labels)):
                return []
            keys = re.findall(r'\{\{([1-9][0-9]*)\}\}', item.body)
            remainder = re.sub(r'\{\{[1-9][0-9]*\}\}', '', item.body)
            if ('{{' in remainder or '}}' in remainder or
                    set(keys) != {str(n+1) for n in range(len(item.variable_labels))}):
                return []
            result.append(dict(contentSid=item.content_sid, version=item.version, name=item.name,
                               language=item.language, body=item.body, variableLabels=list(item.variable_labels)))
        return result if len({item['contentSid'] for item in result}) == len(result) else []
    except Exception:
        return []


def prepare(templates, selection):
    if not isinstance(selection, dict) or set(selection) != {'contentSid', 'version', 'variables'}:
        raise ValueError('Choose a configured template and review its values.')
    item = next((t for t in templates if t['contentSid'] == selection['contentSid']
                 and t['version'] == selection['version']), None)
    variables = selection['variables']
    if (not item or not isinstance(variables, dict) or
            set(variables) != {str(n+1) for n in range(len(item['variableLabels']))} or
            any(not text(value, 200) or '{{' in value or '}}' in value for value in variables.values())):
        raise ValueError('Template or values changed. Check status and review again.')
    wording = re.sub(r'\{\{([1-9][0-9]*)\}\}', lambda match: variables[match[1]], item['body'])
    if len(wording) > 1600:
        raise ValueError('The completed template exceeds 1600 characters.')
    return dict(contentSid=item['contentSid'], version=item['version'], name=item['name'],
                language=item['language'], body=item['body'], variables=dict(variables)), wording
