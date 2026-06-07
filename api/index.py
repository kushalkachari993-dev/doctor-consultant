import json
import os

from fastapi import Depends, FastAPI, HTTPException  # type: ignore
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
