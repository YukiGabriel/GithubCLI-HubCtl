import requests
from typing import Any

API_BASE = "https://api.github.com"

class GitHubClient:
    def __init__(self, token: str):
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def _get(self, path: str, params: dict | None = None) -> Any:
        r = self.session.get(f"{API_BASE}{path}", params=params)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, json: dict | None = None) -> Any:
        r = self.session.post(f"{API_BASE}{path}", json=json)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str) -> None:
        r = self.session.delete(f"{API_BASE}{path}")
        r.raise_for_status()

    def _patch(self, path: str, json: dict | None = None) -> Any:
        r = self.session.patch(f"{API_BASE}{path}", json=json)
        r.raise_for_status()
        return r.json()

    def _put(self, path: str) -> Any:
        r = self.session.put(f"{API_BASE}{path}")
        r.raise_for_status()
        return r.json() if r.text else None

    # Repos
    def list_repos(self, limit: int = 30, visibility: str = "all", sort: str = "updated"):
        # visibility: all, public, private
        return self._get("/user/repos", params={"per_page": limit, "visibility": visibility, "sort": sort})

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

    def star_repo(self, full_name: str):
        return self._put(f"/user/starred/{full_name}")

    def unstar_repo(self, full_name: str):
        self._delete(f"/user/starred/{full_name}")

    def check_starred(self, full_name: str) -> bool:
        r = self.session.get(f"{API_BASE}/user/starred/{full_name}")
        if r.status_code == 204:
            return True
        if r.status_code == 404:
            return False
        r.raise_for_status()
        return False

    def update_repo(self, full_name: str, **kwargs):
        # kwargs: description, private, homepage, etc
        return self._patch(f"/repos/{full_name}", json=kwargs)

    def search_repos(self, query: str, limit: int = 20, sort: str = "stars"):
        return self._get("/search/repositories", params={"q": query, "per_page": limit, "sort": sort})

    # Issues
    def list_issues(self, full_name: str, state: str = "open", limit: int = 20):
        return self._get(f"/repos/{full_name}/issues", params={"state": state, "per_page": limit})

    def get_issue(self, full_name: str, number: int):
        return self._get(f"/repos/{full_name}/issues/{number}")

    def create_issue(self, full_name: str, title: str, body: str = "", labels: list | None = None):
        data: dict = {"title": title, "body": body}
        if labels:
            data["labels"] = labels
        return self._post(f"/repos/{full_name}/issues", json=data)

    def close_issue(self, full_name: str, number: int):
        return self._patch(f"/repos/{full_name}/issues/{number}", json={"state": "closed"})

    # PRs
    def list_prs(self, full_name: str, state: str = "open", limit: int = 20):
        return self._get(f"/repos/{full_name}/pulls", params={"state": state, "per_page": limit})

    def get_pr(self, full_name: str, number: int):
        return self._get(f"/repos/{full_name}/pulls/{number}")

    def create_pr(self, full_name: str, title: str, head: str, base: str = "main", body: str = "", draft: bool = False):
        return self._post(f"/repos/{full_name}/pulls", json={
            "title": title, "head": head, "base": base, "body": body, "draft": draft
        })

    def get_user(self):
        return self._get("/user")

    def list_starred(self, limit: int = 20):
        return self._get("/user/starred", params={"per_page": limit})
