from TerraFin.configuration import get_environment


def check_api_key(api_key: str) -> str:
    environment = get_environment()
    if api_key not in environment:
        raise ValueError(
            f"API key {api_key} not found in environment variables. Pass {api_key} to the data factory constructor."
        )
    return environment[api_key]
