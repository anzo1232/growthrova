# Growthrova repository instructions

## Scope

This repository is Growthrova only. Do not add, edit, import or deploy Clippr product code. Legacy `CLIPPR_BUSINESS_*` environment names may remain temporarily for runtime compatibility, but new code and configuration must use `GROWTHROVA_*`.

## Product

Growthrova is an automated marketing platform sold to businesses. A user supplies a website. The system must understand the actual business, offer, customer, brand and evidence before it creates marketing.

## Structure

- `frontend/` contains the Next.js public site and customer workspace.
- `backend/` contains the Flask API, website and brand research, creative planning, generation providers, campaign operations, delivery integrations and tests.
- Runtime credentials, databases, customer uploads and generated media are never committed.

## Creative generation rules

1. Inspect the supplied website and approved connected sources before generating.
2. Extract the real logo, colours, typography, imagery, offer, audience, proof and call to action. Record confidence and source URLs.
3. Make the business model obvious in the creative. Do not substitute vague slogans for the offer.
4. Use a visual-first composition with one idea per asset and minimal supporting copy.
5. Do not use AI people or synthetic characters.
6. Prefer authentic website and product assets when their use is approved. Generated imagery supports the concept, it does not replace brand understanding.
7. Reject generic layouts, unexplained symbols, text-heavy posters and outputs that could belong to any company.
8. Produce distinct concepts, not minor prompt variations.
9. Keep provider-specific generation behind adapters so the same creative brief can be tested across providers.
10. Save the research, creative rationale, prompt, provider, model and quality review with every result.

## Engineering rules

- Preserve tenant isolation and explicit authorisation checks.
- Do not read Clippr directories, services, databases, environment files or credentials.
- Add focused tests for changed behaviour.
- Run frontend typecheck, tests and build when frontend code changes.
- Run the relevant Growthrova backend tests when backend code changes.
- Never switch the production services from the legacy live paths without an explicit migration and rollback plan.
