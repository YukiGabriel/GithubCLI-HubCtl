import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import requests
import typer
from rich.prompt import Confirm, Prompt
from rich.panel import Panel
from rich import box

from . import ui
from .config import CONFIG_FILE, delete_token, get_recents, get_theme, get_token, require_token, save_recent, save_theme, save_token
from .github import GitHubClient, fetch_readme_public
from .gitutils import get_cwd_repo, secure_git_clone

try:
    from . import __version__
except ImportError:
    __version__ = "0.2.1"

app = typer.Typer(help="HubCtl - controle total do GitHub pelo terminal, interativo e lindo", rich_markup_mode="rich", no_args_is_help=False)
auth_app = typer.Typer(help="Autenticação", rich_markup_mode="rich")
repo_app = typer.Typer(help="Gerenciar repositórios", rich_markup_mode="rich")
issue_app = typer.Typer(help="Gerenciar issues", rich_markup_mode="rich")
pr_app = typer.Typer(help="Gerenciar pull requests", rich_markup_mode="rich")
config_app = typer.Typer(help="Configuração (tema, etc)", rich_markup_mode="rich")
user_app = typer.Typer(help="Perfis de usuários", rich_markup_mode="rich")

app.add_typer(auth_app, name="auth")
app.add_typer(repo_app, name="repo")
app.add_typer(issue_app, name="issue")
app.add_typer(pr_app, name="pr")
app.add_typer(config_app, name="config")
app.add_typer(user_app, name="user")

console = ui.console

# ---------- AUTH ----------
@auth_app.command("login")
def auth_login(token: Optional[str] = typer.Option(None, "--token", "-t", help="Seu Personal Access Token")):
    """Salva seu token do GitHub"""
    ui.print_banner(version=__version__)
    p = ui.get_palette()
    if not token:
        console.print(f"[{p['muted']}]  Crie seu token em: https://github.com/settings/tokens[/]\n")
        token = Prompt.ask("🔑 Cole seu GitHub Token", password=True)
    if not token:
        ui.error("Token vazio!", title="Falha")
        raise typer.Exit(1)
    try:
        client = GitHubClient(token)
        with console.status(f"[bold {p['primary']}]Validando token...[/]", spinner="dots12"):
            user = client.get_user()
        save_token(token)
        ui.success(f"Autenticado como [bold]{user['login']}[/]!", title="✓ Bem-vindo")
        console.print(f"[{p['muted']}]  Token salvo em {CONFIG_FILE}[/]")
        console.print()
        console.print(ui.auth_panel(user))
    except requests.HTTPError as e:
        ui.error(f"Erro ao validar token: {e}", title="Token inválido")
        if e.response is not None:
            console.print(f"[dim]{e.response.text[:400]}[/dim]")
        raise typer.Exit(1)

@auth_app.command("logout")
def auth_logout(force: bool = typer.Option(False, "--yes", "-y", help="Não pedir confirmação")):
    """Remove o token salvo (logout)"""
    p = ui.get_palette()
    token = get_token()
    env_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token and not CONFIG_FILE.exists():
        ui.warning("Você já não está logado (sem token salvo).", title="Aviso")
        if env_token:
            console.print(f"[{p['muted']}]  Mas existe GITHUB_TOKEN/GH_TOKEN no env — remova do seu shell.[/]")
        return
    if not force:
        console.print(Panel(f"[{p['muted']}]  Vamos remover o token de [{p['fg_bold']}]{CONFIG_FILE}[/]  [dim](preserva [ui] tema)[/dim]", box=box.ROUNDED, border_style=p["warning"], padding=(0,1)))
        if not Confirm.ask(f"[yellow]Remover token salvo em {CONFIG_FILE}?[/yellow]"):
            console.print("[dim]Cancelado[/dim]")
            raise typer.Exit(0)
    if delete_token():
        ui.success(f"Token removido de {CONFIG_FILE}", title="✓ Logout")
    else:
        ui.warning("Nenhum token salvo encontrado.", title="Aviso")
    if env_token:
        console.print(f"[{p['warning']}]  ⚠ GITHUB_TOKEN/GH_TOKEN ainda está no env — unset no shell se quiser logout completo.[/]")

@auth_app.command("status")
def auth_status(
    json_output: bool = typer.Option(False, "--json", help="Saída em JSON"),
    show_repos: bool = typer.Option(False, "--repos", help="Mostrar top repos do usuário"),
):
    """Mostra status da autenticação (perfil premium)"""
    p = ui.get_palette()
    token = get_token()
    if not token:
        ui.error("Não autenticado. Rode 'hubctl auth login' ou defina GITHUB_TOKEN", title="Offline")
        console.print(f"[{p['muted']}]  Dica: use [bold]hubctl[/] (modo interativo) para login guiado[/]")
        raise typer.Exit(1)
    try:
        client = GitHubClient(token)
        with console.status(f"[bold {p['primary']}]Buscando seu perfil...[/]", spinner="dots12"):
            user = client.get_user()
        if json_output:
            typer.echo(json.dumps(user, indent=2, ensure_ascii=False))
            return
        ui.show_header("Autenticado", user["login"])
        console.print(ui.user_profile_panel(user, is_self=True))
        console.print()
        src = "env GITHUB_TOKEN" if os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") else str(CONFIG_FILE)
        console.print(f"  [{p['muted']}]Token:[/] [{p['fg_bold']}]{src}[/]  [dim]•[/]  [{p['muted']}]Tema:[/] {ui.get_effective_theme_name()}")
        console.print()
        if show_repos:
            with console.status(f"[bold {p['primary']}]Buscando seus repos...[/]", spinner="dots12"):
                repos = client.list_repos(limit=6, sort="updated")
            if repos:
                console.print(ui.repo_table(f"Seus repos recentes • {len(repos)}", repos))
    except Exception as e:
        ui.error(str(e), title="Erro")
        raise typer.Exit(1)

# ---------- REPO ----------
@repo_app.command("list")
def repo_list(
    limit: int = typer.Option(20, "--limit", "-n", help="Qtd de repos"),
    visibility: str = typer.Option("all", "--visibility", help="all/public/private"),
    token: Optional[str] = typer.Option(None, "--token", help="Token (opcional)"),
    json_output: bool = typer.Option(False, "--json", help="Saída em JSON puro (p/ scripts)"),
):
    """Lista seus repositórios"""
    p = ui.get_palette()
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e), title="Auth necessário")
        raise typer.Exit(1)
    client = GitHubClient(t)
    try:
        with console.status(f"[bold {p['primary']}]Buscando repos ({visibility})...[/]", spinner="dots12"):
            repos = client.list_repos(limit=limit, visibility=visibility)
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps(repos, indent=2, ensure_ascii=False))
        return

    if not repos:
        ui.warning("Nenhum repositório encontrado.", title="Vazio")
        return

    ui.show_header("Seus Repositórios", f"{visibility} • {len(repos)} encontrados")
    console.print(ui.repo_table(f"Seus Repositórios • {visibility} • {len(repos)}", repos))
    console.print()
    console.print(Panel(f"[{p['muted']}]Dica:[/]  [bold]hubctl repo view usuario/repo[/]  [dim]•[/]  [bold]hubctl[/] para navegar com setas ↑↓  [dim]•[/]  [bold]--json[/] p/ script", box=box.ROUNDED, border_style=p["border"], padding=(0,1)))

@repo_app.command("view")
def repo_view(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    token: Optional[str] = typer.Option(None, "--token"),
    json_output: bool = typer.Option(False, "--json", help="Saída em JSON"),
):
    """Mostra detalhes de um repositório"""
    p = ui.get_palette()
    resolved = get_token(token)
    try:
        if resolved:
            client = GitHubClient(resolved)
            with console.status(f"[bold {p['primary']}]Buscando {full_name}...[/]", spinner="dots12"):
                r = client.get_repo(full_name)
        else:
            with console.status(f"[dim]Buscando {full_name} (público)...[/]", spinner="dots12"):
                resp = requests.get(f"https://api.github.com/repos/{full_name}", headers={"Accept": "application/vnd.github+json"})
                resp.raise_for_status()
                r = resp.json()
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            ui.error(f"Repo '{full_name}' não encontrado", title="404")
        else:
            ui.error(str(e))
        raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps(r, indent=2, ensure_ascii=False))
        return

    # salva nos recentes
    try:
        save_recent(full_name)
    except Exception:
        pass
    ui.show_header("Detalhes", full_name)
    console.print(ui.detail_panel(r))
    console.print()
    # dono do repo — atalho para perfil premium
    owner = (r.get("owner") or {}).get("login") or full_name.split("/")[0]
    if owner:
        console.print(Panel(f"[{p['muted']}]👤 Dono:[/] [bold {p['primary']}]{owner}[/]  [dim]•[/]  [cyan]hubctl user view {owner}[/]  ver perfil premium com top repos", box=box.ROUNDED, border_style=p["border"], padding=(0,1)))
        console.print()
    extra = ""
    if r.get("license"):
        extra += f"[{p['muted']}]📄 Licença: {r['license'].get('spdx_id') or r['license'].get('name')}[/]  "
    if r.get("homepage"):
        extra += f"[{p['muted']}]🏠 {r['homepage']}[/]"
    if extra:
        console.print(Panel(extra, box=box.ROUNDED, border_style=p["border"], padding=(0,1)))
        console.print()

    readme_text = None
    try:
        if resolved:
            _c = GitHubClient(resolved)
            with console.status(f"[dim]Buscando README.md...[/]", spinner="dots12"):
                readme_text = _c.get_readme(full_name)
        else:
            with console.status(f"[dim]Buscando README.md...[/]", spinner="dots12"):
                readme_text = fetch_readme_public(full_name)
    except Exception:
        readme_text = None
    console.print(ui.readme_panel(full_name, readme_text))
    console.print()
    console.print(Panel(f"[{p['muted']}]Ações:[/]  [cyan]hubctl repo clone {full_name}[/]  [dim]•[/]  [cyan]hubctl repo fork {full_name}[/]  [dim]•[/]  [cyan]hubctl repo star {full_name}[/]  [dim]• recentes salvos[/]", box=box.ROUNDED, border_style=p["border"], padding=(0,1)))

@repo_app.command("create")
def repo_create(
    name: str = typer.Argument(..., help="Nome do novo repo"),
    private: bool = typer.Option(False, "--private", help="Criar como privado"),
    description: str = typer.Option("", "--description", "-d", help="Descrição"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Cria um novo repositório"""
    p = ui.get_palette()
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    client = GitHubClient(t)
    try:
        with console.status(f"[bold {p['secondary']}]Criando {name}...[/]", spinner="dots12"):
            r = client.create_repo(name, private=private, description=description)
        ui.success(f"Repo criado: [bold]{r['full_name']}[/]\n[link={r['html_url']}]🔗 {r['html_url']}[/]", title="✓ Criado")
        console.print(f"[{p['muted']}]  Dica: hubctl repo view {r['full_name']}[/]")
    except requests.HTTPError as e:
        ui.error(f"Erro ao criar: {e}")
        if e.response is not None:
            console.print(f"[dim]{e.response.text}[/dim]")
        raise typer.Exit(1)

@repo_app.command("delete")
def repo_delete(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Pular confirmação"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Deleta um repositório (CUIDADO!)"""
    p = ui.get_palette()
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)

    if not yes:
        console.print(Panel(f"[{p['error']}]⚠️  AÇÃO IRREVERSÍVEL[/]  •  Todos os commits/issues/PRs serão perdidos\n[{p['fg_bold']}]{full_name}[/]", box=box.ROUNDED, border_style=p["error"], padding=(1,2), title=f"[{p['error']}]⚠️  CUIDADO[/]"))
        ui.warning(f"Você vai deletar [bold]{full_name}[/] permanentemente!", title="⚠️  CUIDADO")
        if not Confirm.ask(f"[red]Tem certeza que quer deletar [bold]{full_name}[/bold]?[/red]"):
            console.print("[dim]Cancelado[/dim]")
            raise typer.Exit(0)
        typed = Prompt.ask(f"Digite '[bold]{full_name}[/bold]' para confirmar")
        if typed != full_name:
            ui.error("Nomes não batem. Cancelado.")
            raise typer.Exit(1)

    client = GitHubClient(t)
    try:
        with console.status(f"[bold {p['error']}]Deletando {full_name}...[/]", spinner="dots12"):
            client.delete_repo(full_name)
        ui.success(f"Repo {full_name} deletado", title="🗑️  Removido")
    except requests.HTTPError as e:
        ui.error(str(e))
        if e.response is not None:
            console.print(f"[dim]{e.response.text}[/dim]")
        raise typer.Exit(1)

@repo_app.command("clone")
def repo_clone(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    ssh: bool = typer.Option(False, "--ssh", help="Usar SSH (git@github.com:...) ao invés de HTTPS"),
    directory: Optional[str] = typer.Option(None, "--dir", "-d", help="Diretório destino (padrão: ./<repo>)"),
    token: Optional[str] = typer.Option(None, "--token", help="Token (usa salvo/env se não passar)"),
):
    """Clona um repositório com git clone"""
    p = ui.get_palette()
    if shutil.which("git") is None:
        ui.error("git não encontrado no PATH. Instale o git primeiro.")
        raise typer.Exit(1)

    resolved_token = get_token(token)
    clone_url = None
    ssh_url = None
    is_private = False
    try:
        if resolved_token:
            client = GitHubClient(resolved_token)
            with console.status(f"[bold {p['primary']}]Buscando {full_name}...[/]", spinner="dots12"):
                r = client.get_repo(full_name)
        else:
            with console.status(f"[dim]Buscando {full_name}...[/]", spinner="dots12"):
                resp = requests.get(f"https://api.github.com/repos/{full_name}", headers={"Accept": "application/vnd.github+json"})
                resp.raise_for_status()
                r = resp.json()
        clone_url = r.get("clone_url")
        ssh_url = r.get("ssh_url")
        is_private = r.get("private", False)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            ui.error(f"Repo '{full_name}' não encontrado", title="404")
        elif e.response is not None and e.response.status_code == 401:
            ui.error("Não autorizado. Repo privado? Rode 'hubctl auth login'")
        else:
            ui.error(f"Erro ao buscar repo: {e}")
        raise typer.Exit(1)
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)

    dest = Path(directory) if directory else Path(full_name.split("/")[-1])
    if dest.exists():
        ui.error(f"Destino '{dest}' já existe")
        raise typer.Exit(1)

    # URLs sem token (seguro — token não aparece em `ps`)
    base_url = clone_url or f"https://github.com/{full_name}.git"
    safe_display = ssh_url if ssh else base_url
    console.print(Panel(f"[bold {p['primary']}]⬇ Clonando [bold]{full_name}[/] {'(SSH)' if ssh else '(HTTPS)'} → [bold]{dest}[/][/]\n[dim]{safe_display}[/]", box=box.ROUNDED, border_style=p["primary"], padding=(0,1)))

    rc = secure_git_clone(base_url, dest, resolved_token, is_private=is_private, ssh=ssh, ssh_url=ssh_url)
    if rc != 0:
        ui.error(f"git clone falhou (código {rc})")
        raise typer.Exit(rc)

    ui.success(f"Clonado em [bold]{dest.resolve()}[/]", title="✓ Clone ok")
    console.print(f"[{p['muted']}]  cd {dest} && code .[/]")

@repo_app.command("fork")
def repo_fork(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Faz fork de um repositório para sua conta"""
    p = ui.get_palette()
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    client = GitHubClient(t)
    try:
        with console.status(f"[bold {p['secondary']}]Fazendo fork de {full_name}...[/]", spinner="dots12"):
            r = client.fork_repo(full_name)
        ui.success(f"Fork criado! [bold]{r['full_name']}[/]\n[link={r['html_url']}]🔗 {r['html_url']}[/]", title="🍴 Fork ok")
        console.print(f"[{p['muted']}]  Clone depois: [cyan]hubctl repo clone {r['full_name']}[/][/]")
    except requests.HTTPError as e:
        ui.error(f"Erro ao fazer fork: {e}")
        if e.response is not None:
            console.print(f"[dim]{e.response.text[:500]}[/dim]")
            if e.response.status_code == 409:
                console.print("[yellow]Já existe fork? Verifique seus repos.[/yellow]")
        raise typer.Exit(1)

@repo_app.command("star")
def repo_star(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Dá star em um repositório"""
    p = ui.get_palette()
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    client = GitHubClient(t)
    try:
        with console.status(f"[bold {p['warning']}]Dando star em {full_name}...[/]", spinner="dots12"):
            client.star_repo(full_name)
        ui.success(f"⭐ Star em [bold]{full_name}[/]!", title="Favoritado")
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)

@repo_app.command("unstar")
def repo_unstar(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Remove star de um repositório"""
    p = ui.get_palette()
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    client = GitHubClient(t)
    try:
        with console.status(f"[dim]Removendo star de {full_name}...[/]", spinner="dots12"):
            client.unstar_repo(full_name)
        ui.success(f"Star removido de [bold]{full_name}[/]", title="✓")
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)

@repo_app.command("edit")
def repo_edit(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Nova descrição"),
    homepage: Optional[str] = typer.Option(None, "--homepage", help="Nova homepage"),
    private: Optional[bool] = typer.Option(None, "--private/--public", help="Tornar privado/público"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Edita descrição/visibilidade/homepage de um repo"""
    p = ui.get_palette()
    if description is None and homepage is None and private is None:
        ui.warning("Nada para editar. Use --description, --homepage ou --private/--public", title="Sem alterações")
        raise typer.Exit(1)
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    client = GitHubClient(t)
    data = {}
    if description is not None:
        data["description"] = description
    if homepage is not None:
        data["homepage"] = homepage
    if private is not None:
        data["private"] = private
    try:
        with console.status(f"[bold {p['primary']}]Atualizando {full_name}...[/]", spinner="dots12"):
            r = client.update_repo(full_name, **data)
        ui.success(f"Atualizado [bold]{r['full_name']}[/]\n[dim]{r.get('description') or ''}[/]", title="✓ Editado")
        console.print(f"[{p['muted']}]  🔗 {r['html_url']}[/]")
    except requests.HTTPError as e:
        ui.error(f"Erro ao editar: {e}")
        if e.response is not None:
            console.print(f"[dim]{e.response.text}[/dim]")
        raise typer.Exit(1)

@repo_app.command("search")
def repo_search(
    query: str = typer.Argument(None, help="Termos da busca (ex: 'cli language:python' ou vazio se usar --user)"),
    limit: int = typer.Option(10, "--limit", "-n", help="Qtd resultados"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Filtrar por usuário/org (ex: octocat, yukigabriel)"),
    token: Optional[str] = typer.Option(None, "--token"),
    json_output: bool = typer.Option(False, "--json", help="Saída em JSON"),
):
    """Busca repositórios no GitHub (search) — agora com filtro por usuário e opção de clonar"""
    p = ui.get_palette()
    effective_query = (query.strip() if query else "")
    if user and user.strip():
        user = user.strip()
        effective_query = f"user:{user} {effective_query}".strip()
    if not effective_query:
        ui.error("Informe um termo de busca ou use --user para listar repos de um usuário. Ex: hubctl repo search --user octocat --limit 5", title="Busca vazia")
        raise typer.Exit(1)
    resolved = get_token(token)
    try:
        if resolved:
            client = GitHubClient(resolved)
            with console.status(f"[bold {p['primary']}]Buscando '{effective_query}'...[/]", spinner="dots12"):
                result = client.search_repos(effective_query, limit=limit)
        else:
            with console.status(f"[dim]Buscando '{effective_query}'...[/]", spinner="dots12"):
                resp = requests.get("https://api.github.com/search/repositories", params={"q": effective_query, "per_page": limit}, headers={"Accept": "application/vnd.github+json"})
                resp.raise_for_status()
                result = resp.json()
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)

    items = result.get("items", [])
    total = result.get("total_count", len(items))
    if json_output:
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if not items:
        ui.warning(f"Nenhum resultado para '{effective_query}'", title="Vazio")
        return

    ui.show_header("Busca", f"'{effective_query}' • {total} resultados")
    console.print(ui.repo_table(f"Busca: '{effective_query}' • {total} resultados (mostrando {len(items)})", items))
    console.print()
    console.print(Panel(f"[{p['muted']}]Dica:[/]  [cyan]hubctl repo view usuario/repo[/]  [dim]•[/]  [cyan]hubctl repo clone usuario/repo[/]  [dim]•[/]  [cyan]--user[/] filtra por pessoa  [dim]•[/]  [bold]--json[/]", box=box.ROUNDED, border_style=p["border"], padding=(0,1)))

@repo_app.command("sync")
def repo_sync(
    full_name: str = typer.Argument(..., help="ex: usuario/meu-fork"),
    branch: str = typer.Option("main", "--branch", "-b", help="Branch do fork para sincronizar"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Sincroniza fork com upstream (merge-upstream)"""
    p = ui.get_palette()
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    client = GitHubClient(t)
    try:
        with console.status(f"[bold {p['primary']}]Sincronizando {full_name}:{branch} com upstream...[/]", spinner="dots12"):
            r = client.sync_fork(full_name, branch=branch)
        ui.success(f"Fork {full_name}:{branch} sincronizado!", title="✓ Sync ok")
        if r:
            console.print(f"[dim]{r}[/dim]")
    except requests.HTTPError as e:
        ui.error(f"Erro ao sincronizar: {e}")
        if e.response is not None:
            console.print(f"[dim]{e.response.text[:600]}[/dim]")
            if e.response.status_code == 409:
                console.print("[yellow]Fork já está atualizado ou sem upstream configurado.[/yellow]")
        raise typer.Exit(1)

@repo_app.command("starred")
def repo_starred(
    limit: int = typer.Option(20, "--limit", "-n", help="Qtd de repos"),
    token: Optional[str] = typer.Option(None, "--token"),
    json_output: bool = typer.Option(False, "--json", help="Saída em JSON"),
):
    """Lista seus repositórios com star"""
    p = ui.get_palette()
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    client = GitHubClient(t)
    try:
        with console.status(f"[bold {p['warning']}]Buscando starred...[/]", spinner="dots12"):
            repos = client.list_starred(limit=limit)
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)
    if json_output:
        typer.echo(json.dumps(repos, indent=2, ensure_ascii=False))
        return
    if not repos:
        ui.warning("Nenhum starred encontrado.", title="Vazio")
        return
    ui.show_header("Starred", f"{len(repos)} repos")
    console.print(ui.repo_table(f"Starred • {len(repos)}", repos))
    console.print(Panel(f"[{p['muted']}]Dica:[/]  [cyan]hubctl repo star usuario/repo[/]  [dim]•[/]  [bold]--json[/]", box=box.ROUNDED, border_style=p["border"], padding=(0,1)))

# ---------- ISSUE ----------
@issue_app.command("list")
def issue_list(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    state: str = typer.Option("open", "--state", help="open/closed/all"),
    limit: int = typer.Option(20, "--limit", "-n"),
    token: Optional[str] = typer.Option(None, "--token"),
    json_output: bool = typer.Option(False, "--json", help="Saída em JSON"),
):
    """Lista issues de um repo"""
    p = ui.get_palette()
    try:
        t = require_token(token)
    except ValueError:
        t = get_token(token)
        if not t:
            try:
                with console.status(f"[dim]Buscando issues de {full_name}...[/]", spinner="dots12"):
                    resp = requests.get(f"https://api.github.com/repos/{full_name}/issues", params={"state": state, "per_page": limit}, headers={"Accept": "application/vnd.github+json"})
                    resp.raise_for_status()
                    issues = resp.json()
                    issues = [i for i in issues if "pull_request" not in i]
                    if json_output:
                        typer.echo(json.dumps(issues, indent=2, ensure_ascii=False))
                        return
                    if not issues:
                        ui.warning("Nenhuma issue encontrada", title="Vazio")
                        return
                    ui.show_header("Issues", f"{full_name} • {state}")
                    console.print(ui.issue_table(f"Issues • {full_name} • {state}", issues))
                    return
            except Exception as e:
                ui.error(str(e))
                raise typer.Exit(1)
    client = GitHubClient(t) if t else None
    if not client:
        ui.error("Token não encontrado")
        raise typer.Exit(1)
    try:
        with console.status(f"[bold {p['primary']}]Buscando issues de {full_name}...[/]", spinner="dots12"):
            issues = client.list_issues(full_name, state=state, limit=limit)
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)

    issues = [i for i in issues if "pull_request" not in i]

    if json_output:
        typer.echo(json.dumps(issues, indent=2, ensure_ascii=False))
        return

    if not issues:
        ui.warning("Nenhuma issue encontrada", title="Vazio")
        return

    ui.show_header("Issues", f"{full_name} • {state} • {len(issues)}")
    console.print(ui.issue_table(f"Issues • {full_name} • {state}", issues))
    console.print()
    console.print(Panel(f"[{p['muted']}]Dica:[/]  [cyan]hubctl issue view {full_name} <num>[/]  [dim]•[/]  [cyan]hubctl issue create {full_name}[/]  [dim]•[/]  [bold]--json[/]", box=box.ROUNDED, border_style=p["border"], padding=(0,1)))

@issue_app.command("view")
def issue_view(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    number: int = typer.Argument(..., help="número da issue"),
    token: Optional[str] = typer.Option(None, "--token"),
    json_output: bool = typer.Option(False, "--json", help="Saída em JSON"),
):
    """Mostra detalhes de uma issue"""
    p = ui.get_palette()
    resolved = get_token(token)
    try:
        if resolved:
            client = GitHubClient(resolved)
            with console.status(f"[bold {p['primary']}]Buscando issue #{number}...[/]", spinner="dots12"):
                issue = client.get_issue(full_name, number)
        else:
            with console.status(f"[dim]Buscando issue #{number}...[/]", spinner="dots12"):
                resp = requests.get(f"https://api.github.com/repos/{full_name}/issues/{number}", headers={"Accept": "application/vnd.github+json"})
                resp.raise_for_status()
                issue = resp.json()
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            ui.error(f"Issue #{number} não encontrada em {full_name}")
        else:
            ui.error(str(e))
        raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps(issue, indent=2, ensure_ascii=False))
        return

    state = issue["state"]
    color = p["success"] if state == "open" else p["error"]
    labels = "  ".join(f"[{p['secondary']}]#{l['name']}[/]" for l in issue.get("labels", [])) or "[dim]sem labels[/dim]"
    ui.show_header(f"Issue #{issue['number']}", issue["title"][:60])
    console.print(ui.info_panel(
        f"#{issue['number']} • {issue['title']}",
        f"[bold {color}]● {state.upper()}[/]  por [bold]{issue['user']['login']}[/]  em {issue['created_at'][:10]}  •  💬 {issue['comments']} comentários\n"
        f"[dim]{labels}[/]\n\n"
        f"{issue.get('body') or '[dim]Sem descrição[/dim]'}\n\n"
        f"[dim]🔗 {issue['html_url']}[/]",
        border_color=color
    ))

@issue_app.command("create")
def issue_create(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    title: str = typer.Option(..., "--title", "-t", help="Título da issue", prompt="Título da issue"),
    body: str = typer.Option("", "--body", "-b", help="Corpo/descrição"),
    label: Optional[str] = typer.Option(None, "--label", "-l", help="Label (pode repetir)", show_default=False),
    labels: Optional[str] = typer.Option(None, "--labels", help="Labels separados por vírgula"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Cria uma nova issue"""
    p = ui.get_palette()
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    all_labels = []
    if label:
        all_labels.append(label)
    if labels:
        all_labels.extend([s.strip() for s in labels.split(",") if s.strip()])
    if not body:
        try:
            import sys
            if sys.stdin.isatty():
                body = Prompt.ask("📝 Descrição (opcional)", default="") or ""
        except Exception:
            body = ""

    client = GitHubClient(t)
    try:
        with console.status(f"[bold {p['secondary']}]Criando issue...[/]", spinner="dots12"):
            issue = client.create_issue(full_name, title=title, body=body, labels=all_labels or None)
        ui.success(f"Issue criada: [bold]#{issue['number']} {issue['title']}[/]\n[link={issue['html_url']}]{issue['html_url']}[/]", title="🐛 Criada")
    except requests.HTTPError as e:
        ui.error(f"Erro ao criar issue: {e}")
        if e.response is not None:
            console.print(f"[dim]{e.response.text}[/dim]")
        raise typer.Exit(1)

@issue_app.command("close")
def issue_close(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    number: int = typer.Argument(..., help="número da issue"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Fecha uma issue"""
    p = ui.get_palette()
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    console.print(Panel(f"[{p['warning']}]  Fechar issue [bold]#{number}[/] em [{p['fg_bold']}]{full_name}[/] ?[/]", box=box.ROUNDED, border_style=p["warning"], padding=(0,1)))
    if not Confirm.ask(f"Fechar issue [bold]#{number}[/] em {full_name}?"):
        console.print("[dim]Cancelado[/dim]")
        raise typer.Exit(0)
    client = GitHubClient(t)
    try:
        with console.status(f"[bold {p['error']}]Fechando #{number}...[/]", spinner="dots12"):
            issue = client.close_issue(full_name, number)
        ui.success(f"Issue #{issue['number']} fechada", title="✓ Fechada")
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)

@issue_app.command("comment")
def issue_comment(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    number: int = typer.Argument(..., help="número da issue"),
    body: str = typer.Option(..., "--body", "-b", help="Texto do comentário"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Comenta em uma issue/PR"""
    p = ui.get_palette()
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    client = GitHubClient(t)
    try:
        with console.status(f"[bold {p['primary']}]Comentando #{number}...[/]", spinner="dots12"):
            c = client.comment_issue(full_name, number, body)
        ui.success(f"Comentário criado em #{number}!", title="💬 Comentado")
        console.print(f"[dim]{c.get('html_url','')}[/dim]")
    except requests.HTTPError as e:
        ui.error(f"Erro ao comentar: {e}")
        if e.response is not None:
            console.print(f"[dim]{e.response.text[:600]}[/dim]")
        raise typer.Exit(1)

@issue_app.command("comments")
def issue_comments(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    number: int = typer.Argument(..., help="número da issue/PR"),
    token: Optional[str] = typer.Option(None, "--token"),
    json_output: bool = typer.Option(False, "--json", help="Saída em JSON"),
):
    """Lista comentários de uma issue"""
    p = ui.get_palette()
    try:
        t = require_token(token)
    except ValueError:
        t = get_token(token)
    client = GitHubClient(t) if t else None
    try:
        if client:
            with console.status(f"[dim]Buscando comentários #{number}...[/]", spinner="dots12"):
                comments = client.list_comments(full_name, number)
        else:
            with console.status(f"[dim]Buscando comentários #{number}...[/]", spinner="dots12"):
                resp = requests.get(f"https://api.github.com/repos/{full_name}/issues/{number}/comments", headers={"Accept": "application/vnd.github+json"})
                resp.raise_for_status()
                comments = resp.json()
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)
    if json_output:
        typer.echo(json.dumps(comments, indent=2, ensure_ascii=False))
        return
    if not comments:
        ui.warning("Nenhum comentário.", title="Vazio")
        return
    ui.show_header(f"Comentários #{number}", full_name)
    for c in comments:
        console.print(ui.info_panel(f"💬 {c['user']['login']} • {c['created_at'][:16]}", c.get("body") or "[dim]vazio[/dim]", border_color=p["muted"]))
        console.print()

# ---------- PR ----------
@pr_app.command("list")
def pr_list(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    state: str = typer.Option("open", "--state", help="open/closed/all"),
    limit: int = typer.Option(20, "--limit", "-n"),
    token: Optional[str] = typer.Option(None, "--token"),
    json_output: bool = typer.Option(False, "--json", help="Saída em JSON"),
):
    """Lista PRs de um repo"""
    p = ui.get_palette()
    resolved = get_token(token)
    try:
        if resolved:
            client = GitHubClient(resolved)
            with console.status(f"[bold {p['secondary']}]Buscando PRs de {full_name}...[/]", spinner="dots12"):
                prs = client.list_prs(full_name, state=state, limit=limit)
        else:
            with console.status(f"[dim]Buscando PRs de {full_name}...[/]", spinner="dots12"):
                resp = requests.get(f"https://api.github.com/repos/{full_name}/pulls", params={"state": state, "per_page": limit}, headers={"Accept": "application/vnd.github+json"})
                resp.raise_for_status()
                prs = resp.json()
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps(prs, indent=2, ensure_ascii=False))
        return

    if not prs:
        ui.warning("Nenhum PR encontrado", title="Vazio")
        return

    ui.show_header("Pull Requests", f"{full_name} • {state}")
    console.print(ui.pr_table(f"Pull Requests • {full_name} • {state}", prs))
    console.print()
    console.print(Panel(f"[{p['muted']}]Dica:[/]  [cyan]hubctl pr view {full_name} <num>[/]  [dim]•[/]  [bold]--json[/]", box=box.ROUNDED, border_style=p["border"], padding=(0,1)))

@pr_app.command("view")
def pr_view(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    number: int = typer.Argument(..., help="número do PR"),
    token: Optional[str] = typer.Option(None, "--token"),
    json_output: bool = typer.Option(False, "--json", help="Saída em JSON"),
):
    """Mostra detalhes de um PR"""
    p = ui.get_palette()
    resolved = get_token(token)
    try:
        if resolved:
            client = GitHubClient(resolved)
            with console.status(f"[bold {p['secondary']}]Buscando PR #{number}...[/]", spinner="dots12"):
                pr = client.get_pr(full_name, number)
        else:
            with console.status(f"[dim]Buscando PR #{number}...[/]", spinner="dots12"):
                resp = requests.get(f"https://api.github.com/repos/{full_name}/pulls/{number}", headers={"Accept": "application/vnd.github+json"})
                resp.raise_for_status()
                pr = resp.json()
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            ui.error(f"PR #{number} não encontrado em {full_name}")
        else:
            ui.error(str(e))
        raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps(pr, indent=2, ensure_ascii=False))
        return

    state = pr["state"]
    merged = pr.get("merged", False)
    if merged:
        color = p["secondary"]
        state_str = "MERGED"
    elif state == "open":
        color = p["success"]
        state_str = "OPEN"
    else:
        color = p["error"]
        state_str = state.upper()

    ui.show_header(f"PR #{pr['number']}", pr["title"][:55])
    console.print(ui.info_panel(
        f"#{pr['number']} • {pr['title']}",
        f"[bold {color}]● {state_str}[/]  por [bold]{pr['user']['login']}[/]  em {pr['created_at'][:10]}\n"
        f"[{p['primary']}]{pr['head']['ref']}[/] → [bold]{pr['base']['ref']}[/]  •  💬 {pr.get('comments',0)}  •  ✅ {pr.get('additions',0)}++ / ❌ {pr.get('deletions',0)}--  •  📄 {pr.get('changed_files',0)} arquivos\n\n"
        f"{pr.get('body') or '[dim]Sem descrição[/dim]'}\n\n"
        f"[dim]🔗 {pr['html_url']}[/]",
        border_color=color
    ))

@pr_app.command("create")
def pr_create(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    title: str = typer.Option(..., "--title", "-t", help="Título do PR", prompt="Título do PR"),
    head: str = typer.Option(..., "--head", "-h", help="Branch de origem (sua feature)", prompt="Branch head (ex: feature/minha)"),
    base: str = typer.Option("main", "--base", "-b", help="Branch base (ex: main)"),
    body: str = typer.Option("", "--body", help="Descrição"),
    draft: bool = typer.Option(False, "--draft", help="Criar como draft"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Cria um Pull Request"""
    p = ui.get_palette()
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    if not body:
        try:
            import sys
            if sys.stdin.isatty():
                body = Prompt.ask("📝 Descrição (opcional)", default="") or ""
        except Exception:
            body = ""
    client = GitHubClient(t)
    try:
        with console.status(f"[bold {p['secondary']}]Criando PR...[/]", spinner="dots12"):
            pr = client.create_pr(full_name, title=title, head=head, base=base, body=body, draft=draft)
        ui.success(f"PR criado: [bold]#{pr['number']} {pr['title']}[/]\n[link={pr['html_url']}]{pr['html_url']}[/]  {'[dim](draft)[/]' if pr.get('draft') else ''}", title="🔀 PR criado")
    except requests.HTTPError as e:
        ui.error(f"Erro ao criar PR: {e}")
        if e.response is not None:
            console.print(f"[dim]{e.response.text}[/dim]")
        raise typer.Exit(1)

@pr_app.command("merge")
def pr_merge(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    number: int = typer.Argument(..., help="número do PR"),
    method: str = typer.Option("merge", "--method", help="merge/squash/rebase"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Faz merge de um PR"""
    p = ui.get_palette()
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    if method not in ("merge", "squash", "rebase"):
        ui.error("method deve ser merge/squash/rebase")
        raise typer.Exit(1)
    if not Confirm.ask(f"[bold]Merge PR #{number} em {full_name} via {method}?[/]"):
        console.print("[dim]Cancelado[/dim]")
        raise typer.Exit(0)
    client = GitHubClient(t)
    try:
        with console.status(f"[bold {p['success']}]Mergeando PR #{number}...[/]", spinner="dots12"):
            r = client.merge_pr(full_name, number, merge_method=method)
        ui.success(f"PR #{number} mergeado via {method}!", title="✓ Merge ok")
        console.print(f"[dim]{r}[/dim]")
    except requests.HTTPError as e:
        ui.error(f"Erro ao mergear: {e}")
        if e.response is not None:
            console.print(f"[dim]{e.response.text[:600]}[/dim]")
        raise typer.Exit(1)

@pr_app.command("diff")
def pr_diff(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    number: int = typer.Argument(..., help="número do PR"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Mostra diff de um PR (raw)"""
    p = ui.get_palette()
    resolved = get_token(token)
    try:
        if resolved:
            client = GitHubClient(resolved)
            with console.status(f"[dim]Buscando diff #{number}...[/]", spinner="dots12"):
                diff = client.get_pr_diff(full_name, number)
        else:
            with console.status(f"[dim]Buscando diff #{number}...[/]", spinner="dots12"):
                resp = requests.get(f"https://api.github.com/repos/{full_name}/pulls/{number}", headers={"Accept": "application/vnd.github.diff"}, timeout=15)
                resp.raise_for_status()
                diff = resp.text
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)
    if not diff:
        ui.warning("Sem diff ou PR não encontrado.")
        return
    # mostra com syntax
    from rich.syntax import Syntax
    console.print(Panel(Syntax(diff[:12000], "diff", theme="monokai" if p["name"]=="dark" else "github-light", line_numbers=True), title=f"[bold {p['primary']}]Diff PR #{number} — {full_name}[/]", border_style=p["primary"], box=box.ROUNDED))

@pr_app.command("files")
def pr_files(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    number: int = typer.Argument(..., help="número do PR"),
    token: Optional[str] = typer.Option(None, "--token"),
    json_output: bool = typer.Option(False, "--json", help="Saída em JSON"),
):
    """Lista arquivos alterados num PR"""
    p = ui.get_palette()
    resolved = get_token(token)
    try:
        if resolved:
            client = GitHubClient(resolved)
            with console.status(f"[dim]Buscando arquivos PR #{number}...[/]", spinner="dots12"):
                files = client.get_pr_files(full_name, number)
        else:
            with console.status(f"[dim]Buscando arquivos...[/]", spinner="dots12"):
                resp = requests.get(f"https://api.github.com/repos/{full_name}/pulls/{number}/files", headers={"Accept": "application/vnd.github+json"}, timeout=15)
                resp.raise_for_status()
                files = resp.json()
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)
    if json_output:
        typer.echo(json.dumps(files, indent=2, ensure_ascii=False))
        return
    if not files:
        ui.warning("Nenhum arquivo alterado.")
        return
    ui.show_header(f"Arquivos PR #{number}", f"{full_name} • {len(files)} arquivos")
    from rich.table import Table
    table = Table(box=box.ROUNDED, border_style=p["border"], header_style=p["header"], expand=True, padding=(0,1))
    table.add_column("Arquivo", style=p["fg_bold"], ratio=3)
    table.add_column("Status", width=10, justify="center")
    table.add_column("+", style=p["success"], justify="right", width=7)
    table.add_column("-", style=p["error"], justify="right", width=7)
    for f in files[:50]:
        table.add_row(f["filename"], f["status"], str(f.get("additions",0)), str(f.get("deletions",0)))
    console.print(table)
    if len(files) > 50:
        console.print(f"[dim]... e mais {len(files)-50} arquivos (use --json)[/dim]")

# ---------- CONFIG ----------
@config_app.command("theme")
def config_theme(
    theme: Optional[str] = typer.Argument(None, help="dark / light / auto (vazio mostra atual)"),
):
    """Configura tema (auto detecta claro/escuro). Use GHC_THEME env para override."""
    p = ui.get_palette()
    current = get_theme()
    effective = ui.get_effective_theme_name()
    if theme is None:
        ui.print_banner(version=__version__)
        console.print()
        console.print(Panel(
            f"  Tema preferido: [bold {p['primary']}]{current}[/]  → efetivo: [bold {p['fg_bold']}]{effective}[/]  {'☀️ claro' if effective=='light' else '🌙 escuro'}\n"
            f"  [{p['muted']}]Detectado via COLORFGBG={os.getenv('COLORFGBG','-')}  •  GHC_THEME={os.getenv('GHC_THEME','-')}  •  HUBCTL_THEME={os.getenv('HUBCTL_THEME','-')}[/]\n"
            f"  [{p['muted']}]Para mudar: [bold]hubctl config theme [dark|light|auto][/]  •  env: GHC_THEME=light hubctl[/]",
            box=box.ROUNDED, border_style=p["border"], padding=(1,2), title=f"[{p['primary']}]◆ Tema[/]"
        ))
        console.print()
        console.print(f"[{p['muted2']}]  Preview:[/]")
        console.print()
        ui.success("Exemplo sucesso — tudo ok!", title="Sucesso")
        ui.warning("Exemplo aviso — atenção", title="Aviso")
        ui.error("Exemplo erro — falhou", title="Erro")
        console.print()
        console.print(ui.detail_panel({"full_name":"demo/repo","private":False,"description":"Preview de repo para ver contraste do tema atual","stargazers_count":1234,"forks_count":42,"watchers_count":1234,"open_issues_count":5,"language":"Python","created_at":"2024-01-01T00:00:00Z","updated_at":"2024-06-01T00:00:00Z","html_url":"https://github.com/demo/repo","topics":["cli","python","hubctl"]}))
        console.print()
        console.print(Panel(f"[{p['muted']}]Dica:[/]  fundo branco e letra sumindo?  [bold]hubctl config theme light[/] resolve.", box=box.ROUNDED, border_style=p["border"], padding=(0,1)))
        return
    theme = theme.lower()
    if theme not in ("dark", "light", "auto"):
        ui.error("Tema deve ser dark, light ou auto", title="Inválido")
        raise typer.Exit(1)
    save_theme(theme)
    ui.reload_theme()
    p = ui.get_palette()
    new_effective = ui.get_effective_theme_name()
    ui.success(f"Tema salvo: [bold]{theme}[/]  (efetivo agora: {new_effective})", title="✓ Configurado")
    console.print(f"[{p['muted']}]  Reinicie o terminal ou rode hubctl novamente pra ver 100%[/]")
    console.print()
    ui.print_banner(version=__version__)

@config_app.command("show")
def config_show():
    """Mostra toda configuração salva"""
    import configparser
    p = ui.get_palette()
    ui.print_banner(version=__version__)
    console.print()
    console.print(Panel(f"[{p['muted']}]Arquivo:[/] [{p['fg_bold']}]{CONFIG_FILE}[/]  [dim](GHC_THEME env: {os.getenv('GHC_THEME','-')})[/]", box=box.ROUNDED, border_style=p["border"], padding=(0,1)))
    console.print()
    if not CONFIG_FILE.exists():
        ui.warning("Nenhum config salvo ainda.", title="Vazio")
        console.print(f"[{p['muted']}]  Dica: hubctl auth login para criar[/]")
        return
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE)
    for sec in cfg.sections():
        console.print(f"[bold {p['primary']}][{sec}][/]")
        for k, v in cfg[sec].items():
            if k == "token":
                v = v[:6] + "***" + v[-4:] if len(v) > 10 else "***"
            console.print(f"  {k} = {v}")
    console.print()
    console.print(Panel(f"[{p['muted']}]Tema efetivo:[/] [{p['fg_bold']}]{ui.get_effective_theme_name()}[/] ({'claro' if ui.get_effective_theme_name()=='light' else 'escuro'})  [dim]•[/]  [{p['muted']}]mude com hubctl config theme[/]", box=box.ROUNDED, border_style=p["border"], padding=(0,1)))

@config_app.command("recent")
def config_recent(
    clear: bool = typer.Option(False, "--clear", help="Limpar histórico de repos recentes"),
    json_output: bool = typer.Option(False, "--json", help="Saída em JSON"),
):
    """Mostra / limpa repos recentes"""
    from .config import get_recents, clear_recents
    p = ui.get_palette()
    if clear:
        clear_recents()
        ui.success("Histórico de recentes limpo.", title="✓")
        return
    recents = get_recents(limit=20)
    if json_output:
        typer.echo(json.dumps(recents, indent=2, ensure_ascii=False))
        return
    if not recents:
        ui.warning("Nenhum repo recente. Use hubctl repo view/clone para popular.", title="Vazio")
        return
    ui.show_header("Recentes", f"{len(recents)} últimos acessos")
    from rich.table import Table as _Table
    table = _Table(box=box.ROUNDED, border_style=p["border"], header_style=p["header"], expand=True, padding=(0,1))
    table.add_column("#", width=4, justify="right", style=p["muted2"])
    table.add_column("Repositório", style=f"bold {p['primary']}")
    table.add_column("Ação", style=p["muted"], width=28)
    for i, r in enumerate(recents, 1):
        table.add_row(str(i), r, f"hubctl repo view {r}")
    console.print(table)
    console.print(Panel(f"[{p['muted']}]Dica:[/]  [cyan]hubctl config recent --clear[/] limpa histórico  [dim]•[/]  [bold]--json[/]", box=box.ROUNDED, border_style=p["border"], padding=(0,1)))

@config_app.command("completion")
def config_completion(
    shell: str = typer.Argument(None, help="bash/zsh/fish/powershell (vazio mostra instruções)"),
):
    """Instala completion de shell"""
    p = ui.get_palette()
    ui.show_header("Completion", "Autocompletar no seu shell")
    if shell is None:
        console.print(Panel(
            f"[{p['fg_bold']}]Gere completion para seu shell:[/]\n"
            f"  [cyan]hubctl --install-completion bash[/]  [dim]# bash[/]\n"
            f"  [cyan]hubctl --install-completion zsh[/]   [dim]# zsh[/]\n"
            f"  [cyan]hubctl --install-completion fish[/]  [dim]# fish[/]\n"
            f"  [cyan]hubctl --install-completion powershell[/]  [dim]# PowerShell[/]\n\n"
            f"[{p['muted']}]Ou use o helper:[/] [bold]hubctl config completion bash[/] → instala direto\n"
            f"[{p['muted']}]Depois reinicie o terminal.[/]",
            box=box.ROUNDED, border_style=p["primary"], padding=(1,2), title=f"[{p['primary']}]◆ Shell[/]"
        ))
        return
    shell = shell.lower()
    if shell not in ("bash", "zsh", "fish", "powershell"):
        ui.error("Shell deve ser bash/zsh/fish/powershell")
        raise typer.Exit(1)
    # usa typer's built-in installer via subprocess
    result = subprocess.run([sys.executable, "-m", "typer", str(Path(__file__)), "--install-completion", shell])
    if result.returncode == 0:
        ui.success(f"Completion para {shell} instalado! Reinicie o terminal.", title="✓")
    else:
        ui.error(f"Falha ao instalar completion para {shell} (código {result.returncode})")
        raise typer.Exit(result.returncode)

# ---------- USER ----------
@user_app.command("view")
def user_view(
    username: str = typer.Argument(..., help="login do usuário (ex: torvalds, octocat)"),
    token: Optional[str] = typer.Option(None, "--token", help="Token (usa salvo se não passar)"),
    repos: int = typer.Option(6, "--repos", "-r", help="Qtd de repos top para mostrar"),
    json_output: bool = typer.Option(False, "--json", help="Saída em JSON"),
):
    """Mostra perfil premium de qualquer usuário/org + top repos"""
    p = ui.get_palette()
    resolved = get_token(token)
    # busca perfil (anônimo ok, mas com token tem rate maior)
    try:
        if resolved:
            client = GitHubClient(resolved)
            with console.status(f"[bold {p['primary']}]Buscando perfil {username}...[/]", spinner="dots12"):
                user = client.get_user_by_username(username)
                user_repos = client.list_user_repos(username, limit=repos, sort="updated")
        else:
            from .github import fetch_user_public, fetch_user_repos_public
            with console.status(f"[dim]Buscando perfil {username} (anônimo)...[/]", spinner="dots12"):
                user = fetch_user_public(username)
                if not user:
                    ui.error(f"Usuário '{username}' não encontrado", title="404")
                    raise typer.Exit(1)
                user_repos = fetch_user_repos_public(username, limit=repos, sort="updated")
                # tenta token anon mas sem auth já pegou
        if not user:
            ui.error(f"Usuário '{username}' não encontrado", title="404")
            raise typer.Exit(1)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            ui.error(f"Usuário '{username}' não encontrado", title="404")
        else:
            ui.error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)

    if json_output:
        out = {"user": user, "top_repos": user_repos}
        typer.echo(json.dumps(out, indent=2, ensure_ascii=False))
        return

    # header + perfil premium
    is_self = False
    try:
        if resolved:
            me = GitHubClient(resolved).get_user()
            is_self = me.get("login", "").lower() == username.lower()
    except Exception:
        pass

    ui.show_header("Perfil", f"{username} {'(você)' if is_self else ''}")
    console.print(ui.user_profile_panel(user, is_self=is_self))
    console.print()
    # orgs inline compacto (sem painel extra)
    try:
        if resolved:
            orgs = client.list_user_orgs(username)
            if orgs:
                org_str = "  ".join(f"[{p['secondary']}]@{o['login']}[/]" for o in orgs[:5])
                console.print(f"  [{p['muted']}]🏢[/] {org_str}")
                console.print()
    except Exception:
        pass

    if user_repos:
        console.print(ui.repo_table(f"Top repos de {username} • {len(user_repos)}", user_repos))
        console.print()
    else:
        console.print(Panel(f"[dim]📦 {username} não tem repos públicos visíveis[/]", box=box.ROUNDED, border_style=p["border"], padding=(0,1)))
        console.print()
    console.print(Panel(f"[{p['muted']}]→[/]  [cyan]hubctl user repos {username} --limit 20[/]  [dim]•[/]  [cyan]hubctl repo view {username}/<repo>[/]  [dim]•[/]  [cyan]hubctl repo search --user {username}[/]", box=box.ROUNDED, border_style=p["border"], padding=(0,1)))

@user_app.command("repos")
def user_repos(
    username: str = typer.Argument(..., help="login do usuário/org"),
    limit: int = typer.Option(20, "--limit", "-n", help="Qtd de repos"),
    sort: str = typer.Option("updated", "--sort", help="updated/created/pushed/full_name/stars"),
    token: Optional[str] = typer.Option(None, "--token"),
    json_output: bool = typer.Option(False, "--json", help="Saída em JSON"),
):
    """Lista repos de um usuário/org (públicos)"""
    p = ui.get_palette()
    resolved = get_token(token)
    try:
        if resolved:
            client = GitHubClient(resolved)
            with console.status(f"[bold {p['primary']}]Buscando repos de {username}...[/]", spinner="dots12"):
                repos = client.list_user_repos(username, limit=limit, sort=sort)
        else:
            from .github import fetch_user_repos_public, fetch_user_public
            with console.status(f"[dim]Buscando repos de {username}...[/]", spinner="dots12"):
                # verifica se user existe
                u = fetch_user_public(username, token=None)
                if not u:
                    ui.error(f"Usuário '{username}' não encontrado", title="404")
                    raise typer.Exit(1)
                repos = fetch_user_repos_public(username, limit=limit, sort=sort, token=None)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            ui.error(f"Usuário '{username}' não encontrado", title="404")
        else:
            ui.error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps(repos, indent=2, ensure_ascii=False))
        return
    if not repos:
        ui.warning(f"Nenhum repo público para {username}", title="Vazio")
        return
    ui.show_header(f"Repos de {username}", f"{len(repos)} repos • sort:{sort}")
    console.print(ui.repo_table(f"Repos de {username} • {len(repos)}", repos))
    console.print(Panel(f"[{p['muted']}]Dica:[/]  [cyan]hubctl repo view {username}/<repo>[/]  [dim]•[/]  [cyan]hubctl user view {username}[/]", box=box.ROUNDED, border_style=p["border"], padding=(0,1)))

@app.command("dashboard", help="Visão geral: perfil, rate-limit, cwd e recentes")
def dashboard(
    token: Optional[str] = typer.Option(None, "--token"),
    json_output: bool = typer.Option(False, "--json", help="Saída em JSON"),
):
    """Dashboard premium — perfil, rate-limit, repo do cwd e recentes"""
    p = ui.get_palette()
    resolved = get_token(token)
    if not resolved:
        ui.error("Não autenticado. Rode 'hubctl auth login'", title="Offline")
        raise typer.Exit(1)
    client = GitHubClient(resolved)
    # cwd detect
    from .gitutils import get_cwd_repo
    from .config import get_recents, save_recent
    cwd_repo = get_cwd_repo()
    # busca perfil + rate limit
    try:
        with console.status(f"[bold {p['primary']}]Carregando dashboard...[/]", spinner="dots12"):
            user = client.get_user()
            rl = client.get_rate_limit()
            recent = get_recents(limit=5)
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)
    if json_output:
        out = {"user": user, "rate_limit": rl, "cwd_repo": cwd_repo, "recent": recent}
        typer.echo(json.dumps(out, indent=2, ensure_ascii=False))
        return
    ui.show_header("Dashboard", f"{user['login']} • {rl['resources']['core']['remaining']}/{rl['resources']['core']['limit']} req restantes")
    console.print(ui.user_profile_panel(user, is_self=True))
    console.print()
    console.print(ui.user_summary_grid(user))
    console.print()
    # rate limit panel
    core = rl["resources"]["core"]
    rem = core["remaining"]
    lim = core["limit"]
    pct = (rem/lim*100) if lim else 0
    col = p["success"] if pct>30 else p["warning"] if pct>10 else p["error"]
    bar_f = int(pct/100*20)
    bar = f"[{col}]{'█'*bar_f}[/][{p['border']}]{'░'*(20-bar_f)}[/]"
    console.print(Panel(
        f"  Rate limit: {bar}  [{col}]{rem}/{lim}[/]  •  [dim]reset {core.get('reset')}[/]\n"
        f"  [{p['muted']}]Search: {rl['resources']['search']['remaining']}/{rl['resources']['search']['limit']}[/]",
        box=box.ROUNDED, border_style=p["border"], padding=(0,1), title=f"[{p['primary']}]◆ API[/]"
    ))
    console.print()
    # cwd repo
    if cwd_repo:
        console.print(Panel(f"[{p['fg_bold']}]📁 Repo do diretório atual:[/] [bold {p['primary']}]{cwd_repo}[/]\n[{p['muted']}]  hubctl repo view {cwd_repo}  •  hubctl issue list {cwd_repo}[/]", box=box.ROUNDED, border_style=p["success"], padding=(1,2), title=f"[{p['success']}]◆ CWD[/]"))
        # salva como recente
        save_recent(cwd_repo)
    else:
        console.print(Panel(f"[{p['muted']}]Nenhum repo GitHub detectado no cwd[/]\n[dim]  {Path.cwd()}[/]\n[dim]  Dica: git clone um repo ou rode dentro de um projeto[/]", box=box.ROUNDED, border_style=p["border"], padding=(1,2), title=f"[{p['muted']}]◆ CWD[/]"))
    console.print()
    if recent:
        console.print(Panel(
            "\n".join(f"  [{p['primary']}]•[/]  [{p['fg_bold']}]{r}[/]" for r in recent),
            box=box.ROUNDED, border_style=p["border"], padding=(1,2), title=f"[{p['primary']}]◆ Recentes[/]"
        ))
        console.print(f"[{p['muted']}]  hubctl config recent --clear  para limpar[/]")
    else:
        console.print(f"[{p['muted']}]  Sem recentes — navegue em repos para popular[/]")
    console.print()

@app.command("interactive", help="Modo interativo com navegação por setas (↑/↓)")
def interactive():
    """Inicia o modo interativo (navegação com ↑/↓)"""
    try:
        from .interactive import run_interactive
    except ImportError as e:
        ui.error(f"Modo interativo requer 'questionary': {e}")
        console.print("[dim]Instale com: uv pip install questionary[/dim]")
        raise typer.Exit(1)
    run_interactive()


def _version_callback(value: bool):
    if value:
        p = ui.get_palette()
        console.print(f"hubctl [black on {p['primary']}] v{__version__} [/]  [{p['muted']}]tema:{ui.get_effective_theme_name()}[/]")
        raise typer.Exit(0)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        help="Mostra versão e sai",
        callback=_version_callback,
        is_eager=True,
    ),
):
    if ctx.invoked_subcommand is None:
        if any(x in sys.argv for x in ("--help", "-h", "--install-completion", "--show-completion", "-i", "--version", "-v")):
            return
        try:
            from .interactive import run_interactive
            run_interactive()
        except ImportError:
            console.print("[dim]Dica: rode 'hubctl --help' para ver comandos ou 'hubctl interactive' para modo interativo[/dim]")
            console.print(ctx.get_help())
        raise typer.Exit(0)
