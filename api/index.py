import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import jwt  # type: ignore
from fastapi import Depends, FastAPI, HTTPException  # type: ignore
from fastapi.responses import StreamingResponse  # type: ignore
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # type: ignore
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
    clerk_secret_key = os.getenv("CLERK_SECRET_KEY")
    if not clerk_secret_key:
        raise HTTPException(status_code=500, detail="CLERK_SECRET_KEY is not configured")

    try:
        claims = jwt.decode(
            credentials.credentials,
            options={"verify_signature": False, "verify_exp": False},
        )
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Authentication token could not be read. Please sign out and sign in again.",
        )

    session_id = claims.get("sid")
    user_id = claims.get("sub")
    if not session_id or not user_id:
        raise HTTPException(status_code=401, detail="Invalid Clerk session token")

    request = Request(
        f"https://api.clerk.com/v1/sessions/{session_id}",
        headers={"Authorization": f"Bearer {clerk_secret_key}"},
        method="GET",
    )

    try:
        with urlopen(request, timeout=15) as response:
            session = json.loads(response.read().decode("utf-8"))
    except HTTPError:
        raise HTTPException(
            status_code=401,
            detail="Clerk session is not active. Please sign in again.",
        )
    except URLError:
        raise HTTPException(status_code=502, detail="Could not verify Clerk session")

    if session.get("status") != "active" or session.get("user_id") != user_id:
        raise HTTPException(status_code=401, detail="Clerk session is not active")

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
