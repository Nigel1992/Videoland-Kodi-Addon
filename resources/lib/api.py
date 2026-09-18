import base64
import copy
import hashlib
import json
import os
import re
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ApiError(Exception):
    pass


class AuthError(ApiError):
    """Raised when the session/JWT is missing, expired or rejected.

    Callers use this as the signal to refresh the session (auto-relogin) and
    retry the original request exactly once.
    """


class VideolandApi:
    API_KEY = "4_hRanGnYDFjdiZQfh-ghhhg"  # Public key shipped by the Videoland web client.
    CUSTOMER = "rtlnl"
    PLATFORM = "m6group_web"
    CLIENT_RELEASE = "6.49.1"
    GIGYA = "https://gigya-merge.videoland.com"
    FRONT_AUTH = "https://front-auth.videoland.bedrock.tech"
    USERS = "https://users.videoland.bedrock.tech"
    LAYOUT = "https://layout.videoland.bedrock.tech"
    DRM = "https://drm.videoland.bedrock.tech"
    LICENSE_URL = "https://lic.drmtoday.com/license-proxy-widevine/cenc/"

    def __init__(self, device_id=None, timeout=20, cache_dir=None, cache_ttl=3600):
        self.device_id = device_id or "kodi-" + str(uuid.uuid4())
        self.timeout = timeout
        self.token = None
        self.cache_dir = cache_dir
        self.cache_ttl = int(cache_ttl or 0)

    def _headers(self, location="https://v2.videoland.com/", authenticated=True):
        headers = {
            "Accept": "application/json",
            "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
            "Request-Timeout": "10000",
            "User-Agent": "Kodi Videoland/0.1.0",
            "X-Client-Release": self.CLIENT_RELEASE,
            "X-Customer-Name": self.CUSTOMER,
            "X-Location": location,
            "Origin": "https://v2.videoland.com",
            "Referer": "https://v2.videoland.com/",
        }
        if authenticated and self.token:
            headers["Authorization"] = "Bearer " + self.token
        return headers

    def _request(self, url, headers=None, data=None, allow_empty=False, timeout=None):
        request = Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
        try:
            with urlopen(request, timeout=self.timeout if timeout is None else timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            raw_error = exc.read(4096).decode("utf-8", "replace")
            detail = ""
            try:
                error_data = json.loads(raw_error)
                detail = error_data.get("message") or error_data.get("error") or error_data.get("reason") or ""
                if isinstance(detail, dict):
                    detail = json.dumps(detail, separators=(",", ":"))
            except (ValueError, AttributeError):
                detail = raw_error if raw_error and len(raw_error) < 300 else ""
            # Defensively redact emails and JWT-like strings before Kodi logging.
            detail = re.sub(r"[\w.+-]+@[\w.-]+", "[email]", str(detail))
            detail = re.sub(r"eyJ[A-Za-z0-9_.-]{20,}", "[token]", detail)
            suffix = ": " + detail[:300] if detail else ""
            # 498 is Videoland's invalid/expired-token response. Like 401/403,
            # it means the session
            # (JWT or Gigya signature) is stale. Surface this distinctly so the
            # caller can re-login and retry instead of surfacing a dead end.
            if exc.code in (401, 403, 498):
                raise AuthError("Authenticatie verlopen ({})".format(exc.code)) from exc
            raise ApiError("HTTP {} from {}{}".format(exc.code, url.split("?", 1)[0], suffix)) from exc
        except URLError as exc:
            raise ApiError("Network error contacting {}: {}".format(url.split("?", 1)[0], exc.reason)) from exc
        if allow_empty and not raw.strip():
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError("Invalid JSON from {}".format(url.split("?", 1)[0])) from exc

    def _cache_key(self, url, extra=""):
        if not self.cache_dir:
            return None
        raw = (extra + "\n" if extra else "") + url
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, "cache_" + digest + ".json")

    def _cached_get(self, url, headers, extra="", use_cache=True):
        path = self._cache_key(url, extra) if use_cache else None
        if self.cache_ttl > 0 and path and os.path.exists(path):
            try:
                if time.time() - os.path.getmtime(path) < self.cache_ttl:
                    with open(path, "r", encoding="utf-8") as fh:
                        return json.load(fh)
            except (OSError, ValueError):
                pass
        for attempt in range(3):
            try:
                result = self._request(url, headers)
                break
            except ApiError as exc:
                cause = exc.__cause__
                if (attempt == 2 or not isinstance(cause, HTTPError)
                        or cause.code not in (500, 502, 503, 504)):
                    raise
                time.sleep(0.5 * (attempt + 1))
        if path:
            try:
                os.makedirs(self.cache_dir, exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(result, fh)
            except OSError:
                pass
        return result

    @staticmethod
    def clear_cache(cache_dir):
        if not cache_dir or not os.path.isdir(cache_dir):
            return 0
        removed = 0
        try:
            for name in os.listdir(cache_dir):
                if name.startswith("cache_") and name.endswith(".json"):
                    try:
                        os.remove(os.path.join(cache_dir, name))
                        removed += 1
                    except OSError:
                        pass
        except OSError:
            pass
        return removed

    def login(self, email, password):
        fields = {
            "apiKey": self.API_KEY,
            "loginId": email,
            "password": password,
            "include": "profile,data",
            "includeUserInfo": "true",
        }
        boundary = "----KodiVideoland{}".format(uuid.uuid4().hex)
        chunks = []
        for name, value in fields.items():
            chunks.extend([
                "--{}\r\n".format(boundary),
                'Content-Disposition: form-data; name="{}"\r\n\r\n'.format(name),
                str(value),
                "\r\n",
            ])
        chunks.append("--{}--\r\n".format(boundary))
        result = self._request(
            self.GIGYA + "/accounts.login",
            {
                "Content-Type": "multipart/form-data; boundary={}".format(boundary),
                "Origin": "https://account.videoland.com",
                "User-Agent": "Kodi Videoland/0.1.0",
            },
            "".join(chunks).encode("utf-8"),
        )
        if result.get("errorCode", 0):
            raise ApiError(result.get("errorMessage") or "Gigya login failed")
        uid = result.get("UID")
        signature = result.get("UIDSignature")
        timestamp = result.get("signatureTimestamp")
        if not all((uid, signature, timestamp)):
            raise ApiError("Login response did not contain a Videoland session signature")
        return {"uid": uid, "signature": signature, "timestamp": str(timestamp)}

    def jwt(self, auth, profile_id=None):
        # front-auth rejects an existing Bearer token when exchanging the
        # Gigya signature for an account- or profile-scoped JWT.
        headers = self._headers(authenticated=False)
        headers.update({
            "X-Auth-gigya-uid": auth["uid"],
            "X-Auth-gigya-signature": auth["signature"],
            "X-Auth-gigya-signature-timestamp": auth["timestamp"],
            "X-Auth-Device-Id": self.device_id,
            "X-Auth-Device-Name": "Kodi",
            "X-Auth-Device-Player-Size-Width": "1920",
            "X-Auth-Device-Player-Size-Height": "1080",
        })
        if profile_id:
            headers["X-Auth-profile-id"] = profile_id
        result = self._request(self.FRONT_AUTH + "/v2/platforms/{}/getJwt".format(self.PLATFORM), headers)
        if not result.get("token"):
            raise ApiError("Videoland did not return a JWT")
        self.token = result["token"]
        claims = self.jwt_claims(self.token) or {}
        self.session_exp = int(claims.get("exp") or 0)
        return self.token

    def session_expired(self, grace=120):
        """True when the current JWT is missing or past its expiry (with grace)."""
        exp = getattr(self, "session_exp", 0)
        if not exp:
            return self.token is None
        return time.time() >= exp - grace

    def profiles(self, uid):
        url = self.USERS + "/v2/platforms/{}/users/{}/profiles".format(self.PLATFORM, uid)
        result = self._request(url, self._headers())
        return result if isinstance(result, list) else result.get("profiles", [])

    def navigation(self, target="desktop"):
        url = self.LAYOUT + "/front/v1/{}/{}/main/token-web-31/navigation/{}".format(
            self.CUSTOMER, self.PLATFORM, target
        )
        return self._cached_get(url, self._headers())

    def layout(self, kind="alias", entity_id="home", location=None, query=None, complete=False,
               block_filter=None):
        location = location or "https://v2.videoland.com/"
        url = self.LAYOUT + "/front/v1/{}/{}/main/token-web-31/{}/{}/layout".format(
            self.CUSTOMER, self.PLATFORM, kind, entity_id
        )
        query_parameters = {"blockPage": 1, "nbPages": 2}
        query_parameters.update(query or {})
        headers = self._headers(location)

        def fetch(parameters):
            # Video layouts contain profile progress and short-lived stream URLs.
            return self._cached_get(url + "?" + urlencode(parameters), headers,
                                    extra=location, use_cache=kind != "video")

        result = fetch(query_parameters)
        if not complete:
            return result
        result = copy.deepcopy(result)
        blocks = result.setdefault("blocks", [])
        seen_pages = {query_parameters["blockPage"]}
        page = (result.get("pagination") or {}).get("nextPage")
        while page is not None:
            if page in seen_pages:
                raise ApiError("Layout pagination did not advance")
            seen_pages.add(page)
            following = fetch(dict(query_parameters, blockPage=page))
            if not following.get("blocks"):
                raise ApiError("Layout pagination returned an empty page")
            blocks.extend(following["blocks"])
            page = (following.get("pagination") or {}).get("nextPage")
        if "pagination" in result:
            result["pagination"]["nextPage"] = None

        # blockPage pages through sections. Each section has its own item
        # cursor and endpoint; changing blockPage cannot load more titles.
        for block in blocks:
            if block_filter is not None and not block_filter(block):
                continue
            content = block.get("content") or {}
            page = (content.get("pagination") or {}).get("nextPage")
            if page is None:
                continue
            block_id = block.get("blockId")
            if not block_id or not isinstance(content.get("items"), list):
                raise ApiError("Paginated block is missing its ID or items")
            block_url = url.rsplit("/", 1)[0] + "/block/" + str(block_id)
            seen_pages = set()
            pages_per_request = 8
            seen_items = {json.dumps(item, sort_keys=True) for item in content["items"]}
            while page is not None:
                if page in seen_pages:
                    raise ApiError("Item pagination did not advance")
                seen_pages.add(page)
                parameters = dict(query or {}, page=page, nbPages=pages_per_request)
                parameters.pop("blockPage", None)
                try:
                    following = self._cached_get(block_url + "?" + urlencode(parameters), headers, extra=location)
                except ApiError as exc:
                    cause = exc.__cause__
                    if (pages_per_request == 1 or not isinstance(cause, HTTPError)
                            or cause.code not in (500, 502, 503, 504)):
                        raise
                    # Some blocks reject a large batch while individual pages
                    # work. Retry the same cursor without dropping any titles.
                    pages_per_request = 1
                    parameters["nbPages"] = 1
                    following = self._cached_get(block_url + "?" + urlencode(parameters), headers, extra=location)
                next_content = following.get("content") or {}
                for item in next_content.get("items") or []:
                    key = json.dumps(item, sort_keys=True)
                    if key not in seen_items:
                        seen_items.add(key)
                        content["items"].append(item)
                # Some editorial rails overstate totalItems and yield empty
                # pages before their final cursor. Follow the cursor even on
                # an empty/overlapping page; repeated cursors still fail above.
                content["pagination"] = next_content.get("pagination") or {}
                page = content["pagination"].get("nextPage")
        return result

    def _progress_post(self, endpoint, uid, payload, authenticated=True):
        headers = self._headers(authenticated=authenticated)
        headers["Content-Type"] = "application/json"
        body = dict(payload, platformCode=self.PLATFORM, uid=uid, uidType="gigya")
        url = "https://heartbeat-v2.videoland.bedrock.tech/v2/platforms/{}/notify/{}".format(
            self.PLATFORM, endpoint)
        return self._request(url, headers, json.dumps(body).encode("utf-8"))

    def remove_continue_watching(self, content_id):
        """Use the website's visibility action; content ID comes from its card."""
        if not isinstance(content_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", content_id):
            raise ApiError("Invalid Continue Watching content ID")
        url = "https://heartbeat-v3.videoland.bedrock.tech/v3/{}/{}/watched_contents_visibility".format(
            self.CUSTOMER, self.PLATFORM)
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        body = json.dumps({content_id: True}).encode("utf-8")
        # Setting visibility to true is idempotent: safely repeat after a gateway
        # timeout, even if the server already applied the first request.
        for attempt in range(3):
            try:
                return self._request(url, headers, body, allow_empty=True, timeout=min(self.timeout, 10))
            except ApiError as exc:
                cause = exc.__cause__
                if (attempt == 2 or not isinstance(cause, HTTPError)
                        or cause.code not in (502, 503, 504)):
                    raise
            except TimeoutError:
                if attempt == 2:
                    raise ApiError("Videoland removal request timed out") from None
            time.sleep(0.5 * (attempt + 1))

    def progress_session(self, uid, session):
        result = self._progress_post("session", uid, session)
        session_id = result.get("sessionId")
        if not session_id:
            raise ApiError("Videoland did not return a playback session")
        return session_id

    def progress_view(self, uid, view):
        return self._progress_post("view", uid, view)

    def upfront_token(self, uid, video_id):
        url = self.DRM + "/v1/customers/{}/platforms/{}/services/videoland/users/{}/videos/{}/upfront-token".format(
            self.CUSTOMER, self.PLATFORM, uid, video_id
        )
        result = self._request(url, self._headers())
        token = result.get("token")
        if not token:
            raise ApiError("Videoland did not return a DRM token")
        return token

    @staticmethod
    def jwt_claims(token):
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        except (ValueError, IndexError, UnicodeDecodeError, json.JSONDecodeError):
            return {}


def _block_context(value):
    """Extract (feature, block_title) from a genuine Bedrock block.

    A block is recognised by its ``analytics.tealium`` metadata (or ``blockId``).
    Plain container dicts (e.g. a ``content`` wrapper) carry a ``title`` too, so
    they are deliberately ignored to avoid overriding the enclosing block.
    """
    analytics = value.get("analytics") if isinstance(value.get("analytics"), dict) else None
    tealium = (analytics or {}).get("tealium") if isinstance((analytics or {}).get("tealium"), dict) else None
    if tealium is None and not value.get("blockId") and not value.get("type"):
        return None
    feature = tealium.get("from") if tealium else None
    title = tealium.get("block_title") if tealium else None
    if not feature and not title and not value.get("blockId"):
        return None
    context = {"feature": feature or "", "block_title": title or ""}
    content = value.get("content") or {}
    if isinstance(content, dict) and content.get("contentTemplateId"):
        context["template"] = content["contentTemplateId"]
    return context


def walk_item_content(value, block=None):
    """Yield ``(item, block)`` pairs for Bedrock ``itemContent`` objects.

    ``block`` is a dict describing the containing block: ``{"feature": ...,
    "block_title": ...}``. It lets callers tell primary content (episodes/seasons)
    apart from recommendation/"related" rails, trailers and ads without relying on
    a fixed page template.
    """
    if isinstance(value, dict):
        item = value.get("itemContent")
        if isinstance(item, dict):
            yield item, dict(block) if block else {}
        child_block = block
        if "itemContent" not in value:
            ctx = _block_context(value)
            if ctx is not None:
                child_block = ctx
        for key, child in value.items():
            # secondaryActions are auxiliary (bookmark/trailer); not list content.
            if key == "secondaryActions":
                continue
            yield from walk_item_content(child, child_block)
    elif isinstance(value, list):
        for child in value:
            yield from walk_item_content(child, block)


# Features (analytics.tealium.from) that carry recommendation/auxiliary rails we
# should not surface as directory entries on a series/movie/program page.
# ``info_by_program`` is deliberately NOT filtered: it is the primary program
# content block whose embedded clip is the playable film (or the series hero).
RELATED_FEATURES = (
    "recommend",
    "related",
    "trailers",
    "advertis",
    # Explicitly related ``*_by_program`` variants on detail pages. The generic
    # "recommend" substring above is narrowed in is_related_block so that the
    # home "Verder kijken" rail (recommended_videos_by_user) is kept.
)


def is_related_block(block):
    """Return True when a block signals recommendation/trailer/ad/hero content."""
    if not block:
        return False
    feature = str(block.get("feature") or "").lower()
    title = str(block.get("block_title") or "").lower()
    # Personalized home rails like "Verder kijken"
    # (feature.recommended_videos_by_user) are real content and must be kept;
    # only drop recommendation rails that recommend *by program* (e.g. the
    # series-page "Anderen kijken ook" rail).
    by_user = "recommend" in feature and feature.endswith("by_user")
    if not by_user:
        for h in RELATED_FEATURES:
            if h in feature:
                return True
    # Standalone "Trailers" rails (feature videos_by_program) are not episodes.
    if "trail" in title:
        return True
    return False


def is_hero_block(block):
    """Return True when a block is the page hero (Jumbotron).

    The hero often re-uses the featured/latest episode's target id. It is real
    content (a film's playable teaser is only listed here), so it must not be
    filtered outright; callers prefer the real episode/movie card instead when
    the same id also appears in a regular listing block.
    """
    if not block:
        return False
    if str((block or {}).get("template") or "").casefold() == "jumbotron":
        return True
    return str((block or {}).get("feature") or "").casefold() == "feature.info_by_program"


def block_season(block):
    """Return the season number from a block title like 'Seizoen 1'."""
    title = str((block.get("block_title") or "") or "")
    for token in title.split():
        if token.isdigit():
            return int(token)
    return None


def action_target(item):
    action = item.get("action") or {}
    target = action.get("target") or {}
    return target.get("value_layout") if target.get("type") == "layout" else None


def navigation_entries(navigation):
    """Yield the entries from all Bedrock navigation groups in display order."""
    groups = navigation if isinstance(navigation, list) else navigation.get("groups", [])
    for group in groups:
        for entry in group.get("entries") or []:
            if isinstance(entry, dict):
                yield entry


def video_assets(layout, video_id=None):
    """Yield DASH/stream assets belonging to ``video_id`` only.

    A video detail layout commonly embeds related/recommendation rows that bring
    their own ``video.assets``. Filtering by the requested video id prevents the
    player from resolving a related video's (or trailer's) stream.
    """
    video_id = str(video_id or "")
    for item, _section in walk_item_content(layout):
        video = item.get("video") or {}
        own_id = str(video.get("id") or "")
        target = action_target(item)
        target_id = str((target or {}).get("id") or "") if target else ""
        if video_id:
            if own_id and own_id != video_id:
                continue
            if target_id and target_id != video_id:
                continue
        for asset in video.get("assets") or []:
            if isinstance(asset, dict) and asset.get("path"):
                yield asset
