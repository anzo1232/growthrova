"""Contact-free saved message evidence. Read-only; never contacts a provider."""
import json

from business_growthrova_followup import receipt


STATES = ('queued', 'claimed', 'dispatching', 'uncertain', 'paused', 'blocked',
          'cancelled', 'failed', 'sent', 'simulated')
EVENTS = {
    'email': dict(positive={'email.sent', 'email.delivered'},
                  delivered={'email.delivered'}, read=set(),
                  negative={'email.bounced', 'email.failed'}, complaint={'email.complained'}),
    'whatsapp': dict(positive={'sent', 'delivered', 'read'},
                     delivered={'delivered'}, read={'read'},
                     negative={'failed', 'undelivered'}, complaint=set()),
}


def followup_delivery_results(con, scope, now):
    totals = dict(totalJobs=0, sentConfirmations=0, simulations=0, unresolvedJobs=0,
                  unconfirmedCompletions=0, deliveredEventJobs=0, readEventJobs=0,
                  negativeEventJobs=0, complaintEventJobs=0)
    campaigns, groups = {}, {}
    # The indexed event lookup binds evidence to both job and remote identity.
    # Inbound events (no job) and unrelated receipt references cannot contribute.
    rows = con.execute('''SELECT r.document_id,d.revision,
        json_extract(d.document_json,'$.name') AS name,r.mode,r.state,r.receipt_json,
        json_extract(r.snapshot_json,'$.channel') AS channel,
        COALESCE(json_extract(r.snapshot_json,'$.subjectKind'),'enquiry') AS subject,
        (SELECT json_group_array(json_extract(e.evidence_json,'$.status'))
         FROM growthrova_sender_events e WHERE e.job_id=r.job_id
           AND json_extract(e.evidence_json,'$.reference')=json_extract(r.receipt_json,'$.id')) AS events
        FROM growthrova_followup_jobs r
        JOIN marketing_drafts d ON d.id=r.document_id
        JOIN offline_document_owners o ON o.draft_id=d.id
        WHERE r.owner_id=? AND r.organisation_id=?
          AND o.owner_id=r.owner_id AND o.organisation_id=r.organisation_id
        ORDER BY d.updated DESC,r.document_id,r.mode,r.state''', scope)
    for row in rows:
        channel = row['channel'] if row['channel'] in EVENTS else 'unknown'
        mode = row['mode'] if row['mode'] in ('live', 'simulation') else 'unknown'
        state = row['state'] if row['state'] in STATES else 'unknown'
        subject = row['subject'] if row['subject'] in ('enquiry', 'prospect') else 'unknown'
        parsed = receipt(json.loads(row['receipt_json'])) if row['receipt_json'] else None
        # The callback handler can confirm a send while retaining the original
        # accepted/unknown receipt outcome. Positive event evidence is separate.
        events = set(json.loads(row['events'])) if mode == 'live' and parsed and channel in EVENTS else set()
        policy = EVENTS.get(channel)
        sent = bool(mode == 'live' and state == 'sent' and parsed and policy
                    and (parsed['outcome'] == 'sent' or events & policy['positive']))
        simulated = bool(mode == 'simulation' and state == 'simulated' and parsed
                         and parsed['outcome'] == 'simulated' and channel in EVENTS)
        counts = dict.fromkeys(totals, 0)
        counts.update(totalJobs=1, sentConfirmations=int(sent), simulations=int(simulated),
                      unresolvedJobs=int(state in ('dispatching', 'uncertain')),
                      unconfirmedCompletions=int(state in ('sent', 'simulated') and not (sent or simulated)))
        for key, category in (('deliveredEventJobs', 'delivered'), ('readEventJobs', 'read'),
                              ('negativeEventJobs', 'negative'), ('complaintEventJobs', 'complaint')):
            counts[key] = int(bool(policy and events & policy[category]))
        campaign = campaigns.setdefault(row['document_id'], dict(
            campaignId=row['document_id'], name=row['name'], revision=row['revision'],
            **dict.fromkeys(totals, 0), jobs=[]))
        key = (row['document_id'], channel, subject, mode, state)
        if key not in groups:
            group = dict(channel=channel, subject=subject, mode=mode, savedState=state,
                         **dict.fromkeys(totals, 0))
            groups[key] = group
            campaign['jobs'].append(group)
        for field, count in counts.items():
            totals[field] += count
            campaign[field] += count
            groups[key][field] += count
    return dict(scope='all_saved_followup_jobs', observedAt=now,
                **totals, campaigns=list(campaigns.values()))
