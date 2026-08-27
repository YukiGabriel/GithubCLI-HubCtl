import os
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich.box import ROUNDED, HEAVY

console = Console()

# Temas
THEME_DARK = {
    "primary": "#00D9FF",
    "secondary": "#B537F2",
    "accent": "#FF6B35",
    "success": "#00F5A0",
    "warning": "#FFD23F",
    "error": "#FF006E",
    "muted": "#6C7293",
    "bg": "#1A1B26",
    "fg": "#E0E0E0",
    "name": "dark",
}

THEME_LIGHT = {
    # cores escuras que contrastam em fundo branco
    "primary": "#0070C9",
    "secondary": "#6A1B9A",
    "accent": "#D35400",
    "success": "#0A7A3A",
    "warning": "#8D6E00",
    "error": "#C62D42",
    "muted": "#5F6B7A",
    "bg": "#FFFFFF",
    "fg": "#1A1B26",
    "name": "light",
}

def _is_light_background() -> bool:
    """Detecta se o terminal tem fundo claro via COLORFGBG e outros sinais"""
    # COLORFGBG é o mais confiável: "fg;bg" e.g. "15;0" dark, "0;15" light
    c = os.getenv("COLORFGBG")
    if c:
        try:
            parts = c.strip().split(";")
            bg = parts[-1].strip()
            # valores comuns de bg claro
            light_bgs = {"7", "15", "11", "231", "255", "254", "253", "252", "230", "229", "15", "7;15", "0;15"}
            dark_bgs = {"0", "1", "2", "3", "4", "5", "6", "8", "16", "232", "233", "234", "235", "236"}
            # COLORFGBG pode ser "0;15" ou "15;0" - já pegamos último
            # também pode ser "15;0" -> bg 0 dark, "0;15" -> bg 15 light
            if bg in light_bgs:
                return True
            if bg in dark_bgs:
                return False
            # tenta interpretar como número
            try:
                n = int(bg)
                # 7,15 são claros, 0-6 escuros, 231-255 claros
                if n in (7, 15) or 231 <= n <= 255:
                    return True
                if 0 <= n <= 16:
                    return False
            except:
                pass
        except Exception:
            pass
    # fallback: verifica se TERM indica light
    term = os.getenv("TERM_PROGRAM", "") + os.getenv("TERM", "")
    if "light" in term.lower():
        return True
    # GNOME light theme?
    gtk = os.getenv("GTK_THEME", "")
    if "light" in gtk.lower():
        return True
    # padrão: assume dark (maioria dos devs)
    return False

def _get_preferred_theme() -> str:
    """Lê preferência via config.get_theme (suporta hubctl + legacy)"""
    try:
        from .config import get_theme
        return get_theme()
    except Exception:
        pass
    # fallback direto
    env = os.getenv("GHC_THEME") or os.getenv("HUBCTL_THEME")
    if env in ("dark", "light", "auto"):
        return env
    return "auto"

def get_effective_theme_name() -> str:
    pref = _get_preferred_theme()
    if pref == "dark":
        return "dark"
    if pref == "light":
        return "light"
    # auto
    return "light" if _is_light_background() else "dark"

# THEME ativo (dinâmico)
THEME_NAME = get_effective_theme_name()
THEME = THEME_DARK if THEME_NAME == "dark" else THEME_LIGHT

def reload_theme():
    """Recarrega tema (usado após save_theme)"""
    global THEME, THEME_NAME
    THEME_NAME = get_effective_theme_name()
    THEME = THEME_DARK if THEME_NAME == "dark" else THEME_LIGHT
    return THEME

# Banner adaptativo
def _banner_colors():
    if THEME_NAME == "light":
        return ("#0070C9", "#6A1B9A")
    return ("#00D9FF", "#B537F2")

def get_banner() -> str:
    c1, c2 = _banner_colors()
    return rf"""[bold {c1}]   ____ _ _   _           _       ____ _     ___[/]
[bold {c2}]  / ___(_) |_| |__  _   _| |__   / ___| |   |_ _|[/]
[bold {c1}] | |  _| | __| '_ \| | | | '_ \ | |   | |    | | [/]
[bold {c2}] | |_| | | |_| | | | |_| | |_) || |___| |___ | | [/]
[bold {c1}]  \____|_|\__|_| |_|\__,_|_.__/  \____|_____|___|[/]"""

BANNER_SUB = f"[dim {THEME['muted']}]gerencie seus repositórios com estilo • navegue com ↑/↓ • tema: {THEME_NAME} (auto)[/]"

def print_banner(clear: bool = False):
    if clear:
        console.clear()
    # recarrega tema caso env/config mudou
    reload_theme()
    banner = get_banner()
    sub = f"[dim {THEME['muted']}]gerencie seus repositórios com estilo • navegue com ↑/↓ • tema: {THEME_NAME} (auto)[/]"
    console.print(Align.center(Text.from_markup(banner)))
    console.print(Align.center(Text.from_markup(sub)))
    console.print()
    # dica se estiver em fundo claro mas usando tema dark (invisível)
    # não precisa, já é auto

def get_questionary_style():
    """Style do questionary que se adapta ao fundo"""
    from questionary import Style
    if THEME_NAME == "light":
        return Style([
            ("qmark", "fg:#0070C9 bold"),
            ("question", "bold fg:#1A1B26"),
            ("answer", "fg:#0A7A3A bold"),
            ("pointer", "fg:#6A1B9A bold"),
            ("highlighted", "fg:#0070C9 bold"),
            ("selected", "fg:#D35400"),
            ("separator", "fg:#5F6B7A"),
            ("instruction", "fg:#5F6B7A"),
            ("text", "fg:#1A1B26"),
            ("disabled", "fg:#8A8A8A italic"),
        ])
    else:
        return Style([
            ("qmark", "fg:#00D9FF bold"),
            ("question", "bold fg:#E0E0E0"),
            ("answer", "fg:#00F5A0 bold"),
            ("pointer", "fg:#B537F2 bold"),
            ("highlighted", "fg:#00D9FF bold"),
            ("selected", "fg:#FF6B35"),
            ("separator", "fg:#6C7293"),
            ("instruction", "fg:#6C7293"),
            ("text", "fg:#E0E0E0"),
            ("disabled", "fg:#858585 italic"),
        ])

def success(msg: str, title: str = "✓ Sucesso"):
    console.print(Panel(
        f"[{THEME['success']}]{msg}[/{THEME['success']}]",
        title=f"[bold {THEME['success']}]{title}[/]",
        border_style=THEME["success"],
        box=ROUNDED,
        padding=(0,1)
    ))

def error(msg: str, title: str = "✗ Erro"):
    console.print(Panel(
        f"[{THEME['error']}]{msg}[/{THEME['error']}]",
        title=f"[bold {THEME['error']}]{title}[/]",
        border_style=THEME["error"],
        box=ROUNDED,
    ))

def warning(msg: str, title: str = "⚠ Aviso"):
    console.print(Panel(
        f"[{THEME['warning']}]{msg}[/{THEME['warning']}]",
        title=f"[bold {THEME['warning']}]{title}[/]",
        border_style=THEME["warning"],
        box=ROUNDED,
    ))

def info_panel(title: str, content: str, border_color: str = None) -> Panel:
    if border_color is None:
        border_color = THEME["primary"]
    return Panel(
        content,
        title=f"[bold {border_color}]{title}[/]",
        border_style=border_color,
        box=ROUNDED,
        padding=(1,2)
    )

def repo_table(title: str, repos: list) -> Table:
    table = Table(
        title=f"[bold {THEME['primary']}]{title}[/]",
        title_justify="left",
        header_style=f"bold {THEME['primary']}",
        border_style=THEME["muted"],
        box=ROUNDED,
        row_styles=["", "dim"],
        show_lines=False,
        expand=False,
        show_edge=True,
    )
    table.add_column("Repo", style=f"bold {THEME['primary']}", no_wrap=False, overflow="fold", min_width=18, max_width=28)
    table.add_column("Vis", justify="center", width=9, no_wrap=True)
    table.add_column("⭐", justify="right", style=f"{THEME['warning']}", width=7, no_wrap=True)
    table.add_column("🍴", justify="right", style="dim", width=7, no_wrap=True)
    table.add_column("Desc", style="dim", overflow="fold", min_width=18, max_width=32)
    table.add_column("Data", style=f"{THEME['muted']}", width=10, no_wrap=True)
    for r in repos:
        name = f"[bold]{r['full_name']}[/]"
        if r.get("topics"):
            name += f"\n[dim {THEME['muted']}]{' '.join('#'+t for t in r['topics'][:3])}[/]"
        vis = f"[{THEME['error']}]🔒 privado[/]" if r["private"] else f"[{THEME['success']}]🌍 público[/]"
        desc = (r["description"] or "[dim]sem descrição[/dim]")[:60]
        table.add_row(
            name,
            vis,
            str(r["stargazers_count"]),
            str(r.get("forks_count","-")),
            desc,
            r["updated_at"][:10],
        )
    return table

def issue_table(title: str, issues: list) -> Table:
    table = Table(
        title=f"[bold {THEME['primary']}]{title}[/]",
        header_style=f"bold {THEME['primary']}",
        border_style=THEME["muted"],
        box=ROUNDED,
        expand=False,
    )
    table.add_column("#", style=f"bold {THEME['accent']}", width=7, no_wrap=True)
    table.add_column("Título", overflow="fold", min_width=30, max_width=50)
    table.add_column("Autor", style="dim", width=13, overflow="fold", no_wrap=False)
    table.add_column("Estado", justify="center", width=9, no_wrap=True)
    table.add_column("💬", justify="center", width=5, no_wrap=True)
    table.add_column("Criado", style=f"{THEME['muted']}", width=11, no_wrap=True)
    for i in issues:
        state = i["state"]
        if state == "open":
            state_str = f"[{THEME['success']}]● open[/]"
        elif state == "closed":
            state_str = f"[{THEME['error']}]● closed[/]"
        else:
            state_str = f"[{THEME['warning']}]● {state}[/]"
        labels = ""
        if i.get("labels"):
            labels = " " + " ".join(f"[dim {THEME['secondary']}]{l['name']}[/]" for l in i["labels"][:2])
        table.add_row(
            f"#{i['number']}",
            f"{i['title'][:55]}{labels}",
            i["user"]["login"],
            state_str,
            str(i["comments"]),
            i["created_at"][:10],
        )
    return table

def pr_table(title: str, prs: list) -> Table:
    table = Table(
        title=f"[bold {THEME['secondary']}]{title}[/]",
        header_style=f"bold {THEME['secondary']}",
        border_style=THEME["muted"],
        box=ROUNDED,
        expand=False,
    )
    table.add_column("#", style=f"bold {THEME['accent']}", width=7, no_wrap=True)
    table.add_column("Título", overflow="fold", min_width=25, max_width=45)
    table.add_column("Autor", style="dim", width=13, overflow="fold")
    table.add_column("Estado", justify="center", width=9, no_wrap=True)
    table.add_column("Branch", style=f"{THEME['primary']}", overflow="fold", min_width=15, max_width=25)
    for pr in prs:
        state = pr["state"]
        if state == "open":
            state_str = f"[{THEME['success']}]◉ open[/]"
        elif state == "closed":
            state_str = f"[{THEME['error']}]◎ closed[/]"
        elif state == "merged":
            state_str = f"[{THEME['secondary']}]◉ merged[/]"
        else:
            state_str = state
        table.add_row(
            f"#{pr['number']}",
            pr["title"][:50],
            pr["user"]["login"],
            state_str,
            f"[dim]{pr['head']['ref']}[/] → [bold]{pr['base']['ref']}[/]",
        )
    return table

def detail_panel(repo: dict) -> Panel:
    vis = f"[{THEME['error']}]🔒 PRIVADO[/]" if repo["private"] else f"[{THEME['success']}]🌍 PÚBLICO[/]"
    desc = repo["description"] or "[dim]Sem descrição[/dim]"
    topics = ""
    if repo.get("topics"):
        topics = "\n[bold]🏷️  Topics:[/] " + "  ".join(f"[{THEME['secondary']}]#{t}[/]" for t in repo["topics"])
    stats = (
        f"[bold {THEME['warning']}]⭐ {repo['stargazers_count']}[/]  "
        f"[dim]🍴 {repo['forks_count']}  👀 {repo['watchers_count']}  🐛 {repo.get('open_issues_count',0)}[/]\n"
        f"[bold]📝 {repo.get('language') or '—'}[/]  [dim]📅 {repo['created_at'][:10]}  🔄 {repo['updated_at'][:10]}[/]\n"
        f"[link={repo['html_url']}]🔗 {repo['html_url']}[/]{topics}"
    )
    return Panel(
        f"[bold {THEME['primary']}]{repo['full_name']}[/]  {vis}\n"
        f"[dim]{desc}[/]\n\n"
        f"{stats}",
        title=f"[bold]📦 Detalhes[/]",
        border_style=THEME["primary"],
        box=HEAVY,
        padding=(1,2)
    )

def auth_panel(user: dict) -> Panel:
    return Panel(
        f"[bold {THEME['success']}]● Logado como {user['login']}[/] [dim]({user.get('name') or ''})[/]\n"
        f"[dim]{user.get('bio') or ''}[/]\n\n"
        f"[bold]📦 Repos:[/] {user['public_repos']} públicos  •  [bold]👥 Seguidores:[/] {user['followers']}  •  [bold]Seguindo:[/] {user['following']}\n"
        f"[dim]📍 {user.get('location') or '—'}  •  🏢 {user.get('company') or '—'}  •  🔗 {user.get('blog') or user.get('html_url')}[/]",
        title=f"[bold {THEME['success']}]✓ Autenticado[/]",
        border_style=THEME["success"],
        box=ROUNDED,
        padding=(1,2)
    )
