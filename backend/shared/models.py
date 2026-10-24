from pydantic import BaseModel, ConfigDict


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")
