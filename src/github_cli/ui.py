import os
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich.box import ROUNDED, HEAVY
from rich.markdown import Markdown
from rich import box

console = Console()

# ── Paletas premium adaptativas (inspirado no sweeo, elevado pro nível hubctl) ──
# Dark: neon cyan/purple pra fundo escuro — Light: azul profundo/púrpura escuro pra fundo branco
DARK = {
    "fg": "#E0E0E0",
    "fg_bold": "#FFFFFF",
    "muted": "#6C7293",
    "muted2": "#5C6370",
    "border": "#2A2F3A",
    "border_light": "#3A4150",
    "primary": "#00D9FF",
    "primary_dark": "#00B8E6",
    "secondary": "#B537F2",
    "accent": "#FF6B35",
    "success": "#00F5A0",
    "warning": "#FFD23F",
    "error": "#FF006E",
    "bg": "#1A1B26",
    "header": "bold #E0E0E0",
    "name": "dark",
}

LIGHT = {
    "fg": "#24292F",
    "fg_bold": "#0F111A",
    "muted": "#57606A",
    "muted2": "#8B949E",
    "border": "#D0D7DE",
    "border_light": "#AFB8C1",
    "primary": "#0070C9",
    "primary_dark": "#005A9E",
    "secondary": "#6A1B9A",
    "accent": "#D35400",
    "success": "#0A7A3A",
    "warning": "#8D6E00",
    "error": "#C62D42",
    "bg": "#FFFFFF",
    "header": "bold #24292F",
    "name": "light",
}

# Back-compat aliases
THEME_DARK = DARK
THEME_LIGHT = LIGHT


def _is_light_background() -> bool:
    """Detecta fundo claro via COLORFGBG e outros sinais (melhor que antes, igual sweeo melhorado)"""
    c = os.getenv("COLORFGBG", "")
    if c:
        try:
            parts = c.strip().split(";")
            bg = parts[-1].strip()
            # sweeo lógica: 7,15,253-255 = claro | 0,8,16,232-236 = escuro
            if bg in ("7", "15", "11", "231", "253", "254", "255", "252", "230", "229"):
                return True
            if bg in ("0", "8", "16", "232", "233", "234", "235", "236", "0"):
                return False
            try:
                n = int(bg)
                if n in (7, 15) or 231 <= n <= 255:
                    return True
                if 0 <= n <= 16 or 232 <= n <= 238:
                    return False
            except ValueError:
                pass
        except Exception:
            pass
    term = (os.getenv("TERM_PROGRAM", "") + os.getenv("TERM", "")).lower()
    if "light" in term:
        return True
    gtk = os.getenv("GTK_THEME", "").lower()
    if "light" in gtk:
        return True
    colorterm = os.getenv("COLORTERM", "").lower()
    # não confiável, deixa None fallback
    return False


def _get_preferred_theme() -> str:
    try:
        from .config import get_theme as _cfg_get
        return _cfg_get()
    except Exception:
        pass
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
    return "light" if _is_light_background() else "dark"


def is_dark_mode() -> bool:
    return get_effective_theme_name() == "dark"


def get_palette() -> dict:
    return DARK if is_dark_mode() else LIGHT


# THEME ativo dinâmico (compatibilidade)
THEME_NAME = get_effective_theme_name()
THEME = get_palette()


def get_banner_sub() -> str:
    p = get_palette()
    return f"gerencie seus repositórios com estilo • navegue com ↑/↓ • tema: {THEME_NAME} (auto)"


BANNER_SUB = get_banner_sub()


def reload_theme():
    global THEME, THEME_NAME, BANNER_SUB
    THEME_NAME = get_effective_theme_name()
    THEME = DARK if THEME_NAME == "dark" else LIGHT
    BANNER_SUB = get_banner_sub()
    return THEME


# ── Banner premium (Panel como sweeo, melhor ainda com version badge) ──
BANNER_ASCII = r"""
   ____ _ _   _           _       ____ _     ___
  / ___(_) |_| |__  _   _| |__   / ___| |   |_ _|
 | |  _| | __| '_ \| | | | '_ \ | |   | |    | |
 | |_| | | |_| | | | |_| | |_) || |___| |___ | |
  \____|_|\__|_| |_|\__,_|_.__/  \____|_____|___|
"""


def _banner_colors():
    p = get_palette()
    if p["name"] == "light":
        return (p["primary"], p["secondary"])
    return ("#00D9FF", "#B537F2")


def get_banner() -> str:
    c1, c2 = _banner_colors()
    return rf"""[bold {c1}]   ____ _ _   _           _       ____ _     ___[/]
[bold {c2}]  / ___(_) |_| |__  _   _| |__   / ___| |   |_ _|[/]
[bold {c1}] | |  _| | __| '_ \| | | | '_ \ | |   | |    | | [/]
[bold {c2}] | |_| | | |_| | | | |_| | |_) || |___| |___ | | [/]
[bold {c1}]  \____|_|\__|_| |_|\__,_|_.__/  \____|_____|___|[/]"""


def print_banner(clear: bool = False, version: str | None = None):
    if clear:
        console.clear()
    reload_theme()
    p = get_palette()
    try:
        from . import __version__ as _ver
    except Exception:
        _ver = version or "0.2.1"
    ver = version or _ver

    c1, c2 = _banner_colors()
    title = Text.from_markup(get_banner())
    subtitle = Text("Controle total do GitHub  •  TUI lindo  •  100% interativo", style=p["muted"], justify="center")
    ver_badge = Text(f"  v{ver}  ", style=f"black on {p['primary']} bold")
    hint = Text("Use ↑ ↓ para navegar  •  ESPAÇO para selecionar  •  ENTER para confirmar", style=f"{p['muted2']} italic", justify="center")
    sub = Text(get_banner_sub(), style=p["muted2"], justify="center")

    inner = Table.grid(padding=(0, 0))
    inner.add_column(justify="center")
    inner.add_row(Align.center(title))
    inner.add_row(subtitle)
    inner.add_row(Text(""))
    inner.add_row(Align.center(ver_badge))
    inner.add_row(Text(""))
    inner.add_row(sub)
    inner.add_row(Text(""))
    inner.add_row(Align.center(hint))

    panel = Panel(
        Align.center(inner),
        box=box.ROUNDED,
        border_style=p["primary"],
        padding=(1, 2),
        title=f"[bold {p['primary']}]◉ HubCtl[/]",
        title_align="left",
        subtitle=f"[{p['muted2']}]zero comandos para decorar[/]",
        subtitle_align="right",
    )
    console.print(panel)


def show_banner(version: str | None = None):
    print_banner(clear=False, version=version)


def show_header(title: str, subtitle: str = ""):
    p = get_palette()
    txt = Text(f" {title} ", style=f"black on {p['primary']} bold")
    if subtitle:
        txt.append(f"  {subtitle}", style=p["muted"])
    console.print(txt)
    console.print()


def divider():
    p = get_palette()
    console.print(f"[{p['border']}]" + "─" * console.width + "[/]")


def get_questionary_style():
    from questionary import Style
    p = get_palette()
    return Style([
        ("qmark", f"fg:{p['primary']} bold"),
        ("question", f"fg:{p['fg_bold']} bold"),
        ("answer", f"fg:{p['success']} bold"),
        ("pointer", f"fg:{p['primary']} bold"),
        ("highlighted", f"fg:{p['primary']} bold"),
        ("selected", f"fg:{p['fg_bold']}"),
        ("separator", f"fg:{p['muted2']}"),
        ("instruction", f"fg:{p['muted']} italic"),
        ("text", f"fg:{p['fg_bold']}"),
        ("disabled", f"fg:{p['muted2']} italic"),
    ])


# ── Panels de feedback (estilo sweeo, cores hubctl) ──
def success(msg: str, title: str = "✓ Sucesso"):
    p = get_palette()
    console.print(Panel(
        f"[bold {p['success']}]✓[/]  [{p['fg_bold']}]{msg}[/]",
        title=f"[bold {p['success']}]{title}[/]",
        border_style=p["success"],
        box=ROUNDED,
        padding=(0, 2),
    ))


def error(msg: str, title: str = "✗ Erro"):
    p = get_palette()
    console.print(Panel(
        f"[bold {p['error']}]✕[/]  [{p['fg_bold']}]{msg}[/]",
        title=f"[bold {p['error']}]{title}[/]",
        border_style=p["error"],
        box=ROUNDED,
        padding=(0, 2),
    ))


def warning(msg: str, title: str = "⚠ Aviso"):
    p = get_palette()
    console.print(Panel(
        f"[bold {p['warning']}]⚠[/]  [{p['fg_bold']}]{msg}[/]",
        title=f"[bold {p['warning']}]{title}[/]",
        border_style=p["warning"],
        box=ROUNDED,
        padding=(0, 2),
    ))


def info_panel(title: str, content: str, border_color: str | None = None) -> Panel:
    p = get_palette()
    if border_color is None:
        border_color = p["primary"]
    return Panel(
        content,
        title=f"[bold {border_color}]{title}[/]",
        border_style=border_color,
        box=ROUNDED,
        padding=(1, 2),
    )


def show_success(msg: str):
    success(msg)


def show_error(msg: str):
    error(msg)


def show_warning(msg: str):
    warning(msg)


def show_info(msg: str):
    p = get_palette()
    console.print(Panel(
        f"[{p['muted']}]○[/]  [{p['fg_bold']}]{msg}[/]",
        box=ROUNDED,
        border_style=p["border"],
        padding=(0, 2),
    ))

# ── Status bar premium (como sweeo main loop) ──
def make_status_bar(extra: str | None = None) -> Panel:
    """Barra de status com auth, tema e cwd - usada no menu interativo"""
    p = get_palette()
    from pathlib import Path as _P
    try:
        from .config import get_token as _gt
        token = _gt()
        is_logged = bool(token)
    except Exception:
        is_logged = False
    if is_logged:
        try:
            # tenta pegar login cache? sem request, só badge
            badge = f"[black on {p['success']}] ● LOGADO [/]"
        except Exception:
            badge = f"[black on {p['success']}] ● LOGADO [/]"
    else:
        badge = f"[{p['fg_bold']} on {p['border']}] ○ OFFLINE [/]"

    theme_pref = _get_preferred_theme()
    eff = get_effective_theme_name()
    theme_icon = "🌙" if eff == "dark" else "☀️"
    theme_badge = f"[{p['muted']}]{theme_icon} {theme_pref}→{eff}[/]"

    cwd_name = _P.cwd().name
    cwd_path = str(_P.cwd())
    if len(cwd_path) > 38:
        cwd_path = "…" + cwd_path[-37:]
    cwd_txt = f"[{p['fg_bold']}]{cwd_name}[/] [dim {p['muted']}]{cwd_path}[/]"

    status_table = Table.grid(expand=True)
    status_table.add_column(justify="left", ratio=1)
    status_table.add_column(justify="center", ratio=1)
    status_table.add_column(justify="right", ratio=1)
    mid = extra or theme_badge
    status_table.add_row(f"  {badge}  {cwd_txt}", Align.center(mid), f"{theme_badge}  ")

    return Panel(status_table, box=ROUNDED, border_style=p["border"], padding=(0, 1))


def repo_table(title: str, repos: list) -> Table:
    p = get_palette()
    table = Table(
        title=f"[bold {p['primary']}]{title}[/]",
        title_justify="left",
        header_style=p["header"],
        border_style=p["border"],
        box=ROUNDED,
        row_styles=["", "dim"],
        show_lines=False,
        expand=True,
        padding=(0, 1),
        show_edge=True,
    )
    table.add_column("Repositório", style=f"bold {p['fg_bold']}", ratio=2, overflow="fold", min_width=20)
    table.add_column("Vis", justify="center", width=11, no_wrap=True)
    table.add_column("⭐ Stars", justify="right", style=f"bold {p['warning']}", width=9)
    table.add_column("🍴 Forks", justify="right", style=p["muted"], width=9)
    table.add_column("Atualizado", style=p["muted"], width=12, justify="center")
    table.add_column("Descrição", style=p["muted"], ratio=2, overflow="fold", min_width=18)

    for r in repos:
        name = f"[bold {p['primary']}]{r['full_name']}[/]"
        if r.get("topics"):
            name += f"\n[dim {p['muted']}]{' '.join('#'+t for t in r['topics'][:2])}[/]"
        vis = f"[{p['error']}]🔒 privado[/]" if r["private"] else f"[{p['success']}]🌍 público[/]"
        # subtle star bar (0-5k scale)
        stars = r.get("stargazers_count", 0) or 0
        forks = r.get("forks_count", 0) or 0
        desc = (r.get("description") or "[dim]sem descrição[/dim]")[:72]
        # data com ícone
        updated = r.get("updated_at", "")[:10] if r.get("updated_at") else "—"
        table.add_row(
            name,
            vis,
            f"{stars:,}".replace(",", ".") if isinstance(stars, int) and stars > 999 else str(stars),
            str(forks),
            updated,
            desc,
        )
    return table


def issue_table(title: str, issues: list) -> Table:
    p = get_palette()
    table = Table(
        title=f"[bold {p['primary']}]{title}[/]",
        title_justify="left",
        header_style=p["header"],
        border_style=p["border"],
        box=ROUNDED,
        expand=True,
        padding=(0, 1),
    )
    table.add_column("#", style=f"bold {p['accent']}", width=7, justify="right")
    table.add_column("Título", overflow="fold", ratio=3)
    table.add_column("Autor", style=p["muted"], width=14, overflow="fold")
    table.add_column("Estado", justify="center", width=11)
    table.add_column("💬", justify="center", width=6)
    table.add_column("Criado", style=p["muted"], width=11, justify="center")
    for i in issues:
        state = i["state"]
        if state == "open":
            state_str = f"[{p['success']}]● open[/]"
        elif state == "closed":
            state_str = f"[{p['error']}]● closed[/]"
        else:
            state_str = f"[{p['warning']}]● {state}[/]"
        labels = ""
        if i.get("labels"):
            labels = " " + " ".join(f"[dim {p['secondary']}]{l['name']}[/]" for l in i["labels"][:2])
        table.add_row(
            f"#{i['number']}",
            f"[{p['fg_bold']}]{i['title'][:62]}[/]{labels}",
            i["user"]["login"],
            state_str,
            str(i["comments"]),
            i["created_at"][:10],
        )
    return table


def pr_table(title: str, prs: list) -> Table:
    p = get_palette()
    table = Table(
        title=f"[bold {p['secondary']}]{title}[/]",
        title_justify="left",
        header_style=p["header"],
        border_style=p["border"],
        box=ROUNDED,
        expand=True,
        padding=(0, 1),
    )
    table.add_column("#", style=f"bold {p['accent']}", width=7, justify="right")
    table.add_column("Título", overflow="fold", ratio=3)
    table.add_column("Autor", style=p["muted"], width=13, overflow="fold")
    table.add_column("Estado", justify="center", width=11)
    table.add_column("Branch", style=p["primary"], overflow="fold", ratio=2)
    for pr in prs:
        state = pr["state"]
        merged = pr.get("merged", False)
        if merged:
            state_str = f"[{p['secondary']}]◉ merged[/]"
        elif state == "open":
            state_str = f"[{p['success']}]◉ open[/]"
        elif state == "closed":
            state_str = f"[{p['error']}]◎ closed[/]"
        else:
            state_str = state
        table.add_row(
            f"#{pr['number']}",
            f"[{p['fg_bold']}]{pr['title'][:56]}[/]",
            pr["user"]["login"],
            state_str,
            f"[dim]{pr['head']['ref']}[/] → [bold {p['primary']}]{pr['base']['ref']}[/]",
        )
    return table


def detail_panel(repo: dict) -> Panel:
    p = get_palette()
    vis = f"[{p['error']}]🔒 PRIVADO[/]" if repo["private"] else f"[{p['success']}]🌍 PÚBLICO[/]"
    desc = repo.get("description") or "[dim]Sem descrição[/dim]"
    topics = ""
    if repo.get("topics"):
        topics = "\n[bold]🏷️  Topics:[/] " + "  ".join(f"[{p['secondary']}]#{t}[/]" for t in repo["topics"])
    stats = (
        f"[bold {p['warning']}]⭐ {repo['stargazers_count']:,}[/]  [dim]🍴 {repo['forks_count']}  👀 {repo['watchers_count']}  🐛 {repo.get('open_issues_count',0)}[/]\n"
        f"[bold]📝 {repo.get('language') or '—'}[/]  [dim]📅 {repo['created_at'][:10]}  🔄 {repo['updated_at'][:10]}[/]\n"
        f"[link={repo['html_url']}]🔗 {repo['html_url']}[/]{topics}"
    )
    return Panel(
        f"[bold {p['primary']}]{repo['full_name']}[/]  {vis}\n"
        f"[dim]{desc}[/]\n\n"
        f"{stats}",
        title=f"[bold {p['primary']}]📦 Detalhes[/]",
        border_style=p["primary"],
        box=HEAVY,
        padding=(1, 2),
    )


def auth_panel(user: dict) -> Panel:
    # wrapper para compatibilidade — agora delega ao premium
    return user_profile_panel(user, is_self=True)


def user_profile_panel(user: dict, is_self: bool = False, compact: bool = False) -> Panel:
    """Painel premium de perfil — usado para 'meu perfil' e para 'ver dono do repo'"""
    p = get_palette()
    login = user.get("login", "—")
    name = user.get("name") or ""
    bio = user.get("bio") or "[dim]Sem bio[/dim]"
    # header badge
    type_badge = f"[{p['primary']}]👤 USER[/]" if user.get("type") == "User" else f"[{p['secondary']}]🏢 ORG[/]"
    hire = user.get("hireable")
    hire_badge = f"  [{p['success']}]● hireable[/]" if hire else ""
    admin_badge = f"  [{p['warning']}]⚡ staff[/]" if user.get("site_admin") else ""
    title_icon = "✓ Você" if is_self else "👤 Perfil"
    border = p["success"] if is_self else p["primary"]
    # linha 1: login + nome
    header = f"[bold {p['primary']}]{login}[/]  {type_badge}{hire_badge}{admin_badge}"
    if name:
        header += f"  [dim]—[/]  [bold {p['fg_bold']}]{name}[/]"
    # stats grid inline
    followers = user.get("followers", 0)
    following = user.get("following", 0)
    repos = user.get("public_repos", 0)
    gists = user.get("public_gists", 0)
    # total_private_repos só vem quando autenticado e é dono
    priv = user.get("total_private_repos")
    priv_str = f"  [dim]•  🔒 {priv} privados[/]" if isinstance(priv, int) else ""
    # datas
    created = (user.get("created_at") or "")[:10]
    updated = (user.get("updated_at") or "")[:10]
    # contato
    loc = user.get("location") or "—"
    comp = user.get("company") or "—"
    blog = user.get("blog") or ""
    blog_str = blog if blog else user.get("html_url", "")
    twitter = user.get("twitter_username") or ""
    email = user.get("email") or ""
    # followers bar (escala log)
    followers_bar = ""
    if not compact:
        # barra visual simples 0-1000
        pct = min(100, (followers / 1000 * 100) if followers else 0)
        filled = int(pct / 100 * 12)
        followers_bar = f"  [{p['primary']}]{'█'*filled}[/][{p['border']}]{'░'*(12-filled)}[/] [{p['muted']}]{followers} seguidores[/]"

    body = (
        f"{header}\n"
        f"[dim]{bio}[/]\n\n"
        f"[bold {p['warning']}]⭐ {followers}[/] seguidores  [dim]•[/]  [bold]👥 {following}[/] seguindo  [dim]•[/]  [bold]📦 {repos}[/] públicos{priv_str}  [dim]•[/]  📝 {gists} gists{followers_bar}\n"
        f"[dim]📍 {loc}  •  🏢 {comp}  •  🔗 {blog_str}[/]\n"
    )
    if twitter:
        body += f"[dim]🐦 @{twitter}[/]  "
    if email:
        body += f"[dim]✉️  {email}[/]  "
    body += f"[dim]📅 desde {created}  •  🔄 {updated}[/]\n"
    body += f"[link={user.get('html_url')}]🔗 {user.get('html_url')}[/]"
    if compact:
        body = (
            f"[bold {p['primary']}]{login}[/]  [dim]{name}[/]  {type_badge}\n"
            f"[dim]{bio[:90]}[/]\n"
            f"[bold]{followers}[/] seguidores • [bold]{following}[/] seguindo • [bold]{repos}[/] repos  [dim]{loc}[/]"
        )
    return Panel(
        body,
        title=f"[bold {border}]{title_icon} — {login}[/]",
        border_style=border,
        box=HEAVY,
        padding=(1, 2),
    )


def user_summary_grid(user: dict):
    """Grid 3 colunas estilo sweeo make_summary_panel — para perfil"""
    p = get_palette()
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(justify="center", ratio=1)
    grid.add_column(justify="center", ratio=1)
    grid.add_column(justify="center", ratio=1)

    followers = user.get("followers", 0)
    following = user.get("following", 0)
    repos = user.get("public_repos", 0)

    left = Text(f"{repos}", style=f"bold {p['primary']}")
    left.append("\nrepos públicos", style=p["muted"])
    middle = Text(f"{followers}", style=f"bold {p['warning']}")
    middle.append("\nseguidores", style=p["muted"])
    right = Text(f"{following}", style=f"bold {p['fg_bold']}")
    right.append("\nseguindo", style=p["muted"])

    grid.add_row(
        Panel(Align.center(left), box=box.ROUNDED, border_style=p["border"], padding=(1, 2), title=f"[{p['muted2']}]📦[/]"),
        Panel(Align.center(middle), box=box.ROUNDED, border_style=p["primary"], padding=(1, 2), title=f"[{p['primary']}]👥[/]"),
        Panel(Align.center(right), box=box.ROUNDED, border_style=p["border"], padding=(1, 2), title=f"[{p['muted2']}]🔗[/]"),
    )
    return grid


def readme_panel(repo_full_name: str, markdown_text: str | None, max_chars: int = 12000) -> Panel:
    p = get_palette()
    if not markdown_text or not markdown_text.strip():
        return Panel(
            "[dim]📄 Sem README.md neste repositório[/dim]\n[dim]Crie um README.md na raiz para documentar seu projeto[/dim]",
            title=f"[bold {p['primary']}]📖 README — {repo_full_name}[/]",
            border_style=p["muted"],
            box=ROUNDED,
            padding=(1, 2),
        )
    truncated = False
    text = markdown_text
    if len(text) > max_chars:
        text = text[:max_chars].rsplit("\n", 1)[0]
        truncated = True
    code_theme = "monokai" if p["name"] == "dark" else "github-light"
    md = Markdown(text, code_theme=code_theme, hyperlinks=True, inline_code_theme=code_theme)
    title = f"[bold {p['primary']}]📖 README — {repo_full_name}[/]"
    if truncated:
        title += f" [dim](truncado em {max_chars} chars)[/]"
    return Panel(
        md,
        title=title,
        border_style=p["primary"],
        box=ROUNDED,
        padding=(1, 2),
    )
