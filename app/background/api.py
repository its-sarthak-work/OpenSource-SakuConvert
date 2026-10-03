from pathlib import Path
import requests

from app.background.providers import get_provider


class BackgroundAPIError(RuntimeError):
    def __init__(self, message: str, *, daily_limit_reached: bool = False):
        super().__init__(message)
        self.daily_limit_reached = daily_limit_reached


def remove_background_online(
    source: Path,
    destination: Path,
    *,
    provider_id: str = "bgninja",
    timeout: int = 120,
) -> Path:
    provider = get_provider(provider_id)

    if provider.requires_api_key:
        raise BackgroundAPIError(
            "This provider requires an API key and is not configured."
        )

    if not source.exists():
        raise BackgroundAPIError("The selected image does not exist.")

    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        with source.open("rb") as image_file:
            response = requests.post(
                provider.endpoint,
                files={"file": (source.name, image_file, "application/octet-stream")},
                data={"src": "SakuConvert"},
                timeout=timeout,
            )
    except requests.RequestException as exc:
        raise BackgroundAPIError(f"Network request failed: {exc}") from exc

    if response.status_code == 402:
        raise BackgroundAPIError(
            "The provider's 10 free background-removal requests for today "
            "have been used. The provider resets its allowance at midnight.",
            daily_limit_reached=True,
        )

    if response.status_code == 429:
        raise BackgroundAPIError(
            "The provider currently has two background-removal requests running "
            "from this IP address. Please wait a moment and try again."
        )

    if response.status_code != 200:
        detail = response.text[:500] if response.text else "No error details."
        raise BackgroundAPIError(
            f"{provider.name} returned HTTP {response.status_code}: {detail}"
        )

    content_type = response.headers.get("content-type", "").lower()
    if "image" not in content_type and not response.content.startswith(b"\x89PNG"):
        raise BackgroundAPIError("Provider returned an unexpected response.")

    destination.write_bytes(response.content)

    if destination.stat().st_size == 0:
        raise BackgroundAPIError("Provider returned an empty image.")

    return destination
