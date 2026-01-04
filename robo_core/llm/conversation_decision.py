from pydantic import BaseModel, Field
from typing import Literal

class ConversationDecision(BaseModel):
    """
    Structured output for conversation decision making.
    """
    action: Literal["start conversation", "end conversation", "no conversation"] = Field(
        description="The action to take based on the conversation analysis"
    )
    reason: str = Field(
        description="The reasoning for choosing this action"
    )

