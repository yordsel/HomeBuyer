"""Shared HTTP session with retry logic and rate limiting."""

import logging
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tqdm import tqdm
from urllib3.util.retry import Retry

from homebuyer.config import MAX_RETRIES, REQUEST_DELAY_SECONDS, REQUEST_TIMEOUT_SECONDS, USER_AGENT

logger = logging.getLogger(__name__)

# Track the timestamp of the last request for rate limiting
_last_request_time: float = 0.0


def create_session() -> requests.Session:
    """Create an HTTP session with browser-like headers and automatic retry."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Referer": "https://www.redfin.com/",
        }
    )

    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def rate_limited_get(
    session: requests.Session,
    url: str,
    params: dict | None = None,
    delay: float = REQUEST_DELAY_SECONDS,
) -> requests.Response:
    """Perform a GET request with enforced delay between calls.

    Args:
        session: The requests session to use.
        url: The URL to request.
        params: Optional query parameters.
        delay: Minimum seconds between requests (politeness).

    Returns:
        The HTTP response.

    Raises:
        requests.HTTPError: If the response status code indicates an error.
    """
    global _last_request_time

    # Enforce rate limiting
    elapsed = time.time() - _last_request_time
    if elapsed < delay:
        sleep_time = delay - elapsed
        logger.debug("Rate limiting: sleeping %.1fs", sleep_time)
        time.sleep(sleep_time)

    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    _last_request_time = time.time()

    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", 60))
        logger.warning("Rate limited (429). Retrying after %ds.", retry_after)
        time.sleep(retry_after)
        raise requests.HTTPError(f"Rate limited. Retry after {retry_after}s")

    response.raise_for_status()
    return response


def stream_download(
    session: requests.Session,
    url: str,
    dest_path: Path,
    chunk_size: int = 8192,
    description: str = "Downloading",
) -> Path:
    """Stream a large file download with a progress bar.

    Args:
        session: The requests session to use.
        url: The URL to download from.
        dest_path: Where to save the file.
        chunk_size: Size of each download chunk in bytes.
        description: Label for the progress bar.

    Returns:
        The path to the downloaded file.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    response = session.get(url, stream=True, timeout=300)
    response.raise_for_status()

    total_size = int(response.headers.get("content-length", 0))

    with (
        open(dest_path, "wb") as f,
        tqdm(total=total_size, unit="B", unit_scale=True, desc=description) as pbar,
    ):
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
                pbar.update(len(chunk))

    logger.info("Downloaded %s (%s bytes)", dest_path, dest_path.stat().st_size)
    return dest_path
