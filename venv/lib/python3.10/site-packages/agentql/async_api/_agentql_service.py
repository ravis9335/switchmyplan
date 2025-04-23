import logging
import os
from typing import Optional

import httpx

from agentql import AgentQLServerError, AgentQLServerTimeoutError, APIKeyError
from agentql._core._api_constants import (
    CHECK_SERVER_STATUS_ENDPOINT,
    DEFAULT_REQUEST_ORIGIN,
    GET_AGENTQL_DATA_ENDPOINT,
    GET_AGENTQL_ELEMENT_ENDPOINT,
    QUERY_GENERATE_ENDPOINT,
    SERVICE_URL,
    VALIDATE_API_KEY_ENDPOINT,
)
from agentql._core._errors import API_KEY_NOT_SET_MESSAGE
from agentql._core._typing import ResponseMode
from agentql._core._utils import get_api_key_async, minify_query, raise_401_error

RESPONSE_ERROR_KEY = "detail"

log = logging.getLogger("agentql")


async def generate_query_from_agentql_server(
    prompt: str,
    accessibility_tree: dict,
    timeout: int,
    page_url: str,
    request_origin: Optional[str] = None,
) -> str:
    """Make Request to AgentQL Server's query generate endpoint.

    Parameters:
    ----------
    prompt (str): The natural language description of the element to locate.
    accessibility_tree (dict): The accessibility tree.
    timeout (int): The timeout value for the connection with backend api service
    page_url (str): The URL of the active page.
    request_origin (Optional[str]): The origin of the request.

    Returns:
    -------
    str: AgentQL query in String format.
    """
    api_key = await get_api_key_async()
    if not api_key:
        raise APIKeyError(API_KEY_NOT_SET_MESSAGE)

    try:
        request_data = {
            "prompt": prompt,
            "accessibility_tree": accessibility_tree,
            "metadata": {"url": page_url},
            "request_origin": request_origin or "sdk-playwright-python",
        }
        url = os.getenv("AGENTQL_API_HOST", SERVICE_URL) + QUERY_GENERATE_ENDPOINT

        headers = {"X-API-Key": api_key}
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, json=request_data, headers=headers, timeout=timeout, follow_redirects=True
            )
            response.raise_for_status()
            return response.json()["query"]

    except httpx.TimeoutException as e:
        raise AgentQLServerTimeoutError() from e
    except httpx.HTTPStatusError as e:
        request_id = (
            e.response.headers.get("X-Request-ID", None) if e.response is not None else None
        )
        error_code = e.response.status_code
        server_error = e.response.text

        if e.response.status_code == 401:
            raise_401_error(e, request_id)
        if server_error:
            try:
                server_error_json = e.response.json()
                if isinstance(server_error_json, dict):
                    server_error = server_error_json.get(RESPONSE_ERROR_KEY)
            except ValueError:
                raise AgentQLServerError(server_error, error_code, request_id) from e
        raise AgentQLServerError(server_error, error_code, request_id) from e
    except httpx.RequestError as e:
        raise AgentQLServerError(str(e)) from e


async def query_agentql_server(
    query: str,
    accessibility_tree: dict,
    timeout: int,
    page_url: str,
    mode: ResponseMode,
    query_data: bool = False,
    experimental_query_elements_enabled: bool = False,
    **kwargs,
) -> dict:
    """Make Request to AgentQL Server's query endpoint.

    Parameters:
    ----------
    query (str): The query string.
    accessibility_tree (dict): The accessibility tree.
    timeout (int): The timeout value for the connection with backend api service
    page_url (str): The URL of the active page.
    mode (ResponseMode): The mode of the query. It can be either 'standard' or 'fast'.
    experimental_query_elements_enabled (bool) (optional): Whether to use the experimental implementation of the query elements feature. Defaults to `False`.

    Returns:
    -------
    dict: AgentQL response in json format.
    """
    api_key = await get_api_key_async()
    if not api_key:
        raise APIKeyError(API_KEY_NOT_SET_MESSAGE)

    try:
        request_data = {
            "query": f"{query}",
            "accessibility_tree": accessibility_tree,
            "metadata": {
                "url": page_url,
                "experimental_query_elements_enabled": experimental_query_elements_enabled,
            },
            "params": {"mode": mode},
            "request_origin": kwargs.get("request_origin", DEFAULT_REQUEST_ORIGIN),
        }

        if "metadata" in kwargs:
            request_data["metadata"] |= kwargs["metadata"]

        if query_data:
            url = os.getenv("AGENTQL_API_HOST", SERVICE_URL) + GET_AGENTQL_DATA_ENDPOINT
        else:
            url = os.getenv("AGENTQL_API_HOST", SERVICE_URL) + GET_AGENTQL_ELEMENT_ENDPOINT

        headers = {"X-API-Key": api_key}
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, json=request_data, headers=headers, timeout=timeout, follow_redirects=True
            )
            response.raise_for_status()

            minified_query = minify_query(query)
            log.debug(
                f"Request ID for the query request {minified_query} is {response.json()['request_id']}"
            )
            return response.json()["response"]
    except httpx.TimeoutException as e:
        raise AgentQLServerTimeoutError() from e
    except httpx.HTTPStatusError as e:
        request_id = (
            e.response.headers.get("X-Request-ID", None) if e.response is not None else None
        )

        if e.response.status_code == 401:
            raise_401_error(e, request_id)
        error_code = e.response.status_code
        server_error = e.response.text
        if server_error:
            try:
                server_error_json = e.response.json()
                if isinstance(server_error_json, dict):
                    server_error = server_error_json.get(RESPONSE_ERROR_KEY)
            except ValueError:
                raise AgentQLServerError(server_error, error_code, request_id) from e
        raise AgentQLServerError(server_error, error_code, request_id) from e
    except httpx.RequestError as e:
        raise AgentQLServerError(str(e)) from e


async def validate_api_key(api_key: str, timeout: int = 30):
    """Validate the API key through the AgentQL service.

    Parameters:
    ----------
    api_key (str): The AGENTQL API key to validate.

    Returns:
    -------
    bool: True if the API key is valid, False otherwise.
    """
    try:
        url = os.getenv("AGENTQL_API_HOST", SERVICE_URL) + VALIDATE_API_KEY_ENDPOINT
        headers = {"X-API-Key": api_key}
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers=headers, timeout=timeout, follow_redirects=True
            )
            response.raise_for_status()
            return True
    except httpx.HTTPStatusError:
        return False


async def check_agentql_server_status(timeout: int = 15) -> bool:
    """Check the status of the AgentQL server.

    Parameters:
    ----------
    timeout (int): The timeout value for the connection with backend API service.

    Returns:
    -------
    bool: True if the server is up and running, False otherwise.
    """
    try:
        url = os.getenv("AGENTQL_API_HOST", SERVICE_URL) + CHECK_SERVER_STATUS_ENDPOINT
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=timeout, follow_redirects=True)
            response.raise_for_status()
            return True
    except httpx.HTTPStatusError:
        return False
