# Growthrova

Growthrova is an automated marketing platform for businesses. A customer supplies their website, Growthrova learns the brand, offer, audience and visual language, then plans and produces marketing content, advertising creative and campaign actions.

## Repository layout

- `frontend/`: Next.js customer workspace and public website
- `backend/`: Flask API, brand research, creative planning, content generation, delivery integrations and tests
- `docs/`: architecture and operating notes

## Local development

### Frontend

```bash
cd frontend
npm ci
npm run dev
```

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/gunicorn "business_growthrova_preview:from_environment()"
```

Runtime credentials belong in private environment files outside this repository. Never commit customer data, generated media, databases or provider keys.
