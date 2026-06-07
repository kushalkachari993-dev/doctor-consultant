import json
import os
import re
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import Depends, FastAPI, HTTPException  # type: ignore
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse  # type: ignore
from fastapi_clerk_auth import (  # type: ignore
    ClerkConfig,
    ClerkHTTPBearer,
    HTTPAuthorizationCredentials,
)
from openai import OpenAI  # type: ignore
from pydantic import BaseModel, Field  # type: ignore

app = FastAPI()
clerk_config = ClerkConfig(jwks_url=os.getenv("CLERK_JWKS_URL"))
clerk_guard = ClerkHTTPBearer(clerk_config)


class Visit(BaseModel):
    patient_name: str = Field(min_length=1, max_length=120)
    patient_email: str = Field(min_length=3, max_length=254)
    date_of_visit: str = Field(min_length=10, max_length=10)
    notes: str = Field(min_length=1, max_length=12000)


class SendEmailRequest(BaseModel):
    doctor_email: str = Field(min_length=3, max_length=254)
    patient_name: str = Field(min_length=1, max_length=120)
    patient_email: str = Field(min_length=3, max_length=254)
    email_body: str = Field(min_length=1, max_length=12000)
    generated_content: str = Field(min_length=1, max_length=20000)


system_prompt = """
You are provided with notes written by a doctor from a patient's visit.
Your job is to summarize the visit for the doctor and provide an email.
Reply with exactly three sections with the headings:
### Summary of visit for the doctor's records
### Next steps for the doctor
### Draft of email to patient in patient-friendly language
"""


def assert_email(value: str):
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
        raise HTTPException(status_code=422, detail="A valid patient email is required")


def user_prompt_for(visit: Visit) -> str:
    return f"""Create the summary, next steps and draft email for:
Patient Name: {visit.patient_name}
Date of Visit: {visit.date_of_visit}
Notes:
{visit.notes}"""


@app.post("/api")
def consultation_summary(
    visit: Visit,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured")

    user_id = creds.decoded.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid Clerk token")

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


@app.post("/api/send-email")
def send_patient_email(
    payload: SendEmailRequest,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
):
    assert_email(payload.doctor_email)
    assert_email(payload.patient_email)

    resend_api_key = os.getenv("RESEND_API_KEY")
    if not resend_api_key:
        raise HTTPException(
            status_code=500,
            detail="RESEND_API_KEY must be configured",
        )

    doctor_user_id = creds.decoded.get("sub")
    if not doctor_user_id:
        raise HTTPException(status_code=401, detail="Invalid Clerk token")

    audit_id = str(uuid.uuid4())
    content_version = sha256(payload.generated_content.encode("utf-8")).hexdigest()[:12]
    timestamp = datetime.now(timezone.utc).isoformat()
    audit_path = Path(os.getenv("AUDIT_LOG_PATH", "audit/email_sends.jsonl"))
    audit_path.parent.mkdir(exist_ok=True)

    resend_payload = {
        "from": payload.doctor_email,
        "to": [payload.patient_email],
        "subject": "Follow-up from your consultation",
        "text": payload.email_body,
    }

    request = Request(
        "https://api.resend.com/emails",
        data=json.dumps(resend_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {resend_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=20) as response:
            provider_response = json.loads(response.read().decode("utf-8"))
    except HTTPError as err:
        message = err.read().decode("utf-8") or "Resend rejected the email request"
        raise HTTPException(status_code=502, detail=message)
    except URLError:
        raise HTTPException(status_code=502, detail="Could not reach Resend")

    audit_record = {
        "audit_id": audit_id,
        "doctor_user_id": doctor_user_id,
        "doctor_email": payload.doctor_email,
        "patient_name": payload.patient_name,
        "patient_email": payload.patient_email,
        "timestamp": timestamp,
        "content_version": content_version,
        "provider": "resend",
        "provider_message_id": provider_response.get("id"),
    }

    with audit_path.open("a", encoding="utf-8") as audit_file:
        audit_file.write(json.dumps(audit_record) + "\n")

    return JSONResponse(
        {
            "audit_id": audit_id,
            "content_version": content_version,
            "provider_message_id": provider_response.get("id"),
        }
    )
