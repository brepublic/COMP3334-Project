from typing import List

import httpx
from pydantic import TypeAdapter

if __package__:
    from .Schema import (
        AckMessagesRequest,
        FriendInfo,
        FriendListResponse,
        FriendRequestAction,
        FriendRequestPayload,
        LoginRequest,
        LoginResponse,
        OfflineMessageResponse,
        ContactKeysResponse,
        RegisterRequest,
        RegisterResponse,
        SendMessageRequest,
        SendMessageResponse,
        StandardResponse,
        PendingRequestInfo,
        BlockUserRequest,
    )
else:
    from Schema import (
        AckMessagesRequest,
        FriendInfo,
        FriendListResponse,
        FriendRequestAction,
        FriendRequestPayload,
        LoginRequest,
        LoginResponse,
        OfflineMessageResponse,
        ContactKeysResponse,
        RegisterRequest,
        RegisterResponse,
        SendMessageRequest,
        SendMessageResponse,
        StandardResponse,
        PendingRequestInfo,
        BlockUserRequest,
    )


class ClientAPIError(RuntimeError):
    pass


class ChatClientAPI:
    def __init__(self, base_url: str, access_token: str | None = None):
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=10.0)
        self._access_token = access_token

    def close(self) -> None:
        self._client.close()

    def _headers(self, require_auth: bool) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if require_auth:
            if not self._access_token:
                raise ClientAPIError("This command requires a saved login token.")
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    def _request(self, method: str, path: str, *, require_auth: bool = False, json_data=None):
        try:
            response = self._client.request(
                method,
                path,
                headers=self._headers(require_auth),
                json=json_data,
            )
        except httpx.RequestError as exc:
            raise ClientAPIError(
                f"Transport error for {method} {self._client.base_url.join(path)}: {exc}"
            ) from exc

        if response.is_error:
            try:
                payload = response.json()
                detail = payload.get("detail", payload)
            except ValueError:
                detail = response.text
            raise ClientAPIError(
                f"{response.status_code} {response.reason_phrase} for "
                f"{response.request.method} {response.request.url}: {detail}"
            )

        if not response.content:
            return None
        return response.json()

    def register(self, payload: RegisterRequest) -> RegisterResponse:
        data = self._request("POST", "/register", json_data=payload.model_dump())
        return RegisterResponse.model_validate(data)

    def login(self, payload: LoginRequest) -> LoginResponse:
        data = self._request("POST", "/login", json_data=payload.model_dump())
        return LoginResponse.model_validate(data)

    def logout(self) -> StandardResponse:
        data = self._request("POST", "/logout", require_auth=True)
        return StandardResponse.model_validate(data)

    def logout_all(self) -> StandardResponse:
        data = self._request("POST", "/logout-all", require_auth=True)
        return StandardResponse.model_validate(data)

    def list_friends(self) -> FriendListResponse:
        data = self._request("GET", "/friends", require_auth=True)
        return FriendListResponse.model_validate(data)

    def add_friend(self, payload: FriendRequestPayload) -> StandardResponse:
        data = self._request("POST", "/friends/request", require_auth=True, json_data=payload.model_dump())
        return StandardResponse.model_validate(data)

    def pending_requests(self, direction: str = "incoming") -> List[PendingRequestInfo]:
        data = self._request("GET", f"/friends/pending?direction={direction}", require_auth=True)
        return TypeAdapter(List[PendingRequestInfo]).validate_python(data)

    def respond_to_request(self, payload: FriendRequestAction) -> StandardResponse:
        data = self._request("POST", "/friends/action", require_auth=True, json_data=payload.model_dump())
        return StandardResponse.model_validate(data)

    def send_message(self, payload: SendMessageRequest) -> SendMessageResponse:
        data = self._request("POST", "/messages/send", require_auth=True, json_data=payload.model_dump())
        return SendMessageResponse.model_validate(data)

    def pull_messages(self) -> OfflineMessageResponse:
        data = self._request("GET", "/messages/offline", require_auth=True)
        return OfflineMessageResponse.model_validate(data)

    def acknowledge_messages(self, payload: AckMessagesRequest) -> StandardResponse:
        data = self._request("POST", "/messages/ack", require_auth=True, json_data=payload.model_dump())
        return StandardResponse.model_validate(data)

    def get_contact_keys(self, contact_uuid: str) -> ContactKeysResponse:
        data = self._request("GET", f"/friends/{contact_uuid}/keys", require_auth=True)
        return ContactKeysResponse.model_validate(data)

    def remove_friend(self, friend_uuid: str) -> StandardResponse:
        data = self._request("DELETE", f"/friends/{friend_uuid}", require_auth=True)
        return StandardResponse.model_validate(data)

    def cancel_friend_request(self, request_id: str) -> StandardResponse:
        data = self._request("DELETE", f"/friends/request/{request_id}", require_auth=True)
        return StandardResponse.model_validate(data)

    def block_user(self, target_uuid: str) -> StandardResponse:
        data = self._request(
            "POST",
            "/friends/block",
            require_auth=True,
            json_data=BlockUserRequest(target_uuid=target_uuid).model_dump(),
        )
        return StandardResponse.model_validate(data)
