"""Saving a private league's ESPN login (app/espn_login.py) with a fake Secret
Manager client: one secret per league, a new version per save, old versions
destroyed so a replaced login can't be read."""

import json
from types import SimpleNamespace

from google.api_core.exceptions import AlreadyExists, NotFound

import espn_login

LOGIN = {"espn_s2": "s2-value", "SWID": "{SWID}"}


class FakeSecrets:
    def __init__(self):
        self.secrets = {}  # name -> list of versions [{name, state, data}]
        self.calls = []

    def create_secret(self, request):
        name = f"{request['parent']}/secrets/{request['secret_id']}"
        if name in self.secrets:
            raise AlreadyExists("exists")
        self.secrets[name] = []
        self.labels = request["secret"]["labels"]

    def add_secret_version(self, request):
        versions = self.secrets[request["parent"]]
        version = {"name": f"{request['parent']}/versions/{len(versions) + 1}", "state": 1,
                   "data": request["payload"]["data"]}  # fmt: skip
        versions.append(version)
        return SimpleNamespace(name=version["name"])

    def list_secret_versions(self, request):
        return [
            SimpleNamespace(name=v["name"], state=v["state"])
            for v in self.secrets[request["parent"]]
        ]

    def destroy_secret_version(self, request):
        for versions in self.secrets.values():
            for v in versions:
                if v["name"] == request["name"]:
                    v["state"], v["data"] = 3, None

    def delete_secret(self, request):
        if request["name"] not in self.secrets:
            raise NotFound("gone")
        del self.secrets[request["name"]]

    # deliberately no access_secret_version: the website can't read a login back


NAME = "projects/p/secrets/league-42-espn"


def test_save_creates_one_secret_per_league_and_returns_its_reference():
    fake = FakeSecrets()
    assert espn_login.save(fake, "p", 42, LOGIN) == "secret:league-42-espn"
    [version] = fake.secrets[NAME]
    assert json.loads(version["data"]) == LOGIN
    assert fake.labels == {"app": "league-lab", "league_id": "42"}


def test_saving_again_destroys_the_old_login():
    fake = FakeSecrets()
    espn_login.save(fake, "p", 42, LOGIN)
    espn_login.save(fake, "p", 42, LOGIN | {"espn_s2": "new"})
    old, new = fake.secrets[NAME]
    assert old["state"] == 3 and old["data"] is None  # destroyed, unreadable
    assert new["state"] == 1 and json.loads(new["data"])["espn_s2"] == "new"


def test_only_the_two_cookies_are_stored():
    fake = FakeSecrets()
    espn_login.save(fake, "p", 42, LOGIN | {"extra": "ignored"})
    assert set(json.loads(fake.secrets[NAME][0]["data"])) == {"espn_s2", "SWID"}


def test_remove_deletes_the_secret_and_tolerates_missing():
    fake = FakeSecrets()
    espn_login.save(fake, "p", 42, LOGIN)
    espn_login.remove(fake, "p", 42)
    assert NAME not in fake.secrets
    espn_login.remove(fake, "p", 42)  # no error
