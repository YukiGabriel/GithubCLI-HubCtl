import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import requests
import typer
from rich.prompt import Confirm, Prompt

from . import ui
from .config import CONFIG_FILE, delete_token, get_theme, get_token, require_token, save_theme, save_token
from .github import GitHubClient, fetch_readme_public

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

app.add_typer(auth_app, name="auth")
app.add_typer(repo_app, name="repo")
app.add_typer(issue_app, name="issue")
app.add_typer(pr_app, name="pr")
app.add_typer(config_app, name="config")

console = ui.console

# ---------- AUTH ----------
@auth_app.command("login")
def auth_login(token: Optional[str] = typer.Option(None, "--token", "-t", help="Seu Personal Access Token")):
    """Salva seu token do GitHub"""
    ui.print_banner()
    if not token:
        console.print(f"[dim]Crie seu token em: https://github.com/settings/tokens[/dim]\n")
        token = Prompt.ask("🔑 Cole seu GitHub Token", password=True)
    if not token:
        ui.error("Token vazio!", title="Falha")
        raise typer.Exit(1)
    try:
        client = GitHubClient(token)
        with console.status("[bold #00D9FF]Validando token...[/]", spinner="dots12"):
            user = client.get_user()
        save_token(token)
        ui.success(f"Autenticado como [bold]{user['login']}[/]!", title="✓ Bem-vindo")
        console.print(f"[dim]Token salvo em {CONFIG_FILE}[/dim]")
        console.print(ui.auth_panel(user))
    except requests.HTTPError as e:
        ui.error(f"Erro ao validar token: {e}", title="Token inválido")
        if e.response is not None:
            console.print(f"[dim]{e.response.text[:400]}[/dim]")
        raise typer.Exit(1)

@auth_app.command("logout")
def auth_logout(force: bool = typer.Option(False, "--yes", "-y", help="Não pedir confirmação")):
    """Remove o token salvo (logout)"""
    token = get_token()
    env_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token and not CONFIG_FILE.exists():
        ui.warning("Você já não está logado (sem token salvo).", title="Aviso")
        if env_token:
            console.print("[dim]Mas existe GITHUB_TOKEN/GH_TOKEN no env — remova do seu shell.[/dim]")
        return
    if not force:
        if not Confirm.ask(f"[yellow]Remover token salvo em {CONFIG_FILE}?[/yellow]"):
            console.print("[dim]Cancelado[/dim]")
            raise typer.Exit(0)
    if delete_token():
        ui.success(f"Token removido de {CONFIG_FILE}", title="✓ Logout")
    else:
        ui.warning("Nenhum token salvo encontrado.", title="Aviso")
    if env_token:
        console.print("[yellow]⚠ GITHUB_TOKEN/GH_TOKEN ainda está no env — unset no shell se quiser logout completo.[/yellow]")

@auth_app.command("status")
def auth_status():
    """Mostra status da autenticação"""
    token = get_token()
    if not token:
        ui.error("Não autenticado. Rode 'hubctl auth login' ou defina GITHUB_TOKEN", title="Offline")
        raise typer.Exit(1)
    try:
        client = GitHubClient(token)
        with console.status("[bold #00D9FF]Buscando seu perfil...[/]", spinner="dots12"):
            user = client.get_user()
        console.print(ui.auth_panel(user))
        # mostra de onde veio o token
        src = "env GITHUB_TOKEN" if os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") else str(CONFIG_FILE)
        console.print(f"[dim]Token origem: {src}[/dim]")
    except Exception as e:
        ui.error(str(e), title="Erro")
        raise typer.Exit(1)

# ---------- REPO ----------
@repo_app.command("list")
def repo_list(
    limit: int = typer.Option(20, "--limit", "-n", help="Qtd de repos"),
    visibility: str = typer.Option("all", "--visibility", help="all/public/private"),
    token: Optional[str] = typer.Option(None, "--token", help="Token (opcional)"),
):
    """Lista seus repositórios"""
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e), title="Auth necessário")
        raise typer.Exit(1)
    client = GitHubClient(t)
    try:
        with console.status(f"[bold #00D9FF]Buscando repos ({visibility})...[/]", spinner="dots12"):
            repos = client.list_repos(limit=limit, visibility=visibility)
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)

    if not repos:
        ui.warning("Nenhum repositório encontrado.", title="Vazio")
        return

    console.print(ui.repo_table(f"Seus Repositórios • {visibility} • {len(repos)}", repos))
    console.print(f"[dim]Dica: hubctl repo view usuario/repo  •  hubctl interactive para navegar com setas[/dim]")

@repo_app.command("view")
def repo_view(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Mostra detalhes de um repositório"""
    # view permite anônimo para público
    resolved = get_token(token)
    try:
        if resolved:
            client = GitHubClient(resolved)
            with console.status(f"[bold #00D9FF]Buscando {full_name}...[/]", spinner="dots12"):
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

    console.print(ui.detail_panel(r))
    # extras bonitos
    extra = ""
    if r.get("license"):
        extra += f"[dim]📄 Licença: {r['license'].get('spdx_id') or r['license'].get('name')}[/]  "
    if r.get("homepage"):
        extra += f"[dim]🏠 {r['homepage']}[/]"
    if extra:
        console.print(extra)

    # README.md bonito e organizado (em vez de só descrição)
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
    console.print(f"\n[dim]Clone: [cyan]hubctl repo clone {full_name}[/]  •  Fork: [cyan]hubctl repo fork {full_name}[/]  •  Star: [cyan]hubctl repo star {full_name}[/][/dim]")

@repo_app.command("create")
def repo_create(
    name: str = typer.Argument(..., help="Nome do novo repo"),
    private: bool = typer.Option(False, "--private", help="Criar como privado"),
    description: str = typer.Option("", "--description", "-d", help="Descrição"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Cria um novo repositório"""
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    client = GitHubClient(t)
    try:
        with console.status(f"[bold #B537F2]Criando {name}...[/]", spinner="dots12"):
            r = client.create_repo(name, private=private, description=description)
        ui.success(f"Repo criado: [bold]{r['full_name']}[/]\n[link={r['html_url']}]🔗 {r['html_url']}[/]", title="✓ Criado")
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
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)

    if not yes:
        console.print(ui.detail_panel({"full_name": full_name, "private": True, "description": "⚠️  AÇÃO IRREVERSÍVEL", "stargazers_count": 0, "forks_count": 0, "watchers_count": 0, "open_issues_count": 0, "language": "—", "created_at": "0000-00-00T00:00:00Z", "updated_at": "0000-00-00T00:00:00Z", "html_url": f"https://github.com/{full_name}", "topics": []}) if False else "")
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
        with console.status(f"[bold #FF006E]Deletando {full_name}...[/]", spinner="dots12"):
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
            with console.status(f"[bold #00D9FF]Buscando {full_name}...[/]", spinner="dots12"):
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

    if ssh:
        url = ssh_url or f"git@github.com:{full_name}.git"
    else:
        url = clone_url or f"https://github.com/{full_name}.git"
        if is_private and resolved_token:
            if url.startswith("https://"):
                url = url.replace("https://", f"https://oauth2:{resolved_token}@")

    dest = Path(directory) if directory else Path(full_name.split("/")[-1])
    if dest.exists():
        ui.error(f"Destino '{dest}' já existe")
        raise typer.Exit(1)

    safe_url = url.replace(resolved_token, "***") if resolved_token and resolved_token in url else url
    console.print(f"[bold #00D9FF]⬇ Clonando [bold]{full_name}[/] {'(SSH)' if ssh else '(HTTPS)'} → [bold]{dest}[/][/]")
    console.print(f"[dim]{safe_url}[/]")

    result = subprocess.run(["git", "clone", url, str(dest)])
    if result.returncode != 0:
        ui.error(f"git clone falhou (código {result.returncode})")
        raise typer.Exit(result.returncode)

    ui.success(f"Clonado em [bold]{dest.resolve()}[/]", title="✓ Clone ok")
    console.print(f"[dim]cd {dest} && code .[/dim]")

@repo_app.command("fork")
def repo_fork(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Faz fork de um repositório para sua conta"""
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    client = GitHubClient(t)
    try:
        with console.status(f"[bold #B537F2]Fazendo fork de {full_name}...[/]", spinner="dots12"):
            r = client.fork_repo(full_name)
        ui.success(f"Fork criado! [bold]{r['full_name']}[/]\n[link={r['html_url']}]🔗 {r['html_url']}[/]", title="🍴 Fork ok")
        console.print(f"[dim]Clone depois: hubctl repo clone {r['full_name']}[/dim]")
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
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    client = GitHubClient(t)
    try:
        with console.status(f"[bold #FFD23F]Dando star em {full_name}...[/]", spinner="dots12"):
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
        with console.status(f"[bold #00D9FF]Atualizando {full_name}...[/]", spinner="dots12"):
            r = client.update_repo(full_name, **data)
        ui.success(f"Atualizado [bold]{r['full_name']}[/]\n[dim]{r.get('description') or ''}[/]", title="✓ Editado")
        console.print(f"[dim]🔗 {r['html_url']}[/dim]")
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
):
    """Busca repositórios no GitHub (search) — agora com filtro por usuário e opção de clonar"""
    # monta query efetiva: user:xxx + termos
    effective_query = (query.strip() if query else "")
    if user and user.strip():
        user = user.strip()
        effective_query = f"user:{user} {effective_query}".strip()
    if not effective_query:
        ui.error("Informe um termo de busca ou use --user para listar repos de um usuário. Ex: hubctl repo search --user octocat --limit 5", title="Busca vazia")
        raise typer.Exit(1)
    # search funciona anônimo mas melhor autenticado (rate limit maior)
    resolved = get_token(token)
    try:
        if resolved:
            client = GitHubClient(resolved)
            with console.status(f"[bold #00D9FF]Buscando '{effective_query}'...[/]", spinner="dots12"):
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
    if not items:
        ui.warning(f"Nenhum resultado para '{effective_query}'", title="Vazio")
        return

    # transforma items no formato de repo_table
    # search já traz stargazers_count, etc mas falta topics? ok
    console.print(ui.repo_table(f"Busca: '{effective_query}' • {total} resultados (mostrando {len(items)})", items))
    console.print(f"[dim]Dica: hubctl repo view usuario/repo  •  hubctl repo clone usuario/repo  •  use --user para filtrar por pessoa[/dim]")

# ---------- ISSUE ----------
@issue_app.command("list")
def issue_list(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    state: str = typer.Option("open", "--state", help="open/closed/all"),
    limit: int = typer.Option(20, "--limit", "-n"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Lista issues de um repo"""
    try:
        t = require_token(token)
    except ValueError:
        # tenta anônimo pra público
        t = get_token(token)
        if not t:
            # tenta anônimo
            try:
                with console.status(f"[dim]Buscando issues de {full_name}...[/]", spinner="dots12"):
                    resp = requests.get(f"https://api.github.com/repos/{full_name}/issues", params={"state": state, "per_page": limit}, headers={"Accept": "application/vnd.github+json"})
                    resp.raise_for_status()
                    issues = resp.json()
                    issues = [i for i in issues if "pull_request" not in i]
                    if not issues:
                        ui.warning("Nenhuma issue encontrada", title="Vazio")
                        return
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
        with console.status(f"[bold #00D9FF]Buscando issues de {full_name}...[/]", spinner="dots12"):
            issues = client.list_issues(full_name, state=state, limit=limit)
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)

    issues = [i for i in issues if "pull_request" not in i]

    if not issues:
        ui.warning("Nenhuma issue encontrada", title="Vazio")
        return

    console.print(ui.issue_table(f"Issues • {full_name} • {state}", issues))
    console.print(f"[dim]Dica: hubctl issue view {full_name} <num>  •  hubctl issue create {full_name}[/dim]")

@issue_app.command("view")
def issue_view(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    number: int = typer.Argument(..., help="número da issue"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Mostra detalhes de uma issue"""
    resolved = get_token(token)
    try:
        if resolved:
            client = GitHubClient(resolved)
            with console.status(f"[bold #00D9FF]Buscando issue #{number}...[/]", spinner="dots12"):
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

    state = issue["state"]
    color = ui.THEME["success"] if state == "open" else ui.THEME["error"]
    labels = "  ".join(f"[bold #B537F2]#{l['name']}[/]" for l in issue.get("labels", [])) or "[dim]sem labels[/dim]"
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
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    # junta labels
    all_labels = []
    if label:
        all_labels.append(label)
    if labels:
        all_labels.extend([s.strip() for s in labels.split(",") if s.strip()])
    # body opcional - mantém vazio se não passar (não força prompt em modo não-interativo)
    if not body:
        try:
            # só prompta se estiver em TTY
            import sys
            if sys.stdin.isatty():
                body = Prompt.ask("📝 Descrição (opcional)", default="") or ""
        except Exception:
            body = ""

    client = GitHubClient(t)
    try:
        with console.status("[bold #B537F2]Criando issue...[/]", spinner="dots12"):
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
    try:
        t = require_token(token)
    except ValueError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    if not Confirm.ask(f"Fechar issue [bold]#{number}[/] em {full_name}?"):
        console.print("[dim]Cancelado[/dim]")
        raise typer.Exit(0)
    client = GitHubClient(t)
    try:
        with console.status(f"[bold #FF006E]Fechando #{number}...[/]", spinner="dots12"):
            issue = client.close_issue(full_name, number)
        ui.success(f"Issue #{issue['number']} fechada", title="✓ Fechada")
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)

# ---------- PR ----------
@pr_app.command("list")
def pr_list(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    state: str = typer.Option("open", "--state", help="open/closed/all"),
    limit: int = typer.Option(20, "--limit", "-n"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Lista PRs de um repo"""
    resolved = get_token(token)
    try:
        if resolved:
            client = GitHubClient(resolved)
            with console.status(f"[bold #B537F2]Buscando PRs de {full_name}...[/]", spinner="dots12"):
                prs = client.list_prs(full_name, state=state, limit=limit)
        else:
            with console.status(f"[dim]Buscando PRs de {full_name}...[/]", spinner="dots12"):
                resp = requests.get(f"https://api.github.com/repos/{full_name}/pulls", params={"state": state, "per_page": limit}, headers={"Accept": "application/vnd.github+json"})
                resp.raise_for_status()
                prs = resp.json()
    except Exception as e:
        ui.error(str(e))
        raise typer.Exit(1)

    if not prs:
        ui.warning("Nenhum PR encontrado", title="Vazio")
        return

    console.print(ui.pr_table(f"Pull Requests • {full_name} • {state}", prs))
    console.print(f"[dim]Dica: hubctl pr view {full_name} <num>[/dim]")

@pr_app.command("view")
def pr_view(
    full_name: str = typer.Argument(..., help="ex: usuario/repo"),
    number: int = typer.Argument(..., help="número do PR"),
    token: Optional[str] = typer.Option(None, "--token"),
):
    """Mostra detalhes de um PR"""
    resolved = get_token(token)
    try:
        if resolved:
            client = GitHubClient(resolved)
            with console.status(f"[bold #B537F2]Buscando PR #{number}...[/]", spinner="dots12"):
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

    state = pr["state"]
    merged = pr.get("merged", False)
    if merged:
        color = ui.THEME["secondary"]
        state_str = "MERGED"
    elif state == "open":
        color = ui.THEME["success"]
        state_str = "OPEN"
    else:
        color = ui.THEME["error"]
        state_str = state.upper()

    console.print(ui.info_panel(
        f"#{pr['number']} • {pr['title']}",
        f"[bold {color}]● {state_str}[/]  por [bold]{pr['user']['login']}[/]  em {pr['created_at'][:10]}\n"
        f"[bold #00D9FF]{pr['head']['ref']}[/] → [bold]{pr['base']['ref']}[/]  •  💬 {pr.get('comments',0)}  •  ✅ {pr.get('additions',0)}++ / ❌ {pr.get('deletions',0)}--  •  📄 {pr.get('changed_files',0)} arquivos\n\n"
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
        with console.status("[bold #B537F2]Criando PR...[/]", spinner="dots12"):
            pr = client.create_pr(full_name, title=title, head=head, base=base, body=body, draft=draft)
        ui.success(f"PR criado: [bold]#{pr['number']} {pr['title']}[/]\n[link={pr['html_url']}]{pr['html_url']}[/]  {'[dim](draft)[/]' if pr.get('draft') else ''}", title="🔀 PR criado")
    except requests.HTTPError as e:
        ui.error(f"Erro ao criar PR: {e}")
        if e.response is not None:
            console.print(f"[dim]{e.response.text}[/dim]")
        raise typer.Exit(1)

# ---------- CONFIG ----------
@config_app.command("theme")
def config_theme(
    theme: Optional[str] = typer.Argument(None, help="dark / light / auto (vazio mostra atual)"),
):
    """Configura tema (auto detecta claro/escuro). Use GHC_THEME env para override."""
    current = get_theme()
    effective = ui.get_effective_theme_name()
    if theme is None:
        # mostra status
        ui.print_banner()
        console.print(f"Tema preferido: [bold {ui.THEME['primary']}]{current}[/]  (efetivo: [bold]{effective}[/] - {'claro' if effective=='light' else 'escuro'})")
        console.print(f"[dim]Detectado via COLORFGBG={os.getenv('COLORFGBG','-')}  •  GHC_THEME={os.getenv('GHC_THEME','-')}[/dim]")
        console.print(f"[dim]Para mudar: hubctl config theme [dark|light|auto][/dim]")
        console.print(f"[dim]Ou: GHC_THEME=light hubctl repo list  (só pra essa sessão)[/dim]")
        # preview
        console.print("\n[bold]Preview:[/]")
        ui.success("Exemplo sucesso", title="Sucesso")
        ui.warning("Exemplo aviso", title="Aviso")
        ui.error("Exemplo erro", title="Erro")
        console.print(ui.detail_panel({"full_name":"demo/repo","private":False,"description":"Preview de repo para ver contraste","stargazers_count":123,"forks_count":10,"watchers_count":123,"open_issues_count":5,"language":"Python","created_at":"2024-01-01T00:00:00Z","updated_at":"2024-06-01T00:00:00Z","html_url":"https://github.com/demo/repo","topics":["cli","python"]}))
        return
    theme = theme.lower()
    if theme not in ("dark", "light", "auto"):
        ui.error("Tema deve ser dark, light ou auto", title="Inválido")
        raise typer.Exit(1)
    save_theme(theme)
    ui.reload_theme()
    new_effective = ui.get_effective_theme_name()
    ui.success(f"Tema salvo: [bold]{theme}[/]  (efetivo agora: {new_effective})", title="✓ Configurado")
    console.print(f"[dim]Reinicie o terminal ou rode hubctl novamente pra ver 100%[/dim]")
    # mostra preview
    ui.print_banner()

@config_app.command("show")
def config_show():
    """Mostra toda configuração salva"""
    from pathlib import Path
    import configparser
    ui.print_banner()
    console.print(f"[dim]Arquivo: {CONFIG_FILE}  (GHC_THEME env: {os.getenv('GHC_THEME','-')})[/dim]\n")
    if not CONFIG_FILE.exists():
        ui.warning("Nenhum config salvo ainda.", title="Vazio")
        return
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE)
    for sec in cfg.sections():
        console.print(f"[bold {ui.THEME['primary']}][{sec}][/]")
        for k, v in cfg[sec].items():
            # esconde token
            if k == "token":
                v = v[:6] + "***" + v[-4:] if len(v) > 10 else "***"
            console.print(f"  {k} = {v}")
    console.print(f"\n[dim]Tema efetivo: {ui.get_effective_theme_name()} ({'claro' if ui.get_effective_theme_name()=='light' else 'escuro'})[/dim]")

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
        console.print(f"hubctl [bold {ui.THEME['primary']}]{__version__}[/]")
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
    # Se rodar `hubctl` sem nenhum subcomando, entra no modo interativo
    # mas respeita --help e completion
    if ctx.invoked_subcommand is None:
        if any(x in sys.argv for x in ("--help", "-h", "--install-completion", "--show-completion", "-i", "--version", "-v")):
            return
        # também verifica se --help foi passado via contexto
        try:
            from .interactive import run_interactive
            run_interactive()
        except ImportError:
            console.print("[dim]Dica: rode 'hubctl --help' para ver comandos ou 'hubctl interactive' para modo interativo[/dim]")
            console.print(ctx.get_help())
        raise typer.Exit(0)
