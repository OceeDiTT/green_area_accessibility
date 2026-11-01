import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "greenspace-pipeline/0.1 (+urban green space accessibility research)"


def make_session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=4, backoff_factor=1.5,
                                                     status_forcelist=(429, 500, 502, 503, 504))))
    s.headers["User-Agent"] = USER_AGENT
    return s


def download_bytes(url: str, session: requests.Session | None = None, timeout: int = 180) -> bytes:
    r = (session or make_session()).get(url, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r.content
