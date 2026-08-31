"""Host management screens: list, add, edit, remove, test connectivity."""

from __future__ import annotations

from .. import distribution
from .. import hosts as hosts_svc
from ..errors import CntError, ConnectivityError
from . import render
from .prompts import Prompter, host_key_prompt

AUTH_CHOICES = [
    ("SSH agent", "agent"),
    ("Private key file", "key"),
    ("Password (stored encrypted)", "password"),
]


def host_screen(prompter: Prompter, console) -> None:
    while True:
        hosts = hosts_svc.list_hosts()
        if hosts:
            console.print(render.host_table(hosts))
        else:
            console.print("[dim]No hosts registered yet — add one.[/]")

        action = prompter.select(
            "Hosts",
            [
                ("Add host", "add"),
                ("Edit host", "edit"),
                ("Remove host", "remove"),
                ("Test connectivity", "test"),
                ("Scan host (reconcile models)", "scan"),
                ("Back", "back"),
            ],
        )
        if action in (None, "back"):
            return
        try:
            if action == "add":
                add_host_flow(prompter, console)
            elif action == "edit":
                edit_host_flow(prompter, console)
            elif action == "remove":
                remove_host_flow(prompter, console)
            elif action == "test":
                test_host_flow(prompter, console)
            elif action == "scan":
                scan_host_flow(prompter, console)
        except CntError as exc:
            console.print(f"[red]{exc}[/]")


def _pick_host(prompter: Prompter, message: str):
    hosts = hosts_svc.list_hosts()
    if not hosts:
        return None
    return prompter.select(message, [(h.name, h.id) for h in hosts])


def add_host_flow(prompter: Prompter, console, *, values: dict | None = None):
    values = dict(values or {})
    while True:
        for field, label in (
            ("name", "Display name"),
            ("address", "Address (host or IP)"),
            ("port", "Port"),
            ("username", "SSH username"),
            ("remote_base_path", "Remote models base path"),
        ):
            default = values.get(field, "22" if field == "port" else "")
            answer = prompter.text(label, default=str(default))
            if answer is None:
                return None
            values[field] = answer

        auth = prompter.select("Authentication method", AUTH_CHOICES)
        if auth is None:
            return None
        values["auth_method"] = auth

        key_path = None
        password = None
        if auth == "key":
            key_path = prompter.text("Private key path", default=values.get("private_key_path", ""))
            values["private_key_path"] = key_path or ""
        elif auth == "password":
            password = prompter.password("SSH password")
            if password is None:
                return None

        try:
            port = int(values["port"] or "22")
        except ValueError:
            console.print("[red]Port must be a number.[/]")
            continue

        try:
            host = hosts_svc.add_host(
                name=values["name"],
                address=values["address"],
                username=values["username"],
                remote_base_path=values["remote_base_path"],
                port=port,
                auth_method=auth,
                private_key_path=key_path,
                password=password,
            )
        except CntError as exc:
            console.print(f"[red]{exc}[/] — correct the values and continue.")
            continue

        console.print(f"[green]Added host {host.name}.[/]")
        return host


def edit_host_flow(prompter: Prompter, console):
    host_id = _pick_host(prompter, "Edit which host?")
    if host_id is None:
        console.print("[dim]No host selected.[/]")
        return
    host = hosts_svc.get_host(host_id)

    fields: dict[str, object] = {}
    for field, label, current in (
        ("name", "Display name", host.name),
        ("address", "Address", host.address),
        ("port", "Port", str(host.port)),
        ("username", "SSH username", host.username),
        ("remote_base_path", "Remote models base path", host.remote_base_path),
    ):
        answer = prompter.text(label, default=str(current))
        if answer is None:
            return
        fields[field] = int(answer) if field == "port" else answer

    auth = prompter.select("Authentication method", AUTH_CHOICES)
    if auth is None:
        return
    fields["auth_method"] = auth

    password: object = ""
    if auth == "key":
        fields["private_key_path"] = prompter.text(
            "Private key path", default=host.private_key_path or ""
        )
    elif auth == "password":
        entered = prompter.password("New SSH password (blank keeps the stored one)")
        if entered is None:
            return
        password = entered

    hosts_svc.edit_host(host_id, password=password, **fields)
    console.print("[green]Host updated.[/]")


def remove_host_flow(prompter: Prompter, console):
    host_id = _pick_host(prompter, "Remove which host?")
    if host_id is None:
        console.print("[dim]No host selected.[/]")
        return
    host = hosts_svc.get_host(host_id)
    if prompter.confirm(f"Remove host {host.name!r} and its placements?", default=False):
        hosts_svc.remove_host(host_id)
        console.print("[green]Host removed.[/]")
    else:
        console.print("[dim]Cancelled.[/]")


def test_host_flow(prompter: Prompter, console):
    host_id = _pick_host(prompter, "Test which host?")
    if host_id is None:
        console.print("[dim]No host selected.[/]")
        return
    result = hosts_svc.test_connectivity(
        host_id, host_key_prompt=host_key_prompt(prompter, console)
    )
    if result.ok:
        console.print("[green]Connectivity OK.[/]")
    elif result.reason == "host-key-changed":
        console.print(
            f"[bold red]HOST KEY CHANGED for this host — refusing to connect.[/]\n  {result.detail}"
        )
    else:
        console.print(
            f"[red]Connectivity failed: {result.reason}[/]"
            + (f"\n  {result.detail}" if result.detail else "")
        )


def scan_host_flow(prompter: Prompter, console):
    host_id = _pick_host(prompter, "Scan which host?")
    if host_id is None:
        console.print("[dim]No host selected.[/]")
        return
    try:
        result = distribution.reconcile(
            host_id, host_key_prompt=host_key_prompt(prompter, console)
        )
    except ConnectivityError as exc:
        if exc.reason == "host-key-changed":
            console.print(f"[bold red]HOST KEY CHANGED — refusing to connect.[/]\n  {exc}")
        else:
            console.print(f"[red]Could not connect: {exc.reason}[/]\n  {exc}")
        return
    if result.is_empty:
        console.print("[green]In sync — nothing changed.[/]")
        return
    for category, name in result.registered:
        console.print(f"[green]registered[/]  {category}/{name}")
    for category, name in result.added_placements:
        console.print(f"[cyan]placement +[/]  {category}/{name}")
    for category, name in result.removed:
        console.print(f"[yellow]placement -[/]  {category}/{name}")
    for detail in result.discrepancies:
        console.print(f"[red]discrepancy[/]  {detail}")
