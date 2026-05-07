"""`agentdiff` CLI entry point.

Exposes:
- `run-local` (M1): load agents, run evals, print pass/fail.
- `diff-local` (M2): materialize two git refs as worktrees, run evals
  on both, compare, print the rendered diff.

Designed so a developer can pipe either command at any agentdiff-shaped
repo and see a useful answer in under a minute.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import tempfile
from pathlib import Path
from typing import Annotated

import anthropic
import git
import structlog
import typer
from rich.console import Console
from rich.table import Table

from agentdiff.config import Settings
from agentdiff.definition import DefinitionError
from agentdiff.definition.evals import load_eval_cases
from agentdiff.definition.loader import load_agents
from agentdiff.definition.schema import AgentDefinition, EvalRun
from agentdiff.diff.compare import compare
from agentdiff.diff.render import render_case_details, render_diff
from agentdiff.eval.judge import Judger, find_rubric
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


async def _run_agent_eval_sets(
    *,
    agent: AgentDefinition,
    git_sha: str,
    settings: Settings,
    concurrency: int,
    judge_client: anthropic.AsyncAnthropic | None,
) -> list[EvalRun]:
    """Run every eval set declared on `agent` and return the EvalRuns."""
    provider = _build_provider(agent, settings)
    runs: list[EvalRun] = []
    for eval_file in agent.eval_files:
        cases = load_eval_cases(eval_file)
        judger: Judger | None = None
        # Build a judger only if any case in this set lacks `expected`.
        if judge_client is not None and any(c.expected is None for c in cases):
            rubric, fallback = find_rubric(eval_file)
            judger = Judger(client=judge_client, rubric=rubric, fallback_used=fallback)
        run = await run_eval_set(
            agent=agent,
            eval_set=eval_file.name,
            cases=cases,
            provider=provider,
            git_sha=git_sha,
            judger=judger,
            concurrency=concurrency,
        )
        runs.append(run)
    return runs


async def _diff_local_async(
    repo_path: Path,
    base_sha: str,
    head_sha: str,
    settings: Settings,
    concurrency: int,
    show_reasoning: bool,
) -> int:
    """Materialize base + head as worktrees, run evals on both, render diff.

    Returns process exit code: 0 if no threshold violations, 1 otherwise.
    """
    if not settings.anthropic_api_key:
        raise typer.BadParameter(
            "ANTHROPIC_API_KEY is not set. Export it or put it in a .env file."
        )

    repo = git.Repo(repo_path, search_parent_directories=False)
    judge_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    with (
        tempfile.TemporaryDirectory(prefix="agentdiff-base-") as base_dir,
        tempfile.TemporaryDirectory(prefix="agentdiff-head-") as head_dir,
    ):
        base_path = Path(base_dir)
        head_path = Path(head_dir)

        repo.git.worktree("add", "--detach", str(base_path), base_sha)
        repo.git.worktree("add", "--detach", str(head_path), head_sha)

        try:
            base_agents = load_agents(base_path)
            head_agents = load_agents(head_path)

            _console.print(
                f"[bold]Running base @ {base_sha[:7]}[/bold] ({len(base_agents)} agents)..."
            )
            base_runs: list[EvalRun] = []
            for a in base_agents:
                base_runs.extend(
                    await _run_agent_eval_sets(
                        agent=a,
                        git_sha=base_sha,
                        settings=settings,
                        concurrency=concurrency,
                        judge_client=judge_client,
                    )
                )

            _console.print(
                f"[bold]Running head @ {head_sha[:7]}[/bold] ({len(head_agents)} agents)..."
            )
            head_runs: list[EvalRun] = []
            for a in head_agents:
                head_runs.extend(
                    await _run_agent_eval_sets(
                        agent=a,
                        git_sha=head_sha,
                        settings=settings,
                        concurrency=concurrency,
                        judge_client=judge_client,
                    )
                )
        finally:
            # Worktrees stay registered with the source repo even after
            # the temp dir is removed; clean them up explicitly.
            for d in (base_path, head_path):
                with contextlib.suppress(git.GitCommandError):
                    repo.git.worktree("remove", "--force", str(d))

    head_agents_by_name = {a.name: a for a in head_agents}
    base_index = {(r.agent_name, r.eval_set): r for r in base_runs}
    head_index = {(r.agent_name, r.eval_set): r for r in head_runs}

    common = sorted(set(base_index) & set(head_index))
    if not common:
        _err.print("[yellow]no (agent, eval_set) pairs in common[/yellow]")
        return 0

    _console.print()
    any_violation = False
    for i, key in enumerate(common):
        agent_name, _ = key
        agent = head_agents_by_name[agent_name]
        diff = compare(agent=agent, base=base_index[key], head=head_index[key])
        if i > 0:
            _console.print("---")
        _console.print(render_diff(diff))
        if show_reasoning:
            _console.print(render_case_details(diff))
        if diff.threshold_violations:
            any_violation = True

    return 1 if any_violation else 0


@app.command("diff-local")
def diff_local(
    repo_path: Annotated[
        Path,
        typer.Argument(
            help="Path to a git repo containing an agentdiff.yaml at its root.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ],
    base_sha: Annotated[str, typer.Argument(help="Git ref for the base side.")],
    head_sha: Annotated[str, typer.Argument(help="Git ref for the head side.")],
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
    show_reasoning: Annotated[
        bool,
        typer.Option(
            "--show-reasoning",
            help="Print per-case judge reasoning after each diff (verbose, not PR-comment-shaped).",
        ),
    ] = False,
) -> None:
    """Run evals on two git refs and print a behavioral diff."""
    settings = Settings()
    log_level = "INFO" if verbose else settings.log_level
    _configure_logging(log_level)

    effective_concurrency = concurrency or settings.concurrency

    try:
        exit_code = asyncio.run(
            _diff_local_async(
                repo_path,
                base_sha,
                head_sha,
                settings,
                effective_concurrency,
                show_reasoning,
            )
        )
    except DefinitionError as e:
        _err.print(f"[red]definition error:[/red] {e}")
        raise typer.Exit(code=2) from e
    except git.InvalidGitRepositoryError as e:
        _err.print(f"[red]{repo_path} is not a git repository[/red]")
        raise typer.Exit(code=2) from e
    except git.GitCommandError as e:
        _err.print(f"[red]git error:[/red] {e}")
        raise typer.Exit(code=2) from e
    except TimeoutError:
        _err.print("[red]eval run exceeded the wall-clock timeout[/red]")
        raise typer.Exit(code=3) from None

    raise typer.Exit(code=exit_code)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
