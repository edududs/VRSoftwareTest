from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

NotificationType = Literal["EMAIL", "SMS", "PUSH"]


class NotificationIn(BaseModel):
    message_id: Optional[str] = Field(default=None)
    message_content: str
    notification_type: NotificationType


class NotificationAccepted(BaseModel):
    message_id: str
    trace_id: str


class NotificationStatus(BaseModel):
    trace_id: str
    message_id: str
    message_content: str
    notification_type: NotificationType
    status: str
