/** URL state is a navigation hint only; the caller supplies authorised businesses. */
export function selectGrowthrovaBusiness(href, organisationId, {resetCampaign = false} = {}) {
  const url = new URL(href);
  if (resetCampaign || !organisationId || url.searchParams.get('growthrovaBusiness') !== organisationId) {
    url.searchParams.delete('marketingDraft');
  }
  if (organisationId) url.searchParams.set('growthrovaBusiness', organisationId);
  else url.searchParams.delete('growthrovaBusiness');
  return url;
}

export function restoreGrowthrovaBusiness(href, organisations) {
  const requested = new URL(href).searchParams.get('growthrovaBusiness');
  const matched = organisations.find(item => item.id === requested);
  const organisationId = matched?.id || organisations[0]?.id || '';
  return {
    organisationId,
    url: selectGrowthrovaBusiness(href, organisationId),
    unavailable: Boolean(requested && !matched),
  };
}
