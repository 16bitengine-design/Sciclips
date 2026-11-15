"""Publishes videos through Buffer using permanent public GitHub Release assets.

Buffer's API requires a publicly accessible media URL and does not accept file uploads.
This module stores each finished MP4 as a GitHub Release asset, then gives its stable
browser-download URL to Buffer. No third-party media-hosting account or URL is needed.

Required environment:
  BUFFER_API_KEY
  GITHUB_TOKEN
  GITHUB_REPOSITORY (owner/name, supplied automatically by GitHub Actions)
"""
import hashlib
import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BUFFER_URL = "https://api.buffer.com"
GITHUB_API = "https://api.github.com"
YOUTUBE_CATEGORY_SCIENCE = "28"


class PublishError(Exception):
    pass


def default_transport(method, url, headers, body=None, timeout=600):
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        host = urllib.parse.urlparse(url).hostname
        raise PublishError(f"Could not reach {host} ({type(error).__name__}: {str(error)[:100]})") from error


def _gql_string(text):
    return json.dumps(str(text), ensure_ascii=False)


class GithubReleaseMedia:
    """Uploads an MP4 to a public GitHub Release and returns its stable download URL."""

    def __init__(self, token=None, repository=None, transport=None):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.repository = repository or os.environ.get("GITHUB_REPOSITORY")
        if not self.token:
            raise PublishError("Missing GitHub Actions token (GITHUB_TOKEN).")
        if not self.repository or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise PublishError("GITHUB_REPOSITORY must be set to owner/repository.")
        self.transport = transport or default_transport

    def _headers(self, content_type="application/vnd.github+json"):
        return {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28", "Content-Type": content_type}

    def _json_request(self, method, url, payload=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        status, raw = self.transport(method, url, self._headers(), body)
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            data = {}
        if status >= 400:
            message = data.get("message", "GitHub API request failed") if isinstance(data, dict) else "GitHub API request failed"
            raise PublishError(f"GitHub media hosting failed ({status}): {str(message)[:140]}")
        return data

    def upload_video(self, path):
        path = Path(path)
        if not path.is_file():
            raise PublishError(f"Video file does not exist: {path.name}")
        content = path.read_bytes()
        if not content:
            raise PublishError("Refusing to upload an empty video.")
        digest = hashlib.sha256(content).hexdigest()[:12]
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", path.stem).strip("-.")[:80] or "video"
        asset_name = f"{stem}-{digest}{path.suffix.lower() or '.mp4'}"
        tag = f"sciclips-{stem}-{digest}"[:240]
        base = f"{GITHUB_API}/repos/{self.repository}"
        release_url = f"{base}/releases/tags/{urllib.parse.quote(tag, safe='')}"
        status, raw = self.transport("GET", release_url, self._headers(), None)
        if status == 200:
            release = json.loads(raw.decode("utf-8"))
        elif status == 404:
            release = self._json_request("POST", f"{base}/releases", {
                "tag_name": tag, "name": f"Sciclips video: {stem}",
                "body": "Automated Sciclips publishing media. This release asset is used by Buffer.",
                "draft": False, "prerelease": True,
            })
        else:
            try:
                detail = json.loads(raw.decode("utf-8")).get("message", "GitHub API request failed")
            except (ValueError, UnicodeDecodeError):
                detail = "GitHub API request failed"
            raise PublishError(f"GitHub media lookup failed ({status}): {str(detail)[:140]}")

        for asset in release.get("assets", []):
            if asset.get("name") == asset_name and asset.get("browser_download_url"):
                return asset["browser_download_url"]

        upload_url = release.get("upload_url", "").split("{", 1)[0]
        release_id = release.get("id")
        if not upload_url or not release_id:
            raise PublishError("GitHub did not return a usable Release upload endpoint.")
        upload_url += "?name=" + urllib.parse.quote(asset_name)
        content_type = mimetypes.guess_type(asset_name)[0] or "video/mp4"
        status, raw = self.transport("POST", upload_url, self._headers(content_type), content)
        try:
            asset = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            asset = {}
        if status >= 400 or not asset.get("browser_download_url"):
            detail = asset.get("message", "GitHub did not return a public asset URL")
            raise PublishError(f"GitHub video upload failed ({status}): {str(detail)[:140]}")
        return asset["browser_download_url"]


class Buffer:
    def __init__(self, api_key=None, transport=None):
        self.api_key = api_key or os.environ.get("BUFFER_API_KEY")
        if not self.api_key:
            raise PublishError("No Buffer key. Add it as the GitHub secret BUFFER_API_KEY.")
        self.transport = transport or default_transport

    def _query(self, query):
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        status, raw = self.transport("POST", BUFFER_URL, headers, json.dumps({"query": query}).encode("utf-8"))
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            data = {}
        if status >= 400 or data.get("errors"):
            detail = (data.get("errors") or [{}])[0].get("message") or raw[:120]
            raise PublishError(f"Buffer said {status}: {detail}")
        return data.get("data") or {}

    def find_channels(self):
        orgs = self._query("query { account { organizations { id } } }")["account"]["organizations"]
        found = {}
        for org in orgs:
            channels = self._query(f"query {{ channels(input: {{ organizationId: {_gql_string(org['id'])} }}) "
                                   "{ id name service } }")["channels"]
            for channel in channels:
                service = str(channel.get("service", "")).lower()
                if service in ("youtube", "tiktok") and service not in found:
                    found[service] = channel["id"]
        return found

    def create_video_post(self, channel_id, text, video_url, metadata="", mode="shareNow"):
        mutation = (
            "mutation { createPost(input: { "
            f"text: {_gql_string(text)}, channelId: {_gql_string(channel_id)}, schedulingType: automatic, mode: {mode}, "
            f"assets: [{{ video: {{ url: {_gql_string(video_url)} }} }}]{metadata} }}) {{ "
            "... on PostActionSuccess { post { id } } ... on MutationError { message } } }")
        result = self._query(mutation).get("createPost") or {}
        if result.get("message"):
            raise PublishError(f"Buffer refused the post: {result['message']}")
        post = result.get("post") or {}
        if not post.get("id"):
            raise PublishError("Buffer gave no post id.")
        return post["id"]


class BufferPublisher:
    def __init__(self, buffer, media_host, mode="shareNow"):
        self.buffer, self.media_host, self.mode = buffer, media_host, mode

    def publish_video(self, video, title, description, tiktok_caption, accounts, tags=(), made_for_kids=False):
        if not (accounts.get("youtube") or accounts.get("tiktok")):
            raise PublishError("No YouTube or TikTok channel found in Buffer.")
        url = self.media_host.upload_video(video)
        results, failed = {}, {}
        if accounts.get("youtube"):
            metadata = (", metadata: { youtube: { "
                        f"title: {_gql_string(title[:100])}, categoryId: {_gql_string(YOUTUBE_CATEGORY_SCIENCE)}, "
                        f"privacy: public, madeForKids: {'true' if made_for_kids else 'false'}, "
                        "isAiGenerated: true, notifySubscribers: true } }")
            try:
                results["youtube"] = "Buffer post " + self.buffer.create_video_post(
                    accounts["youtube"], description[:5000], url, metadata, self.mode)
            except PublishError as error:
                failed["youtube"] = str(error)[:160]
        if accounts.get("tiktok"):
            try:
                results["tiktok"] = "Buffer post " + self.buffer.create_video_post(
                    accounts["tiktok"], tiktok_caption[:2200], url, "", self.mode)
            except PublishError as error:
                failed["tiktok"] = str(error)[:160]
        if not results:
            raise PublishError("Nothing was accepted by Buffer: " + ", ".join(f"{k}: {v}" for k, v in failed.items()))
        results["failed"] = failed
        results["media_url"] = url
        return results
