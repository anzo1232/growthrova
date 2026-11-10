"""Saved paid lifecycle evidence, separate from current serving and performance."""
import json

from business_growthrova_paid_delivery import receipt

ACTIONS = {
    'create_paused_only': ('created_paused', 'paused', 'creationReceipts'),
    'launch_exact_resources': ('active', 'active', 'activationReceipts'),
    'pause_exact_resources': ('remote_paused', 'paused', 'pauseReceipts'),
}


def confirmed(row):
    """Use each action's wire contract; activation/pause have no receipt ID."""
    action, mode, state = row['action'], row['mode'], row['state']
    value = json.loads(row['receipt_json']) if row['receipt_json'] else None
    if action == 'create_paused_only':
        parsed = receipt(value)
        expected = 'simulated' if mode == 'simulation' else 'paused'
        return (mode in ('live', 'simulation') and parsed is not None
                and parsed['outcome'] == expected
                and state == ('simulated' if mode == 'simulation' else 'created_paused'))
    if action not in ACTIONS or mode != 'live' or not isinstance(value, dict):
        return False
    expected_state, outcome, _ = ACTIONS[action]
    resources = json.loads(row['expected_resources']) if row['expected_resources'] else None
    if (state != expected_state or value.get('outcome') != outcome
            or not isinstance(resources, dict) or not resources.get('campaignId')
            or value.get('resources') != resources):
        return False
    if action == 'launch_exact_resources':
        limits = json.loads(row['expected_limits']) if row['expected_limits'] else None
        return isinstance(limits, dict) and bool(limits) and value.get('limits') == limits
    return True


def paid_delivery_results(con, scope, now):
    totals = dict(totalJobs=0, creationReceipts=0, activationReceipts=0,
                  pauseReceipts=0, simulations=0, unresolvedJobs=0,
                  unconfirmedCompletions=0)
    campaigns = {}
    # Never project creative copy, account configuration or full approvals.
    rows = con.execute('''SELECT r.document_id,d.revision,
        json_extract(d.document_json,'$.name') AS name,r.platform,r.mode,r.state,
        json_extract(r.snapshot_json,'$.intent') AS action,r.receipt_json,
        CASE WHEN json_extract(r.snapshot_json,'$.intent')='launch_exact_resources'
            THEN json_extract(r.snapshot_json,'$.creationReceipt.resources')
            ELSE json_extract(r.snapshot_json,'$.resources') END AS expected_resources,
        json_extract(r.snapshot_json,'$.limits') AS expected_limits
        FROM growthrova_paid_jobs r
        JOIN marketing_drafts d ON d.id=r.document_id
        JOIN offline_document_owners o ON o.draft_id=d.id
        WHERE r.owner_id=? AND r.organisation_id=?
          AND o.owner_id=r.owner_id AND o.organisation_id=r.organisation_id
        ORDER BY d.updated DESC,r.document_id,r.platform,r.mode,r.state''', scope)
    groups = {}
    for row in rows:
        campaign = campaigns.setdefault(row['document_id'], dict(
            campaignId=row['document_id'], name=row['name'], revision=row['revision'],
            **{key: 0 for key in totals}, jobs=[]))
        valid = confirmed(row)
        counts = dict.fromkeys(totals, 0)
        counts['totalJobs'] = 1
        if valid:
            counts['simulations' if row['mode'] == 'simulation' else ACTIONS[row['action']][2]] = 1
        counts['unresolvedJobs'] = int(row['state'] in ('dispatching', 'uncertain'))
        counts['unconfirmedCompletions'] = int(not valid and row['state'] in (
            'created_paused', 'active', 'remote_paused', 'simulated'))
        for key, value in counts.items():
            totals[key] += value
            campaign[key] += value
        # Unknown values are labelled without exposing arbitrary stored strings.
        action = row['action'] if row['action'] in ACTIONS else 'unknown'
        platform = row['platform'] if row['platform'] in ('meta', 'google') else 'unknown'
        mode = row['mode'] if row['mode'] in ('live', 'simulation') else 'unknown'
        state = row['state'] if row['state'] in (
            'queued', 'claimed', 'dispatching', 'uncertain', 'paused', 'blocked',
            'cancelled', 'failed', 'created_paused', 'active', 'remote_paused', 'simulated') else 'unknown'
        key = (row['document_id'], platform, mode, action, state)
        if key not in groups:
            group = dict(platform=platform, mode=mode, approvedAction=action,
                         savedState=state, count=0, confirmedReceipts=0)
            groups[key] = group
            campaign['jobs'].append(group)
        groups[key]['count'] += 1
        groups[key]['confirmedReceipts'] += int(valid)
    return dict(scope='all_saved_paid_delivery_jobs', observedAt=now,
                **totals, campaigns=list(campaigns.values()))
