"""Partner connection schemas."""

from pydantic import BaseModel, EmailStr, field_validator


class SendInviteRequest(BaseModel):
    partner_email: EmailStr

    @field_validator("partner_email")
    @classmethod
    def normalize(cls, v: str) -> str:
        return v.strip().lower()


class RespondInviteRequest(BaseModel):
    connection_id: str
    accept: bool
