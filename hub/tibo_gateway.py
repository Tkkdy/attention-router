# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Narrow lifecycle port. Pins isolated Hub; never delegates to Todo Core."""
from butler_todo_projection import ProjectionHub
from todo_core import ButlerError

class TiboGatewayPort:
    def __call__(self, command):
        hub = ProjectionHub()
        try:
            if command.action == "show_tibo_page":
                return hub._request("POST", "/api/tibo/show", {"request_id": command.source+"-"+command.request_id})
            if command.action == "get_tibo_attention":
                return hub._request("GET", "/api/tibo/lifecycle")
            args = command.arguments
            return hub._request("POST", "/api/tibo/events/"+args["event_id"]+"/ack",
                {"revision": args["event_revision"], "command_id": command.source+"-"+command.request_id})
        except Exception:
            raise ButlerError("attention_unavailable", 503) from None
        finally:
            hub.close()
