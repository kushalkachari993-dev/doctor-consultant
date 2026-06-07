import json
import os
from typing import Any
from urllib.request import urlopen

import jwt  # type: ignore
from fastapi import Depends, FastAPI, HTTPException  # type: ignore
from fastapi.responses import StreamingResponse  # type: ignore
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # type: ignore
from jwt import PyJWKClient  # type: ignore
from openai import OpenAI  # type: ignore
from pydantic import BaseModel, Field  # type: ignore

app = FastAPI()
bearer_scheme = HTTPBearer()


class Visit(BaseModel):
    patient_name: str = Field(min_length=1, max_length=120)
    patient_email: str = Field(min_length=3, max_length=254)
    date_of_visit: str = Field(min_length=10, max_length=10)
    notes: str = Field(min_length=1, max_length=12000)


system_prompt = """
You are provided with notes written by a doctor from a patient's visit.
Your job is to summarize the visit for the doctor and provide an email.
Reply with exactly three sections with the headings:
### Summary of visit for the doctor's records
### Next steps for the doctor
### Draft of email to patient in patient-friendly language
"""


def verify_clerk_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict[str, Any]:
    jwks_url = os.getenv("CLERK_JWKS_URL")
    if not jwks_url:
        raise HTTPException(status_code=500, detail="CLERK_JWKS_URL is not configured")

    try:
        jwk_client = PyJWKClient(jwks_url)
        signing_key = jwk_client.get_signing_key_from_jwt(credentials.credentials)
        claims = jwt.decode(
            credentials.credentials,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Authentication failed. Please sign out and sign in again.",
        )

    if not claims.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid Clerk token")

    return claims


def user_prompt_for(visit: Visit) -> str:
    return f"""Create the summary, next steps and draft email for:
Patient Name: {visit.patient_name}
Date of Visit: {visit.date_of_visit}
Notes:
{visit.notes}"""


@app.post("/api")
def consultation_summary(
    visit: Visit,
    claims: dict[str, Any] = Depends(verify_clerk_token),
):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured")

    client = OpenAI()
    prompt = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt_for(visit)},
    ]

    def event_stream():
        try:
            stream = client.chat.completions.create(
                model="gpt-5-nano",
                messages=prompt,
                stream=True,
            )
            for chunk in stream:
                text = chunk.choices[0].delta.content
                if text:
                    yield f"data: {json.dumps({'content': text})}\n\n"
        except Exception:
            error = "The AI service could not generate a summary. Please try again."
            yield f"data: {json.dumps({'error': error})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
