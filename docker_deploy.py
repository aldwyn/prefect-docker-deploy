from collections import Counter
from typing import List, Optional

import prefect
from prefect.cli.build_register import (
    click, TerminalError, FlowLike,
    get_project_id, expand_paths, collect_flows, build_and_register
)
from prefect.cli.create import project as project_create
from prefect.executors import DaskExecutor, LocalExecutor
from prefect.run_configs import KubernetesRun
from prefect.storage import Docker


def get_default_executor(dask=False):
    if dask:
        return DaskExecutor(address="tcp://dask-scheduler:8786")
    else:
        return LocalExecutor()


def get_default_run_config(labels: List[str] = [], job_template_path: Optional[str] = None):
    return KubernetesRun(
        job_template_path=job_template_path,
        labels=labels,
    )


def get_default_storage(script_path, image_name, base_image, registry_url):
    return Docker(registry_url=registry_url,
                  image_name=image_name,
                  base_image=base_image,
                  local_image=True,
                  stored_as_script=True,
                  path=script_path)


def build_dockerized_flows(flows: List[FlowLike], dask, script_path, docker_registry_url):
    for flow in flows:
        flow.validate()
        flow.run_config = get_default_run_config(dask)
        flow.storage = get_default_storage(script_path, docker_registry_url)
        flow.executor = get_default_executor()


# modified version of prefect.cli.build_register.register_internal
# the schedule param has been introduced since Prefect v15.2.0
@click.command()
@click.option("--project", help="The name of the Prefect project to register this flow in. Required.")
@click.option("--create-project", help="Whether to create project if it does not exist", default=False, is_flag=True)
@click.option("--project-description", help="A description of the project to be used when creating it.")
@click.option("--dask", help="Whether to use the Dask executor.", default=False, is_flag=True)
@click.option("--base-image", help="Docker base image")
@click.option("--docker-registry-url", help="Docker registry URL")
@click.option("--docker-registry-image", help="Docker registry output image")
@click.option(
    "--path",
    "-p",
    "paths",
    help=(
        "A path to a file or a directory containing the flow(s) to register. "
        "May be passed multiple times to specify multiple paths."
    ),
    multiple=True,
)
@click.option(
    "--module",
    "-m",
    "modules",
    help=(
        "A python module name containing the flow(s) to register. May be the full "
        "import path to a flow. May be passed multiple times to specify multiple "
        "modules. "
    ),
    multiple=True,
)
@click.option(
    "--schedule/--no-schedule",
    help=(
        "Toggles the flow schedule upon registering. By default, the "
        "flow's schedule will be activated and future runs will be created. "
        "If disabled, the schedule will still be attached to the flow but "
        "no runs will be created until it is activated."
    ),
    default=True,
)
def register(
    project: str,
    paths: List[str],
    modules: List[str],
    base_image: str,
    docker_registry_url: str,
    docker_registry_image: str,
    json_paths: List[str] = [],
    names: List[str] = [],
    labels: List[str] = [],
    project_description: str = None,
    create_project: bool = False,
    force: bool = False,
    schedule: bool = True,
    dask: bool = False,
) -> None:
    """Do multiple registration pass, loading, building, and registering the
    requested flows.

    Args:
        - project (str): the project in which to register the flows.
        - paths (List[str]): a list of file paths containing flows.
        - modules (List[str]): a list of python modules containing flows.
        - json_paths (List[str]): a list of file paths containing serialied
            flows produced by `prefect build`.
        - names (List[str], optional): a list of flow names that should be
            registered. If not provided, all flows found will be registered.
        - labels (List[str], optional): a list of extra labels to set on all
            flows.
        - force (bool, optional): If false (default), an idempotency key will
            be used to avoid unnecessary register calls.
        - schedule (bool, optional): If `True` (default) activates the flow schedule
            upon registering.
    """
    client = prefect.Client()

    # Create project if it does not exist
    if create_project:
        project_create.callback(project, project_description, True)

    # Determine the project id
    project_id = get_project_id(client, project)

    # Recursively check for flows
    expanded_paths = expand_paths(paths)
    click.secho(f"Found flows: {expanded_paths!r}", fg="green")

    # Load flows from all files/modules requested
    click.echo("Collecting flows...")
    source_to_flows = collect_flows(expanded_paths, modules, json_paths, names=names)

    # Iterate through each file, building all storage and registering all flows
    # Log errors as they happen, but only exit once all files have been processed
    stats = Counter(registered=0, errored=0, skipped=0)
    for source, flows in source_to_flows.items():
        click.secho(f"Processing {source.location!r}:", fg="yellow")

        # Major extension to register_internal goes here
        build_dockerized_flows(flows, dask, script_path=source.location,
                               base_image=base_image,
                               registry_image=docker_registry_image,
                               registry_url=docker_registry_url)

        stats += build_and_register(
            client, flows, project_id, labels=labels, force=force, schedule=schedule
        )

    # Output summary message
    registered = stats["registered"]
    skipped = stats["skipped"]
    errored = stats["errored"]
    parts = [click.style(f"{registered} registered", fg="green")]
    if skipped:
        parts.append(click.style(f"{skipped} skipped", fg="yellow"))
    if errored:
        parts.append(click.style(f"{errored} errored", fg="red"))

    msg = ", ".join(parts)
    bar_length = max(60 - len(click.unstyle(msg)), 4) // 2
    bar = "=" * bar_length
    click.echo(f"{bar} {msg} {bar}")

    # If not in a watch call, exit with appropriate exit code
    if stats["errored"]:
        raise TerminalError


if __name__ == '__main__':
    register()
