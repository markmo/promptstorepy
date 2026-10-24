"""``PromptStore.get_prompt_set``: the version pin reaches the server, and a
version the server does not have fails instead of returning latest.

The HTTP layer is faked at ``requests.request`` (what ``ApiService`` calls),
so each request goes through the real ``ApiService`` and the URL asserted is
the one ``requests`` would send.
"""

import json
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

import promptstorepy
from promptstorepy import PromptSetVersionNotFound, PromptStore

BASE = "http://promptstore.invalid/api"
PROMPT_SET = {
    "skill": "summarise",
    "templateEngine": "handlebars",
    "prompts": [{"role": "user", "prompt": "Summarise {{text}}"}],
}


class _FakeHttp:
    """Answers every request with ``status`` and ``body``, recording the URL."""

    def __init__(self, status=200, body=None):
        self.status = status
        self.body = body
        self.urls = []
        self.kwargs = []

    def __call__(self, method, url, **kwargs):
        prepared = requests.Request(method, url, params=kwargs.get("params")).prepare()
        self.urls.append(prepared.url)
        self.kwargs.append(kwargs)
        response = requests.Response()
        response.status_code = self.status
        response._content = json.dumps(self.body).encode()
        response.url = prepared.url
        response.request = prepared
        return response

    @property
    def query(self):
        return parse_qs(urlsplit(self.urls[-1]).query)


@pytest.fixture
def store():
    return PromptStore({"PROMPTSTORE_BASE_URL": BASE, "WORKSPACE_ID": "1"})


@pytest.fixture
def http(monkeypatch):
    fake = _FakeHttp()
    monkeypatch.setattr("promptstorepy.ApiService.requests.request", fake)
    return fake


def test_version_is_sent_as_a_query_parameter(store, http):
    resolved = {"id": "a-uuid", "version": 3, "tag": "1.2.0"}
    http.body = [{**PROMPT_SET, "resolvedVersion": resolved}]

    prompt_set = store.get_prompt_set("summarise", "1.2.0")

    assert urlsplit(http.urls[-1]).path == "/api/workspaces/1/prompt-sets"
    assert http.query == {"skill": ["summarise"], "version": ["1.2.0"]}
    assert prompt_set["resolvedVersion"] == resolved
    assert prompt_set["prompts"] == PROMPT_SET["prompts"]


def test_integer_version_is_sent_as_its_number(store, http):
    http.body = [PROMPT_SET]
    store.get_prompt_set("summarise", 3)
    assert http.query["version"] == ["3"]


def test_unknown_version_404_raises(store, http):
    http.status = 404
    http.body = {"errors": [{"message": "No version 9.9.9 of prompt set summarise"}]}

    with pytest.raises(PromptSetVersionNotFound) as caught:
        store.get_prompt_set("summarise", "9.9.9")

    error = caught.value
    assert isinstance(error, LookupError)
    assert (error.skill, error.version) == ("summarise", "9.9.9")
    assert "summarise" in str(error) and "9.9.9" in str(error)
    assert "No version 9.9.9" in str(error)
    assert isinstance(error.__cause__, requests.HTTPError)


def test_404_without_a_json_body_still_raises(store, monkeypatch):
    fake = _FakeHttp(status=404)
    fake.body = None
    monkeypatch.setattr("promptstorepy.ApiService.requests.request", fake)
    with pytest.raises(PromptSetVersionNotFound, match="9.9.9"):
        store.get_prompt_set("summarise", "9.9.9")


def test_empty_list_with_a_version_raises(store, http):
    http.body = []
    with pytest.raises(PromptSetVersionNotFound, match="1.0.0"):
        store.get_prompt_set("summarise", "1.0.0")


def test_no_version_sends_only_the_skill(store, http):
    http.body = [PROMPT_SET, {**PROMPT_SET, "skill": "other"}]

    assert store.get_prompt_set("summarise") == PROMPT_SET
    assert http.query == {"skill": ["summarise"]}


def test_no_version_and_no_prompt_set_returns_none(store, http):
    http.body = []
    assert store.get_prompt_set("summarise") is None


def test_no_version_request_error_returns_an_errors_dict(store, http):
    http.status = 404
    http.body = {"errors": [{"message": "not found"}]}

    result = store.get_prompt_set("summarise")

    # The server's own error body is passed through.
    assert result == {"errors": [{"message": "not found"}]}


def test_error_without_a_json_errors_body_returns_a_generic_errors_dict(store, monkeypatch):
    fake = _FakeHttp(status=500)
    original = fake.__call__

    def html(method, url, **kwargs):
        response = original(method, url, **kwargs)
        response._content = b"<html>Bad Gateway</html>"
        return response

    monkeypatch.setattr("promptstorepy.ApiService.requests.request", html)

    result = store.get_prompt_set("summarise")

    assert set(result) == {"errors"}
    assert "500" in result["errors"][0]["message"]


def test_execute_passes_the_server_errors_through(store, http):
    http.status = 400
    http.body = {"errors": [{"message": "args do not match the function schema"}]}

    assert store.execute("summarise", {"text": "x"}, {}) == http.body


def test_special_characters_in_skill_and_version_are_encoded(store, http):
    http.body = [PROMPT_SET]
    skill = "a&b=c d/é?#"
    version = "v1.0.0+build&x=1"

    store.get_prompt_set(skill, version)

    raw_query = urlsplit(http.urls[-1]).query
    assert "&x=1" not in raw_query and "#" not in raw_query and " " not in raw_query
    assert http.query == {"skill": [skill], "version": [version]}


def test_api_service_forwards_params(store, http):
    http.body = [PROMPT_SET]
    store.get_prompt_set("summarise", "1.0.0")
    assert http.kwargs[-1]["params"] == {"skill": "summarise", "version": "1.0.0"}


def test_exception_is_exported_from_the_package():
    assert promptstorepy.PromptSetVersionNotFound is PromptSetVersionNotFound
    assert issubclass(PromptSetVersionNotFound, LookupError)
