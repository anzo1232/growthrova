// Suggestions require an owner's choice; a shared address is not proof of identity.
export function intakeMatches(contacts, submission){
  const email=value=>(value||'').trim().toLowerCase();
  const phone=value=>(value||'').replace(/[ ()+.\-]/g,'');
  const received=submission.contact;
  return contacts.filter(item=>Boolean(received.email&&email(received.email)===email(item.data.email)
    ||received.phone&&phone(received.phone)===phone(item.data.phone)));
}

export function intakeNote(notes, submission){
  const marker=`[Form submission ${submission.campaignId}/${submission.id}]`;
  if((notes||'').includes(marker))throw Error('This submission reference is already in the current notes. Review the existing wording.');
  const evidence=`${marker}\nReceived ${new Date(submission.receivedAt*1000).toISOString()}\nSubmitted name: ${submission.contact.name}\nSubmitted email: ${submission.contact.email||'Not supplied'}\nSubmitted phone: ${submission.contact.phone||'Not supplied'}\n${submission.contact.message||'No message supplied.'}`;
  const result=[notes,evidence].filter(Boolean).join('\n\n');
  // Match the server's Unicode character bound, without truncating the original.
  if([...result].length>2000)throw Error('The complete submission and current notes exceed the 2,000-character notes limit. Keep the original in the inbox and write a shorter factual summary with its submission reference instead.');
  return result;
}
