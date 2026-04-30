from pydantic import BaseModel


class WatchlistItem(BaseModel):
    symbol: str
    name: str
    move: str
    tags: list[str] = []


class WatchlistSnapshotResponse(BaseModel):
    items: list[WatchlistItem]
