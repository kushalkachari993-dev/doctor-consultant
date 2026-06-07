# MediNotes Pro

MediNotes Pro is a demo SaaS application for healthcare consultation note workflows. It lets a signed-in user enter visit notes, then streams an AI-generated doctor summary, follow-up actions, and a patient-friendly email draft.

This is a demo project, not a production medical records system. Do not enter real patient data unless the full deployment, vendor agreements, retention policy, and compliance controls have been reviewed.

## Features

- Next.js pages-router frontend with Tailwind CSS styling
- Clerk authentication and premium subscription gating
- Consultation form with patient name, visit date, and notes
- Python FastAPI endpoint designed for Vercel serverless deployment
- Clerk JWT verification on the API route
- Streaming OpenAI response rendered as Markdown
- Review-and-confirm email sending through Resend
- Local JSONL audit records for sent emails

## Tech Stack

- Next.js 16
- React 19
- TypeScript
- Tailwind CSS 4
- Clerk
- FastAPI
- OpenAI Python SDK

## Project Structure

```text
api/index.py        Python API endpoint mounted at /api
api/send_email.py   Python API endpoint mounted at /api/send_email
pages/index.tsx     Public landing page and sign-in entry point
pages/product.tsx   Protected consultation assistant UI
pages/_app.tsx      Clerk provider and global styles
styles/globals.css  Tailwind import and Markdown output styling
requirements.txt    Python dependencies for the API function
```

## Environment Variables

Create a local `.env.local` file using `.env.example` as a guide.

Required values:

```text
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=
CLERK_SECRET_KEY=
CLERK_JWKS_URL=
OPENAI_API_KEY=
RESEND_API_KEY=
AUDIT_LOG_PATH=audit/email_sends.jsonl
```

Clerk must also have a plan named `premium_subscription`, because `pages/product.tsx` uses that plan id for access control.

The email sender is taken from the signed-in doctor's primary Clerk email address. For Resend, that sender address must belong to a verified sender/domain in your Resend account, otherwise Resend will reject the send.

## Local Development

Install JavaScript dependencies:

```bash
npm install
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Start the full local app with Vercel's dev server:

```bash
npx vercel dev
```

Open `http://localhost:3000`.

Use `npm run dev` only when you want to run the frontend by itself. The AI and email endpoints are Python Vercel functions, so `/api` and `/api/send_email` require `vercel dev` locally.

## Demo Flow

1. Visit the landing page.
2. Sign in with Clerk.
3. Open the product page.
4. Subscribe or use a Clerk test user with access to `premium_subscription`.
5. Enter consultation notes.
6. Submit the form and watch the AI response stream into the page.
7. Review the generated patient email draft.
8. Click `Send Email` and confirm the send.

Sent email metadata is appended to `audit/email_sends.jsonl` locally. On Vercel, relative audit paths are written under `/tmp`, which is suitable for demo diagnostics but not durable storage. The audit record stores the doctor user id, doctor email, patient name/email, timestamp, provider message id, and a hash-based generated content version. It does not store the full generated email body.

## Deployment Notes

The `api/index.py` file is structured for Vercel's Python serverless runtime. Configure the same environment variables in Vercel before deploying.

For a public demo, rotate any local secrets that may have been exposed during development and keep `.env.local` uncommitted.
