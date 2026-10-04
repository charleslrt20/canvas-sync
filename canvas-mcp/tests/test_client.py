import httpx
import pytest
import respx

from canvas_mcp.client import CanvasClient, CanvasError

BASE = "https://canvas.example.edu"
API = f"{BASE}/api/v1"
TOKEN = "SECRET-TOKEN-123"


@pytest.fixture
def client():
    return CanvasClient(BASE, TOKEN)


# --- read-only guard -------------------------------------------------------

@respx.mock
def test_get_sends_bearer_token(client):
    route = respx.get(f"{API}/courses").respond(json=[{"id": 1}])
    assert client.get("/courses") == [{"id": 1}]
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"


@respx.mock(assert_all_mocked=True)
def test_unlisted_path_is_refused_before_network(client):
    with pytest.raises(CanvasError, match="not allowed"):
        client.get("/courses/1/assignments/2/submissions/self")
    with pytest.raises(CanvasError, match="not allowed"):
        client.get("/users/self/profile")
    assert respx.calls.call_count == 0


@respx.mock
def test_non_get_methods_are_refused(client):
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        with pytest.raises(CanvasError, match="read-only"):
            client._request(method, f"{API}/courses")
    assert respx.calls.call_count == 0


@pytest.mark.parametrize(
    "path",
    [
        "/courses",
        "/courses/12/assignments/34",
        "/courses/12/students/submissions",
        "/courses/12/files",
        "/planner/items",
        "/users/self/missing_submissions",
        "/announcements",
        "/files/99",
    ],
)
@respx.mock
def test_allowlisted_paths(client, path):
    respx.get(f"{API}{path}").respond(json={})
    client.get(path)


def test_path_traversal_is_refused(client):
    with pytest.raises(CanvasError, match="not allowed"):
        client.get("/courses/../users/self/profile")


# --- pagination ------------------------------------------------------------

@respx.mock
def test_get_all_follows_link_next(client):
    respx.get(f"{API}/courses", params={"page": "2"}).respond(json=[{"id": 2}])
    respx.get(f"{API}/courses").respond(
        json=[{"id": 1}],
        headers={"Link": f'<{API}/courses?page=2>; rel="next", <{API}/courses?page=1>; rel="first"'},
    )
    assert client.get_all("/courses") == [{"id": 1}, {"id": 2}]


@respx.mock
def test_get_all_refuses_next_link_to_other_host(client):
    respx.get(f"{API}/courses").respond(
        json=[{"id": 1}], headers={"Link": '<https://evil.example.com/api/v1/courses?page=2>; rel="next"'}
    )
    with pytest.raises(CanvasError, match="not allowed"):
        client.get_all("/courses")


@respx.mock
def test_get_all_caps_pages():
    client = CanvasClient(BASE, TOKEN, max_pages=3)
    respx.get(f"{API}/courses").respond(
        json=[{"id": 1}], headers={"Link": f'<{API}/courses?page=2>; rel="next"'}
    )
    respx.get(url__regex=rf"{API}/courses\?page=\d+").respond(
        json=[{"id": 1}], headers={"Link": f'<{API}/courses?page=2>; rel="next"'}
    )
    assert len(client.get_all("/courses")) == 3


# --- caching ---------------------------------------------------------------

@respx.mock
def test_responses_are_cached_until_ttl():
    now = [0.0]
    client = CanvasClient(BASE, TOKEN, ttl=600, clock=lambda: now[0])
    route = respx.get(f"{API}/courses").respond(json=[])
    client.get("/courses")
    client.get("/courses")
    assert route.call_count == 1
    now[0] = 601
    client.get("/courses")
    assert route.call_count == 2


@respx.mock
def test_cache_key_includes_params(client):
    route = respx.get(f"{API}/announcements").respond(json=[])
    client.get("/announcements", params=[("context_codes[]", "course_1")])
    client.get("/announcements", params=[("context_codes[]", "course_2")])
    assert route.call_count == 2


# --- errors never leak the token ------------------------------------------

@pytest.mark.parametrize(
    "status,message",
    [(401, "token invalid or expired"), (403, "no permission"), (404, "not found"),
     (429, "rate limited"), (500, "Canvas is having problems")],
)
@respx.mock
def test_http_errors_are_mapped(client, status, message):
    respx.get(f"{API}/courses").respond(status, text=f"echo {TOKEN}")
    with pytest.raises(CanvasError, match=message) as exc:
        client.get("/courses")
    assert TOKEN not in str(exc.value)


@respx.mock
def test_network_error_does_not_leak_token(client):
    respx.get(f"{API}/courses").mock(side_effect=httpx.ConnectError(f"boom {TOKEN}"))
    with pytest.raises(CanvasError) as exc:
        client.get("/courses")
    assert TOKEN not in str(exc.value)


def test_repr_hides_token(client):
    assert TOKEN not in repr(client)


def test_missing_token_is_rejected():
    with pytest.raises(CanvasError, match="CANVAS_TOKEN"):
        CanvasClient(BASE, "")


# --- file downloads --------------------------------------------------------

@respx.mock
def test_download_follows_redirect_to_cdn_without_token(client):
    respx.get(f"{API}/files/7").respond(json={"id": 7, "url": f"{BASE}/files/7/download?verifier=x"})
    respx.get(f"{BASE}/files/7/download").respond(
        302, headers={"Location": "https://abc.inscloudgate.net/file.pdf"}
    )
    cdn = respx.get("https://abc.inscloudgate.net/file.pdf").respond(content=b"%PDF-data")
    meta, data = client.download(7)
    assert data == b"%PDF-data"
    assert meta["id"] == 7
    assert "Authorization" not in cdn.calls.last.request.headers


@respx.mock
def test_download_refuses_redirect_to_unknown_host(client):
    respx.get(f"{API}/files/7").respond(json={"id": 7, "url": f"{BASE}/files/7/download"})
    respx.get(f"{BASE}/files/7/download").respond(302, headers={"Location": "https://evil.example.com/x"})
    with pytest.raises(CanvasError, match="not allowed"):
        client.download(7)


@respx.mock
def test_download_refuses_oversized_file(client):
    respx.get(f"{API}/files/7").respond(json={"id": 7, "size": 200_000_000, "url": f"{BASE}/files/7/download"})
    with pytest.raises(CanvasError, match="too large"):
        client.download(7)


@respx.mock
def test_download_allows_canvas_user_content_host(client):
    respx.get(f"{API}/files/8").respond(json={"id": 8, "url": f"{BASE}/files/8/download"})
    respx.get(f"{BASE}/files/8/download").respond(
        302, headers={"Location": "https://a1-8.cluster335.canvas-user-content.com/files/8"}
    )
    cdn = respx.get("https://a1-8.cluster335.canvas-user-content.com/files/8").respond(content=b"data")
    assert client.download(8)[1] == b"data"
    assert "Authorization" not in cdn.calls.last.request.headers
