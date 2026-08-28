import base64
import time
from typing import Any

import requests

API_BASE = "https://api.github.com"


def _friendly_rate_limit_error(resp: requests.Response) -> str:
    remaining = resp.headers.get("X-RateLimit-Remaining", "?")
    reset = resp.headers.get("X-RateLimit-Reset")
    reset_str = ""
    if reset:
        try:
            ts = int(reset)
            wait = max(0, ts - int(time.time()))
            reset_str = f" | reset em {wait//60}m {wait%60}s (epoch {ts})"
        except Exception:
            pass
    limit = resp.headers.get("X-RateLimit-Limit", "?")
    return f"Rate limit excedido ({remaining}/{limit} restantes{reset_str}). Tente novamente depois ou use token com mais limite."


class GitHubClient:
    def __init__(self, token: str):
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def _check_rate_limit(self, resp: requests.Response):
        if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
            raise requests.HTTPError(_friendly_rate_limit_error(resp), response=resp)
        # também 429
        if resp.status_code == 429:
            raise requests.HTTPError(_friendly_rate_limit_error(resp), response=resp)

    def _get(self, path: str, params: dict | None = None) -> Any:
        r = self.session.get(f"{API_BASE}{path}", params=params, timeout=15)
        self._check_rate_limit(r)
        r.raise_for_status()
        return r.json()

    def _get_paginated(self, path: str, params: dict | None = None, limit: int = 30) -> list:
        """Busca paginada até `limit` itens (per_page max 100)."""
        params = dict(params or {})
        per_page = min(limit, 100)
        params["per_page"] = per_page
        collected: list = []
        page = 1
        while len(collected) < limit:
            params["page"] = page
            r = self.session.get(f"{API_BASE}{path}", params=params, timeout=15)
            self._check_rate_limit(r)
            r.raise_for_status()
            data = r.json()
            # search retorna dict com items, outros retornam list
            if isinstance(data, dict) and "items" in data:
                items = data["items"]
                collected.extend(items)
                # search tem total_count, mas paginamos igual
                if len(items) < per_page:
                    break
                # se já pegou total_count ou limit
                if len(collected) >= data.get("total_count", limit):
                    break
            elif isinstance(data, list):
                collected.extend(data)
                if len(data) < per_page:
                    break
            else:
                # dict único (ex: get_repo) — não paginado
                return data
            if len(collected) >= limit:
                break
            # verifica Link header p/ next
            link = r.headers.get("Link", "")
            if 'rel="next"' not in link and len(data) < per_page:
                break
            page += 1
        return collected[:limit]

    def _post(self, path: str, json: dict | None = None) -> Any:
        r = self.session.post(f"{API_BASE}{path}", json=json, timeout=15)
        self._check_rate_limit(r)
        r.raise_for_status()
        return r.json() if r.text else {}

    def _delete(self, path: str) -> None:
        r = self.session.delete(f"{API_BASE}{path}", timeout=15)
        self._check_rate_limit(r)
        r.raise_for_status()

    def _patch(self, path: str, json: dict | None = None) -> Any:
        r = self.session.patch(f"{API_BASE}{path}", json=json, timeout=15)
        self._check_rate_limit(r)
        r.raise_for_status()
        return r.json()

    def _put(self, path: str, json: dict | None = None) -> Any:
        r = self.session.put(f"{API_BASE}{path}", json=json, timeout=15)
        self._check_rate_limit(r)
        r.raise_for_status()
        return r.json() if r.text else None

    # Repos
    def list_repos(self, limit: int = 30, visibility: str = "all", sort: str = "updated"):
        if limit <= 100:
            return self._get("/user/repos", params={"per_page": limit, "visibility": visibility, "sort": sort})
        return self._get_paginated("/user/repos", params={"visibility": visibility, "sort": sort}, limit=limit)

    def get_repo(self, full_name: str):
        return self._get(f"/repos/{full_name}")

    def create_repo(self, name: str, private: bool = False, description: str = "", auto_init: bool = False):
        return self._post("/user/repos", json={
            "name": name,
            "private": private,
            "description": description,
            "auto_init": auto_init,
        })

    def delete_repo(self, full_name: str):
        self._delete(f"/repos/{full_name}")

    def fork_repo(self, full_name: str):
        return self._post(f"/repos/{full_name}/forks")

    def sync_fork(self, full_name: str, branch: str = "main"):
        """Sync fork com upstream — POST /repos/{fork}/merge-upstream"""
        return self._post(f"/repos/{full_name}/merge-upstream", json={"branch": branch})

    def star_repo(self, full_name: str):
        return self._put(f"/user/starred/{full_name}")

    def unstar_repo(self, full_name: str):
        self._delete(f"/user/starred/{full_name}")

    def check_starred(self, full_name: str) -> bool:
        r = self.session.get(f"{API_BASE}/user/starred/{full_name}", timeout=15)
        if r.status_code == 204:
            return True
        if r.status_code == 404:
            return False
        self._check_rate_limit(r)
        r.raise_for_status()
        return False

    def update_repo(self, full_name: str, **kwargs):
        return self._patch(f"/repos/{full_name}", json=kwargs)

    def search_repos(self, query: str, limit: int = 20, sort: str = "stars"):
        # search sempre retorna dict; usamos paginação se limit>100 mas normalmente <=20
        if limit <= 100:
            return self._get("/search/repositories", params={"q": query, "per_page": limit, "sort": sort})
        # paginado
        items = self._get_paginated("/search/repositories", params={"q": query, "sort": sort}, limit=limit)
        return {"items": items, "total_count": len(items), "incomplete_results": False}

    def get_readme(self, full_name: str) -> str | None:
        try:
            r = self.session.get(
                f"{API_BASE}/repos/{full_name}/readme",
                headers={"Accept": "application/vnd.github.raw"},
                timeout=15,
            )
            if r.status_code == 404:
                return None
            self._check_rate_limit(r)
            ctype = r.headers.get("Content-Type", "")
            if "application/json" in ctype:
                data = r.json()
                if data.get("encoding") == "base64" and "content" in data:
                    return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                return None
            r.raise_for_status()
            return r.text
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return None
            return None
        except Exception:
            return None

    # Issues
    def list_issues(self, full_name: str, state: str = "open", limit: int = 20):
        if limit <= 100:
            return self._get(f"/repos/{full_name}/issues", params={"state": state, "per_page": limit})
        return self._get_paginated(f"/repos/{full_name}/issues", params={"state": state}, limit=limit)

    def get_issue(self, full_name: str, number: int):
        return self._get(f"/repos/{full_name}/issues/{number}")

    def create_issue(self, full_name: str, title: str, body: str = "", labels: list | None = None):
        data: dict = {"title": title, "body": body}
        if labels:
            data["labels"] = labels
        return self._post(f"/repos/{full_name}/issues", json=data)

    def close_issue(self, full_name: str, number: int):
        return self._patch(f"/repos/{full_name}/issues/{number}", json={"state": "closed"})

    def comment_issue(self, full_name: str, number: int, body: str):
        return self._post(f"/repos/{full_name}/issues/{number}/comments", json={"body": body})

    def list_comments(self, full_name: str, number: int, limit: int = 30):
        if limit <= 100:
            return self._get(f"/repos/{full_name}/issues/{number}/comments", params={"per_page": limit})
        return self._get_paginated(f"/repos/{full_name}/issues/{number}/comments", limit=limit)

    # PRs
    def list_prs(self, full_name: str, state: str = "open", limit: int = 20):
        if limit <= 100:
            return self._get(f"/repos/{full_name}/pulls", params={"state": state, "per_page": limit})
        return self._get_paginated(f"/repos/{full_name}/pulls", params={"state": state}, limit=limit)

    def get_pr(self, full_name: str, number: int):
        return self._get(f"/repos/{full_name}/pulls/{number}")

    def create_pr(self, full_name: str, title: str, head: str, base: str = "main", body: str = "", draft: bool = False):
        return self._post(f"/repos/{full_name}/pulls", json={
            "title": title, "head": head, "base": base, "body": body, "draft": draft
        })

    def merge_pr(self, full_name: str, number: int, commit_title: str | None = None, commit_message: str | None = None, merge_method: str = "merge"):
        data: dict = {"merge_method": merge_method}
        if commit_title:
            data["commit_title"] = commit_title
        if commit_message:
            data["commit_message"] = commit_message
        return self._put(f"/repos/{full_name}/pulls/{number}/merge", json=data)

    def get_pr_diff(self, full_name: str, number: int) -> str | None:
        r = self.session.get(f"{API_BASE}/repos/{full_name}/pulls/{number}", headers={"Accept": "application/vnd.github.diff"}, timeout=15)
        self._check_rate_limit(r)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.text

    def get_pr_files(self, full_name: str, number: int):
        return self._get(f"/repos/{full_name}/pulls/{number}/files", params={"per_page": 100})

    def get_user(self):
        return self._get("/user")

    def get_user_by_username(self, username: str):
        return self._get(f"/users/{username}")

    def list_user_repos(self, username: str, limit: int = 20, sort: str = "updated", type: str = "owner"):
        # type: all, owner, member
        if limit <= 100:
            return self._get(f"/users/{username}/repos", params={"per_page": limit, "sort": sort, "type": type})
        return self._get_paginated(f"/users/{username}/repos", params={"sort": sort, "type": type}, limit=limit)

    def list_user_starred_public(self, username: str, limit: int = 20):
        if limit <= 100:
            return self._get(f"/users/{username}/starred", params={"per_page": limit})
        return self._get_paginated(f"/users/{username}/starred", limit=limit)

    def list_user_orgs(self, username: str):
        return self._get(f"/users/{username}/orgs")

    def list_starred(self, limit: int = 20):
        if limit <= 100:
            return self._get("/user/starred", params={"per_page": limit})
        return self._get_paginated("/user/starred", limit=limit)

    def get_rate_limit(self):
        return self._get("/rate_limit")


def fetch_readme_public(full_name: str, token: str | None = None) -> str | None:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        h_raw = dict(headers)
        h_raw["Accept"] = "application/vnd.github.raw"
        r = requests.get(f"{API_BASE}/repos/{full_name}/readme", headers=h_raw, timeout=15)
        if r.status_code == 404:
            return None
        if r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0":
            return None
        ctype = r.headers.get("Content-Type", "")
        if "application/json" in ctype:
            data = r.json()
            if data.get("encoding") == "base64" and "content" in data:
                return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            return None
        r.raise_for_status()
        return r.text
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        return None
    except Exception:
        return None


def fetch_user_public(username: str, token: str | None = None) -> dict | None:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(f"{API_BASE}/users/{username}", headers=headers, timeout=15)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def fetch_user_repos_public(username: str, limit: int = 20, sort: str = "updated", token: str | None = None) -> list:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        # paginação simples até limit
        collected = []
        per_page = min(limit, 100)
        page = 1
        while len(collected) < limit:
            r = requests.get(f"{API_BASE}/users/{username}/repos", headers=headers, params={"per_page": per_page, "page": page, "sort": sort, "type": "owner"}, timeout=15)
            if r.status_code == 404:
                break
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list) or not data:
                break
            collected.extend(data)
            if len(data) < per_page:
                break
            page += 1
        return collected[:limit]
    except Exception:
        return []
