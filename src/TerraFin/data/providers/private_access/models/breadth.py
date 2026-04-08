from pydantic import BaseModel


class BreadthMetric(BaseModel):
    label: str
    value: str
    tone: str


class MarketBreadthResponse(BaseModel):
    metrics: list[BreadthMetric]


class TrailingForwardPeHistoryPoint(BaseModel):
    date: str
    value: float


class TrailingForwardPeSpreadResponse(BaseModel):
    date: str = ""
    summary: dict = {}
    coverage: dict = {}
    history: list[TrailingForwardPeHistoryPoint] = []
