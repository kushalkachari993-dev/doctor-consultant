import json
import os
import re
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import jwt  # type: ignore
from fastapi import Depends, FastAPI, HTTPException  # type: ignore
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # type: ignore
from jwt import PyJWKClient  # type: ignore
from pydantic import BaseModel, Field  # type: ignore

app = FastAPI()
bearer_scheme = HTTPBearer()


class SendEmailRequest(BaseModel):
    doctor_email: str = Field(min_length=3, max_length=254)
    patient_name: str = Field(min_length=1, max_length=120)
    patient_email: str = Field(min_length=3, max_length=254)
    email_body: str = Field(min_length=1, max_length=12000)
    generated_content: str = Field(min_length=1, max_length=20000)


def assert_email(value: str):
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
        raise HTTPException(status_code=422, detail="A valid email is required")


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


def audit_log_path() -> Path:
    configured_path = Path(os.getenv("AUDIT_LOG_PATH", "audit/email_sends.jsonl"))

    if os.getenv("VERCEL") and not configured_path.is_absolute():
        return Path("/tmp") / configured_path

    return configured_path


@app.post("/api/send-email")
@app.post("/api/send_email")
def send_patient_email(
    payload: SendEmailRequest,
    claims: dict[str, Any] = Depends(verify_clerk_token),
):
    assert_email(payload.doctor_email)
    assert_email(payload.patient_email)

    resend_api_key = os.getenv("RESEND_API_KEY")
    if not resend_api_key:
        raise HTTPException(status_code=500, detail="RESEND_API_KEY must be configured")

    doctor_user_id = claims["sub"]
    audit_id = str(uuid.uuid4())
    content_version = sha256(payload.generated_content.encode("utf-8")).hexdigest()[:12]
    timestamp = datetime.now(timezone.utc).isoformat()
    audit_path = audit_log_path()

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

    audit_write_error = None
    try:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as audit_file:
            audit_file.write(json.dumps(audit_record) + "\n")
    except OSError as err:
        audit_write_error = str(err)

    return JSONResponse(
        {
            "audit_id": audit_id,
            "content_version": content_version,
            "provider_message_id": provider_response.get("id"),
            "audit_write_error": audit_write_error,
        }
    )
