from urllib.parse import quote

import websockets


async def connect_chat_socket(websocket_url: str, token: str):
    separator = "&" if "?" in websocket_url else "?"
    full_url = f"{websocket_url}{separator}token={quote(token)}"
    return await websockets.connect(full_url)
