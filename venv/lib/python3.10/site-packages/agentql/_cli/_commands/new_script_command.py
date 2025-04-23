import typer

from ._utils import download_script

SYNC_TEMPLATE_URL = (
    "https://raw.githubusercontent.com/tinyfish-io/agentql/main/.templates/python/template_sync.py"
)
ASYNC_TEMPLATE_URL = (
    "https://raw.githubusercontent.com/tinyfish-io/agentql/main/.templates/python/template_async.py"
)
TEMPLATE_FILE_NAME = "template_script.py"
INVALID_OPTION_MESSAGE = "Please choose between 'sync' and 'async'"


def _validate_script_type(response: str):
    """Validate the response for the script type."""
    sync_or_async = response.lower().strip()
    if sync_or_async not in ["sync", "async"]:
        raise typer.BadParameter(INVALID_OPTION_MESSAGE)
    return sync_or_async


def new_script(
    script_type: str = typer.Option(
        None,
        "-t",
        "--type",
        prompt="Choose the type of template script (sync or async)",
        help="Specify the type of template script between sync and async",
        callback=_validate_script_type,
    )
):
    """Download a new template script into the current directory."""
    typer.echo("Downloading the template script...")
    script_url = SYNC_TEMPLATE_URL if script_type == "sync" else ASYNC_TEMPLATE_URL
    download_script(script_url, TEMPLATE_FILE_NAME)
