from dataclasses import dataclass

@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    endpoint: str
    requires_api_key: bool
    note: str

PROVIDERS = {
    "bgninja": Provider(
        id="bgninja",
        name="BGNinja",
        endpoint="https://bgninja.com/api/remove",
        requires_api_key=False,
        note="Free, no API key; provider documents a 10-image/day limit.",
    ),
}

def get_provider(provider_id: str) -> Provider:
    try:
        return PROVIDERS[provider_id]
    except KeyError as exc:
        raise ValueError(f"Unknown background-removal provider: {provider_id}") from exc
