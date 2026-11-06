import base64
import difflib
import json
import logging
import os

import azure.functions as func
import httpx

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

AZDO_ORG = os.environ.get("AZDO_ORG", "niagarabottling")
AZDO_PROJECT = os.environ.get("AZDO_PROJECT", "Azure_Integrations")
AZDO_REPO = os.environ.get("AZDO_REPO", "MCP-Integrations")
AZDO_PAT = os.environ.get("AZDO_PAT", "")

API_VERSION = "7.1"
MAX_DIFF_CHARS = 60000
MAX_FILE_BYTES = 200000


def _base_url() -> str:
    return f"https://dev.azure.com/{AZDO_ORG}/{AZDO_PROJECT}/_apis/git/repositories/{AZDO_REPO}"


def _azdo_headers() -> dict:
    token = base64.b64encode(f":{AZDO_PAT}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def _get(url: str, params: dict | None = None) -> httpx.Response:
    return httpx.get(url, params={"api-version": API_VERSION, **(params or {})},
                     headers=_azdo_headers(), timeout=20)


def _parse(resp: httpx.Response) -> tuple[dict | None, str | None]:
    if resp.is_error:
        logging.warning("Azure DevOps call failed: status=%d url=%s", resp.status_code, resp.url)
        return None, json.dumps({"error": True, "status_code": resp.status_code, "detail": resp.text[:500]})
    if "json" not in resp.headers.get("content-type", ""):
        logging.warning("Azure DevOps returned non-JSON: status=%d url=%s", resp.status_code, resp.url)
        return None, json.dumps({
            "error": True,
            "status_code": resp.status_code,
            "detail": "Azure DevOps returned a sign-in page instead of data. Check that AZDO_PAT is set and valid.",
        })
    return resp.json(), None


def _validate_pr_id(pr_id: str) -> bool:
    return pr_id.isdigit()


def _get_file_text(commit_id: str, path: str) -> str:
    resp = _get(f"{_base_url()}/items", {
        "path": path,
        "versionDescriptor.version": commit_id,
        "versionDescriptor.versionType": "commit",
        "includeContent": "true",
    })
    if resp.status_code == 404:
        return ""
    data, err = _parse(resp)
    if err:
        raise RuntimeError(f"could not read {path}")
    content = data.get("content", "")
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        return "<file too large to review>"
    return content


@app.mcp_tool()
def hello_mcp() -> str:
    """Health check for the PR review MCP server."""
    return "PR review MCP server is running."


@app.mcp_tool()
@app.mcp_tool_property(arg_name="pr_id", description="Azure DevOps pull request ID, e.g. 123", is_required=True)
def get_pr_details(pr_id: str) -> str:
    """Return title, author, branches, and status of an Azure DevOps pull request."""
    if not _validate_pr_id(pr_id):
        return json.dumps({"error": True, "detail": "pr_id must be a number"})

    pr, err = _parse(_get(f"{_base_url()}/pullrequests/{pr_id}"))
    if err:
        return err

    return json.dumps({
        "pr_id": pr.get("pullRequestId"),
        "title": pr.get("title"),
        "author": pr.get("createdBy", {}).get("displayName"),
        "source_branch": pr.get("sourceRefName"),
        "target_branch": pr.get("targetRefName"),
        "status": pr.get("status"),
        "url": pr.get("url"),
    }, indent=2)


@app.mcp_tool()
@app.mcp_tool_property(arg_name="pr_id", description="Azure DevOps pull request ID, e.g. 123", is_required=True)
def get_pr_diff(pr_id: str) -> str:
    """Return a unified diff of every file changed in the latest iteration of a pull request."""
    if not _validate_pr_id(pr_id):
        return json.dumps({"error": True, "detail": "pr_id must be a number"})

    pr, err = _parse(_get(f"{_base_url()}/pullrequests/{pr_id}"))
    if err:
        return err
    source_commit = pr.get("lastMergeSourceCommit", {}).get("commitId")
    target_commit = pr.get("lastMergeTargetCommit", {}).get("commitId")

    iterations, err = _parse(_get(f"{_base_url()}/pullrequests/{pr_id}/iterations"))
    if err:
        return err
    iteration_list = iterations.get("value", [])
    if not iteration_list:
        return json.dumps({"pr_id": int(pr_id), "files": [], "note": "no iterations found"})
    latest_id = iteration_list[-1]["id"]

    changes, err = _parse(_get(f"{_base_url()}/pullrequests/{pr_id}/iterations/{latest_id}/changes"))
    if err:
        return err

    files = []
    total_chars = 0
    for change in changes.get("changeEntries", []):
        item = change.get("item", {})
        path = item.get("path")
        if not path or item.get("isFolder"):
            continue
        change_type = change.get("changeType", "edit")

        try:
            old_text = "" if change_type == "add" else _get_file_text(target_commit, path)
            new_text = "" if change_type == "delete" else _get_file_text(source_commit, path)
        except RuntimeError as exc:
            files.append({"path": path, "change_type": change_type, "diff": f"<skipped: {exc}>"})
            continue

        diff_text = "".join(difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a{path}",
            tofile=f"b{path}",
        ))
        total_chars += len(diff_text)
        if total_chars > MAX_DIFF_CHARS:
            files.append({"path": path, "change_type": change_type,
                          "diff": "<diff omitted: total size limit reached>"})
            break
        files.append({"path": path, "change_type": change_type, "diff": diff_text})

    return json.dumps({"pr_id": int(pr_id), "iteration": latest_id, "files": files}, indent=2)


@app.mcp_tool()
@app.mcp_tool_property(arg_name="pr_id", description="Azure DevOps pull request ID, e.g. 123", is_required=True)
@app.mcp_tool_property(arg_name="file_path", description="Repo path of the file, e.g. /scripts/review.py", is_required=True)
@app.mcp_tool_property(arg_name="line", description="Line number in the new version of the file", is_required=True)
@app.mcp_tool_property(arg_name="comment", description="The review comment text", is_required=True)
def post_review_comment(pr_id: str, file_path: str, line: str, comment: str) -> str:
    """Post an inline review comment on a line of a pull request. Comments only, never changes code."""
    if not _validate_pr_id(pr_id) or not str(line).isdigit():
        return json.dumps({"error": True, "detail": "pr_id and line must be numbers"})
    if not comment.strip():
        return json.dumps({"error": True, "detail": "comment is empty"})

    path = file_path if file_path.startswith("/") else f"/{file_path}"
    line_no = int(line)
    body = {
        "comments": [{"parentCommentId": 0, "content": comment, "commentType": 1}],
        "status": 1,
        "threadContext": {
            "filePath": path,
            "rightFileStart": {"line": line_no, "offset": 1},
            "rightFileEnd": {"line": line_no, "offset": 1},
        },
    }
    resp = httpx.post(f"{_base_url()}/pullrequests/{pr_id}/threads",
                      params={"api-version": API_VERSION},
                      headers={**_azdo_headers(), "Content-Type": "application/json"},
                      json=body, timeout=20)
    thread, err = _parse(resp)
    if err:
        return err
    return json.dumps({"posted": True, "thread_id": thread.get("id"), "file": path, "line": line_no})
