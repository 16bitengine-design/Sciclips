"""Publishes a finished video through Buffer, hosting the file on Cloudinary.

Buffer can only attach a video that already sits at a public web address, so the file is uploaded to
Cloudinary first and Buffer is then given that address. One Buffer post is created per channel
(YouTube and TikTok). Follows the documented Buffer GraphQL API (https://api.buffer.com) and the Cloudinary
upload API. The network is reached through one small function (`transport`) so tests can use a fake one.

Secrets used (GitHub Actions secrets):
  CLOUDINARY_URL            cloudinary://API_KEY:API_SECRET@CLOUD_NAME  (shown on your Cloudinary dashboard)
  BUFFER_API_KEY            Buffer: Settings, API
  BUFFER_YOUTUBE_CHANNEL_ID, BUFFER_TIKTOK_CHANNEL_ID   optional; looked up automatically when missing
"""
import hashlib
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse

BUFFER_URL = "https://api.buffer.com"
YOUTUBE_CATEGORY_SCIENCE = "28"


class PublishError(Exception):
    pass


def default_transport(method, url, headers, body, timeout=600):
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise PublishError(f"Could not reach {urlparse(url).hostname} ({type(error).__name__}: {str(error)[:100]})") from error


def _multipart(fields, file_field, file_name, file_bytes, content_type):
    boundary = uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'
                  f"Content-Type: {content_type}\r\n\r\n").encode() + file_bytes + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class Cloudinary:
    def __init__(self, url=None, transport=None, clock=time.time):
        url = url or os.environ.get("CLOUDINARY_URL", "")
        parsed = urlparse(url)
        if parsed.scheme != "cloudinary" or not (parsed.username and parsed.password and parsed.hostname):
            raise PublishError("No Cloudinary connection. Add the GitHub secret CLOUDINARY_URL "
                               "(cloudinary://API_KEY:API_SECRET@CLOUD_NAME).")
        self.key, self.secret, self.cloud = parsed.username, parsed.password, parsed.hostname
        self.transport, self.clock = transport or default_transport, clock

    def upload_video(self, path, public_id):
        path = Path(path)
        params = {"overwrite": "true", "public_id": public_id, "timestamp": str(int(self.clock()))}
        to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params))
        signature = hashlib.sha1((to_sign + self.secret).encode()).hexdigest()
        body, content_type = _multipart({**params, "api_key": self.key, "signature": signature}, "file", path.name,
                                        path.read_bytes(), mimetypes.guess_type(path.name)[0] or "video/mp4")
        status, raw = self.transport("POST", f"https://api.cloudinary.com/v1_1/{self.cloud}/video/upload",
                                     {"Content-Type": content_type}, body)
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            data = {}
        if status >= 400 or not data.get("secure_url"):
            message = (data.get("error") or {}).get("message") if isinstance(data.get("error"), dict) else raw[:120]
            raise PublishError(f"Cloudinary upload failed ({status}): {message}")
        return data["secure_url"]


def _gql_string(text):
    return json.dumps(str(text), ensure_ascii=False)


class Buffer:
    def __init__(self, api_key=None, transport=None):
        self.api_key = api_key or os.environ.get("BUFFER_API_KEY")
        if not self.api_key:
            raise PublishError("No Buffer key. Add it as the GitHub secret BUFFER_API_KEY (Buffer: Settings, API).")
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
        """{'youtube': id, 'tiktok': id}: the first connected channel of each kind."""
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
    """Same `publish_video` call as the other publisher, so the daily runner does not care which one it has."""

    def __init__(self, buffer, cloudinary, mode="shareNow"):
        self.buffer, self.cloudinary, self.mode = buffer, cloudinary, mode

    def publish_video(self, video, title, description, tiktok_caption, accounts, tags=(), made_for_kids=False):
        if not (accounts.get("youtube") or accounts.get("tiktok")):
            raise PublishError("No YouTube or TikTok channel found in Buffer.")
        url = self.cloudinary.upload_video(video, public_id=f"sciclips/{Path(video).stem}")
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
            raise PublishError("Nothing was published: " + ", ".join(f"{k}: {v}" for k, v in failed.items()))
        results["failed"] = failed
        return results
