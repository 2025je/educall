from rest_framework.negotiation import BaseContentNegotiation, DefaultContentNegotiation
from rest_framework.renderers import BrowsableAPIRenderer


class SuperuserBrowsableNegotiation(DefaultContentNegotiation):
    """Offer the browsable HTML API only to active superusers; everyone else gets JSON."""

    def select_renderer(self, request, renderers, format_suffix=None):
        user = getattr(request, "user", None)
        if not (user and user.is_active and user.is_superuser):
            renderers = [renderer for renderer in renderers if not isinstance(renderer, BrowsableAPIRenderer)]
        return super().select_renderer(request, renderers, format_suffix)


class IgnoreClientContentNegotiation(BaseContentNegotiation):
    """For file and stream endpoints: success bypasses renderers, errors are always JSON."""

    def select_parser(self, request, parsers):
        return parsers[0] if parsers else None

    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type
