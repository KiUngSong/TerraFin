from pydantic import BaseModel


class TopCompanyRow(BaseModel):
    rank: int
    ticker: str
    name: str
    marketCap: str
    country: str
    marketCapValue: float | None = None


class TopCompaniesResponse(BaseModel):
    companies: list[TopCompanyRow]
    count: int | None = None
