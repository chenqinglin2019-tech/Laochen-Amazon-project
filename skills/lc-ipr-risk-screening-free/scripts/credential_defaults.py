"""Public empty credential defaults; never read installed credentials."""
import json

BACKEND_URL = "https://mcp.yixunkuajing.com"
API_FIELDS = ['EPO_OPS_CONSUMER_KEY', 'EPO_OPS_CONSUMER_SECRET', 'EUIPO_CLIENT_ID', 'EUIPO_CLIENT_SECRET', 'JPO_API_USERNAME', 'JPO_API_PASSWORD', 'INPI_USERNAME', 'INPI_PASSWORD', 'SERPER_API_KEY', 'SIGNA_API_KEY', 'SERPAPI_API_KEY', 'RAPIDAPI_KEY']


def empty_credentials(name):
    if name == "config.json":
        return (json.dumps({"backend_url": BACKEND_URL, "backend_token": ""}, indent=2) + "\n").encode()
    if name == ".env":
        return ("# Fill only your own approved credentials. Never publish populated values.\n" +
                "".join(key + "=\n" for key in API_FIELDS)).encode()
    raise ValueError("UNKNOWN_CREDENTIAL_FILE")
