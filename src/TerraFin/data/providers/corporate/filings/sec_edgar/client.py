from weakref import finalize

import requests
from pyrate_limiter import Duration, Limiter, Rate
from requests.adapters import HTTPAdapter
from requests.sessions import Session
from urllib3.util.retry import Retry


# Constants for the SEC API
MAX_REQUESTS_PER_SECOND = 10
MAX_RETRIES = 3
BACKOFF_FACTOR = 1 / MAX_REQUESTS_PER_SECOND
SEC_THROTTLE_LIMIT_RATE = Rate(MAX_REQUESTS_PER_SECOND, Duration.SECOND)

limiter = Limiter(SEC_THROTTLE_LIMIT_RATE).as_decorator(name="sec_edgar_api_rate_limit", weight=1)


retries = Retry(
    total=MAX_RETRIES,
    backoff_factor=BACKOFF_FACTOR,
    status_forcelist=[408, 425, 429, 500, 502, 503, 504],
)


class SECClient:
    """
    HTTP client for SEC EDGAR API with rate limiting and retry logic.

    SEC limits users to a maximum of 10 requests per second.
    Source: https://www.sec.gov/developer
    """

    def __init__(self, user_agent: str, host_url: str = "data.sec.gov"):
        assert host_url in ["www.sec.gov", "data.sec.gov"]
        self._session: Session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Host": host_url,
            }
        )
        self._session.mount("http://", HTTPAdapter(max_retries=retries))
        self._session.mount("https://", HTTPAdapter(max_retries=retries))

        # Close the session when this object is garbage collected
        # or the program exits.
        # Source: https://stackoverflow.com/a/67312839/3820660
        _ = finalize(self, self._session.close)

    @limiter
    def get(self, url: str, proxies=None):
        """Make a rate-limited GET request.

        SEC limits users to a maximum of 10 requests per second.
        Source: https://www.sec.gov/developer
        """
        resp = self._session.get(url, proxies=proxies)
        return resp
