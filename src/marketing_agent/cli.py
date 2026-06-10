"""Typer CLI for the marketing agent."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

# Force UTF-8 on Windows so model output containing Unicode doesn't crash cp1252 consoles.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

import anthropic
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .config import OUTPUTS_DIR
from .conversation import Conversation
from .orchestrator import run_orchestrator

load_dotenv()

app = typer.Typer(
    help="Enterprise marketing team AI agent — content, analytics, research.",
    no_args_is_help=True,
)
console = Console()


def _ensure_client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[red]ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.[/red]")
        raise typer.Exit(1)
    return anthropic.Anthropic()


def _save_output(text: str, prefix: str = "result") -> Path:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUTS_DIR / f"{prefix}_{ts}.md"
    path.write_text(text, encoding="utf-8")
    return path


def _event_logger(event: str, payload: dict) -> None:
    if event == "delegating":
        console.print(f"[cyan]-> delegating to[/cyan] [bold]{payload['specialist']}[/bold]")
    elif event == "specialist_done":
        console.print(
            f"[green][done] {payload['specialist']}[/green] returned ({payload['chars']} chars)"
        )
    elif event == "specialist_error":
        console.print(
            f"[red][fail] {payload['specialist']}:[/red] {payload['error']}"
        )
    elif event == "orchestrator_response":
        usage = payload.get("usage", {})
        console.print(
            f"[dim]orchestrator step: stop={payload['stop_reason']} "
            f"in={usage.get('input_tokens')} out={usage.get('output_tokens')}[/dim]"
        )


@app.command()
def run(
    prompt: str = typer.Argument(..., help="The request for the marketing team."),
    csv: Path | None = typer.Option(
        None,
        "--csv",
        help="Optional path to a campaign CSV; the orchestrator will surface this to the analytics agent.",
    ),
    save: bool = typer.Option(True, help="Save the synthesized result to outputs/."),
) -> None:
    """Run a single request end-to-end."""
    client = _ensure_client()

    if csv is not None:
        if not csv.exists():
            console.print(f"[red]CSV not found: {csv}[/red]")
            raise typer.Exit(1)
        full_prompt = f"{prompt}\n\n(Campaign CSV available at: {csv.resolve()})"
    else:
        full_prompt = prompt

    conversation = Conversation()
    console.print(Panel(prompt, title="User request", border_style="blue"))

    try:
        result = run_orchestrator(client, conversation, full_prompt, on_event=_event_logger)
    except anthropic.APIError as exc:
        console.print(f"[red]API error:[/red] {exc}")
        raise typer.Exit(1)

    console.print(Panel(Markdown(result), title="Result", border_style="green"))

    if save and result.strip():
        path = _save_output(result, prefix="result")
        console.print(f"[dim]Saved → {path}[/dim]")


@app.command()
def chat() -> None:
    """Interactive REPL — the orchestrator remembers prior turns in this session."""
    client = _ensure_client()
    conversation = Conversation()
    console.print(
        "[bold green]marketing-agent chat[/bold green] — type your request, "
        "[dim]/reset[/dim] to clear history, [dim]/quit[/dim] to exit."
    )

    while True:
        try:
            user_input = console.input("[bold blue]you ›[/bold blue] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return

        if not user_input:
            continue
        if user_input in {"/quit", "/exit"}:
            return
        if user_input == "/reset":
            conversation.reset()
            console.print("[yellow]Conversation cleared.[/yellow]")
            continue

        try:
            result = run_orchestrator(client, conversation, user_input, on_event=_event_logger)
        except anthropic.APIError as exc:
            console.print(f"[red]API error:[/red] {exc}")
            continue
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
            continue

        console.print(Panel(Markdown(result), title="agent", border_style="green"))


if __name__ == "__main__":
    app()
