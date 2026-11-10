"""Compile reviewed business context for planning and complete-advert inference.

This is an editorial brief, never generated artwork or an approval. No business
category selects a stock scene, palette, capability or unsupported sales claim.
"""
from copy import deepcopy
import re
from business_brand_render import EXACT_LOGO_REGION_PERCENT



def generation_brand_identity(value):
    """Send observed roles and exact-asset fingerprints, never raw logo markup."""
    if not isinstance(value, dict):
        return None
    result = deepcopy(value)
    result['logoCandidates'] = [{
        'kind': item.get('kind'), 'sha256': item.get('sha256', ''),
        'description': item.get('description', ''),
        'availability': ('exact_sanitised_candidate_requires_owner_selection'
                         if item.get('kind') == 'inline_svg' else
                         'website_metadata_candidate_requires_visual_verification')
    } for item in value.get('logoCandidates', []) if isinstance(item, dict)]
    return result

def generation_art_direction_brief(material, brand):
    """Keep local export geometry and review administration out of model input."""
    brief = art_direction_brief(material, brand)
    brief.pop('review')
    brief['brandTreatment'].pop('exactLogoRegionPercent')
    brief['brandTreatment'].pop('logoSpace')
    return brief


def artwork_instruction_issue(direction):
    """Hold known leaked planning instructions; never silently rewrite a scene.

    This bounded check catches the observed label/coordinate defect, not arbitrary
    extra words or artistic quality. Provenance remains in saved asset metadata.
    """
    label_requests = re.finditer(
        r'\b(?:label(?:led|ed)?|mark|add)\b[^.]{0,100}\billustrative\s+(?:concept|scene)\b',
        direction, re.I)
    if any(not re.search(r'\b(?:not|never)\s*$', direction[:match.start()], re.I)
           for match in label_requests):
        return ('Remove internal illustrative concept/scene labels from the visual direction. '
                'Generated origin remains recorded separately; keep only intended advert wording.')
    if re.search(r'\b(?:left|top|width|height)\s+\d+(?:\.\d+)?\s*%|\d+%\s*/\s*\d+%', direction, re.I):
        return ('Replace numeric layout coordinates in the visual direction with plain spacing guidance. '
                'Exact logo placement stays in the local export.')
    return None


def brand_creative_profile(material, brand):
    """Compile a business-specific creative contract from reviewed context.

    This is not a style guess from an industry label. It keeps the confirmed
    offer, positioning, audience and brand settings together so a provider
    cannot satisfy the request with an interchangeable stock advert.
    """
    reviewed = {item['id']: item for item in material['evidence']
                if item.get('status') in ('owner_input', 'owner_correction', 'owner_reviewed_observation')}
    brand = brand or {}
    style = {
        'modern': 'contemporary, precise and editorial',
        'classic': 'established, editorial and restrained',
        'bold': 'confident, high-contrast and direct',
        'minimal': 'quiet, disciplined and spacious',
    }.get(brand.get('font_style'), 'deliberate, legible and specific to the proposition')
    return {
        'identity': {
            'businessName': brand.get('name') or material['business'],
            'palette': [colour for colour in
                        (brand.get('primary_color'), brand.get('secondary_color')) if colour],
            'typographicCharacter': style,
        },
        'websiteVisualIdentity': generation_brand_identity(material.get('brandIdentity')),
        'commercialCore': {
            'offer': reviewed.get('brief-offer'),
            'positioning': reviewed.get('brief-positioning'),
            'audience': material['audience'],
            'goal': material['goal'],
        },
        'typographyAndComposition': {
            'brandFirst': 'Saved style categories are not verified font families. Follow supplied website or authorised brand references; never claim a font, logo or palette was extracted when it was not.',
            'typeDirection': 'Specify headline character, weight contrast, intentional phrase-based line breaks and alignment. Keep brand typography when known; do not choose a different family merely for novelty.',
            'hierarchy': 'Create one dominant headline or visual focal point, a clearly subordinate supporting line and a legible CTA. Use scale and negative space instead of making every line the same weight.',
            'integration': 'Describe the actual spatial relationship between headline and subject: shared baseline, a deliberate open area or a controlled crop. Do not cover words or rely on an isolated image with a pasted text block.',
            'colourRoles': 'Preserve brand colour roles from supplied references: background, readable text and restrained accent are different roles. Do not automatically paint all lettering in the accent colour.',
            'variation': 'Vary composition and type hierarchy across concepts while retaining the same brand identity; never use palette or font changes as the main source of variety.',
        },
        'creativeRules': [
            'Build one visual idea around the buyer tension or transformation, not an inventory of industry props.',
            'Require a specific hero subject, material transformation or object relationship that communicates before copy is read.',
            'Typography supports the campaign idea and cannot be the complete campaign idea unless the owner explicitly requests a type-led direction.',
            'Integrate headline and subject into one composition; avoid the default stock photo above a separate text panel.',
            'Industry relevance alone is insufficient: packaging boxes do not explain a business valuation, and a desk does not explain expertise.',
            'Use an editorial visual metaphor or genuine product demonstration that clarifies the offer.',
            'If replacing the business name would make the advert reusable for an unrelated company, redesign it.',
        ],
        'antiGeneric': [
            'No default laptop, phone, notebook, calculator, coffee cup, dashboard or office scene unless the reviewed offer or selected concept genuinely requires it.',
            'No generic gradient, floating cards, decorative spheres, fake analytics or invented interface.',
            'No decorative luxury props, stock people or vague productivity imagery used as a substitute for the real proposition.',
        ],
    }


def art_direction_brief(material, brand):
    """Reuse source authority; never promote a linked/unconfirmed website claim.

    The caller obtains material through the saved confirmed-context contract.
    Keep citations with the proposition so the planner can support its wording;
    a missing proposition remains missing instead of becoming generic sales copy.
    """
    reviewed = {item['id']: item for item in material['evidence']
                if item.get('status') in ('owner_input', 'owner_correction', 'owner_reviewed_observation')}
    return deepcopy({
        'business': material['business'],
        'goal': material['goal'],
        'audience': material['audience'],
        'proposition': reviewed.get('brief-offer'),
        'positioning': reviewed.get('brief-positioning'),
        'constraints': material['constraints'],
        'brand': brand,
        'creativeProfile': brand_creative_profile(material, brand),
        'artworkMode': 'complete_advert',
        'diversityDimensions': ['buyer_motivation', 'visual_subject', 'composition', 'type_hierarchy'],
        'hierarchy': ['concise_benefit_headline', 'clear_supporting_proposition', 'relevant_imagery', 'call_to_action'],
        'imagery': {
            'direction': 'Choose realistic materials, light and subject details relevant to the reviewed offer and audience.',
            'people': 'Generated concept people only; never claim actual staff, customers or testimonials. Photorealistic style is allowed when requested.',
            'interfaces': 'Concept depictions only; never screenshot evidence or proof of an unconfirmed capability.',
            'exactProducts': 'Require authorised genuine references; never invent product fidelity.',
        },
        'brandTreatment': {
            'palette': 'Use saved exact colours; do not infer a palette when brand is absent.',
            'logo': 'Preserve the exact authorised asset through existing logo composition; never fabricate or redraw it.',
            'exactLogoRegionPercent': EXACT_LOGO_REGION_PERCENT,
            'logoSpace': 'Keep this top-right region quiet for a later exact local logo overlay. No lettering, CTA or important subject detail in it; no placeholder box or generated logo.',
        },
        'review': 'Independent pixel, wording, brand, factual and commercial review remains pending.',
    })
