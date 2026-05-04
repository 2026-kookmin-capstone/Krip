from pydantic import BaseModel, ConfigDict, Field


# ──────────────────── Request ────────────────────

class MuteToggleBody(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "muted": True,
            }
        }
    )

    muted: bool = Field(..., description="true=차단, false=해제")
