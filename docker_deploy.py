import json
from collections import Counter
from typing import Any, List, Optional

import box
import prefect
from prefect.cli.build_register import (
    click, TerminalError, FlowLike,
    get_project_id, expand_paths, collect_flows, build_and_register
)
from prefect.executors import DaskExecutor, LocalExecutor
from prefect.run_configs import KubernetesRun
from prefect.storage import Docker


def get_default_executor(dask_address):
    if dask_address:
        return DaskExecutor(address=dask_address)
    else:
        return LocalExecutor()


def get_default_run_config(labels: List[str] = [], job_template_path: Optional[str] = None):
    return KubernetesRun(
        job_template_path=job_template_path,
        labels=labels,
    )


def get_default_storage(path: str, **storage_kwargs):
    return Docker(stored_as_script=True, path=path, **storage_kwargs)


# modified version of prefect.cli.build_register.register_internal
# the schedule param has been introduced since Prefect v15.2.0
@click.command()
@click.option("--project", help="The name of the Prefect project to register this flow in. Required.")
@click.option("--dask-address", help="The Kubernetes-bound dask executor address")
@click.option("--docker-storage-kwargs", help="Docker storage kwargs")
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
    docker_storage_kwargs: str,
    json_paths: List[str] = [],
    dask_address: str = None,
    names: List[str] = [],
    labels: List[str] = [],
    force: bool = False,
    schedule: bool = True,
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
    # Validate docker_storage_kwargs
    docker_storage_kwargs_json = json.loads(docker_storage_kwargs)
    if 'base_image' not in docker_storage_kwargs_json:
        raise TerminalError(
            "docker_storage_kwargs must contain a base_image key"
        )
    if 'registry_url' not in docker_storage_kwargs_json or 'image_name' not in docker_storage_kwargs_json:
        raise TerminalError(
            "docker_storage_kwargs must contain both registry_url and image_name key"
        )

    client = prefect.Client()

    # Determine the project id
    project_id = get_project_id(client, project)

    # Recursively check for flows
    expanded_paths = expand_paths(paths)
    click.secho(f"Found flows: {expanded_paths!r}", fg="green")

    # Load flows from all files/modules requested
    click.echo("Collecting flows...")
    source_to_flows = collect_flows(expanded_paths, modules, json_paths, names=names)

    serialized_flows = {}

    # Iterate through each file, building all storage and registering all flows
    # Log errors as they happen, but only exit once all files have been processed
    stats = Counter(registered=0, errored=0, skipped=0)
    for source, flows in source_to_flows.items():
        click.secho(f"Processing {source.location!r}:", fg="yellow")

        # Major extension to register_internal goes here
        for flow in flows:
            click.echo(f"  Replacing configs for {flow.name!r}...")
            
            flow.run_config = get_default_run_config()
            flow.storage = get_default_storage(path=source.location, **docker_storage_kwargs_json)
            flow.executor = get_default_executor(dask_address)
            
            # Serialize for the output flows.json
            if isinstance(flow, box.Box):
                serialized_flow = flow
            else:
                serialized_flow = flow.serialize(build=False)
            serialized_flows[flow.name] = serialized_flow

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

    # Write output file
    output = "tmp/flows.json"
    click.echo(f"Writing output to {output!r}")
    flows = [serialized_flows[name] for name in sorted(serialized_flows)]
    obj = {"version": 1, "flows": flows}
    with open(output, "w") as fil:
        json.dump(obj, fil, sort_keys=True)

    # If not in a watch call, exit with appropriate exit code
    if stats["errored"]:
        raise TerminalError


if __name__ == '__main__':
    register()
