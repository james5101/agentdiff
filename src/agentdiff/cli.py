"""`agentdiff` CLI entry point.

Exposes the `run-local` command (Milestone 1): load all agents
declared in `<repo_path>/agentdiff.yaml`, run each agent's eval sets
against the live model API, print pass/fail results.

Designed so a developer can pipe `agentdiff run-local .` at any
agentdiff-shaped repo and see a useful answer in under a minute.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Annotated

import structlog
import typer
from rich.console import Console
from rich.table import Table

from agentdiff.config import Settings
from agentdiff.definition import DefinitionError
from agentdiff.definition.evals import load_eval_cases
from agentdiff.definition.loader import load_agents
from agentdiff.definition.schema import AgentDefinition, EvalRun
from agentdiff.eval.run import run_eval_set
from agentdiff.providers.claude import ClaudeProvider
from agentdiff.providers.openai import OpenAIProvider

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="agentdiff — behavioral eval diffs for agent PRs.",
)


@app.callback()
def _root() -> None:
    """Force Typer to treat commands as named sub-commands.

    Without a callback, a single-command Typer app auto-promotes that
    command to the root, so `agentdiff <path>` would work and
    `agentdiff run-local <path>` would not. The HANDOFF mandates the
    `run-local` sub-command name (and there will be more — `init`, etc.
    — in later milestones).
    """


_console = Console()
_err = Console(stderr=True)


def _configure_logging(level: str) -> None:
    """Route structlog through stdlib logging so users can quiet it."""
    logging.basicConfig(
        level=level.upper(),
        format="%(message)s",
        stream=sys.stderr,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.WARNING)
        ),
    )


def _build_provider(agent: AgentDefinition, settings: Settings) -> ClaudeProvider | OpenAIProvider:
    if agent.provider == "openai":
        return OpenAIProvider(model=agent.model, api_key="not-required-for-stub")
    if not settings.anthropic_api_key:
        raise typer.BadParameter(
            "ANTHROPIC_API_KEY is not set. Export it or put it in a .env file."
        )
    return ClaudeProvider(model=agent.model, api_key=settings.anthropic_api_key)


def _print_run_summary(run: EvalRun) -> None:
    n_pass = sum(1 for c in run.cases if c.passed)
    n_total = len(run.cases)
    pass_pct = (100.0 * n_pass / n_total) if n_total else 0.0

    _console.print(f"\n[bold]Results:[/bold] {run.agent_name} @ {run.eval_set} (sha={run.git_sha})")
    _console.print(
        f"  Pass rate: {n_pass}/{n_total} ({pass_pct:.1f}%)\n"
        f"  Cost:      ${run.total_cost_usd:.6f}\n"
        f"  Latency:   p50={run.p50_latency_ms}ms, p95={run.p95_latency_ms}ms"
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Case")
    table.add_column("Pass")
    table.add_column("Reason")
    for c in run.cases:
        mark = "[green]ok[/green]" if c.passed else "[red]FAIL[/red]"
        reason = c.failure_reason or ""
        if len(reason) > 80:
            reason = reason[:77] + "..."
        table.add_row(c.case_id, mark, reason)
    _console.print(table)


async def _run_local_async(
    repo_path: Path,
    git_sha: str,
    concurrency: int,
    settings: Settings,
) -> int:
    """Returns process exit code (0 on all-pass, 1 if any case failed)."""
    agents = load_agents(repo_path)
    if not agents:
        _err.print(f"[yellow]no agents declared in {repo_path}/agentdiff.yaml[/yellow]")
        return 0

    _console.print(f"[bold]Loaded {len(agents)} agent(s) from {repo_path}:[/bold]")
    for a in agents:
        _console.print(f"  - {a.name} (provider={a.provider}, model={a.model})")
    _console.print()

    any_failed = False
    for agent in agents:
        provider = _build_provider(agent, settings)
        for eval_file in agent.eval_files:
            cases = load_eval_cases(eval_file)
            _console.print(
                f"Running [bold]{agent.name}[/bold] @ {eval_file.name} "
                f"({len(cases)} cases, concurrency={concurrency})..."
            )
            run = await run_eval_set(
                agent=agent,
                eval_set=eval_file.name,
                cases=cases,
                provider=provider,
                git_sha=git_sha,
                concurrency=concurrency,
            )
            _print_run_summary(run)
            if any(not c.passed for c in run.cases):
                any_failed = True

    return 1 if any_failed else 0


@app.command("run-local")
def run_local(
    repo_path: Annotated[
        Path,
        typer.Argument(
            help="Path to a repo containing an agentdiff.yaml at its root.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ],
    git_sha: Annotated[
        str, typer.Option(help="Label used for `EvalRun.git_sha` in output.")
    ] = "localdev",
    concurrency: Annotated[
        int | None,
        typer.Option(
            "--concurrency",
            "-c",
            help="Max concurrent invocations per agent (default: AGENTDIFF_CONCURRENCY or 5).",
            min=1,
        ),
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable INFO-level diagnostic logs.")
    ] = False,
) -> None:
    """Load agents from the repo and run their evals against the live model API."""
    settings = Settings()
    log_level = "INFO" if verbose else settings.log_level
    _configure_logging(log_level)

    effective_concurrency = concurrency or settings.concurrency

    try:
        exit_code = asyncio.run(
            _run_local_async(repo_path, git_sha, effective_concurrency, settings)
        )
    except DefinitionError as e:
        _err.print(f"[red]definition error:[/red] {e}")
        raise typer.Exit(code=2) from e
    except TimeoutError:
        _err.print("[red]eval run exceeded the wall-clock timeout[/red]")
        raise typer.Exit(code=3) from None

    raise typer.Exit(code=exit_code)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
