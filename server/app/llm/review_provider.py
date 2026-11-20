"""Select the server's configured Responses credentials for new review jobs."""

from . import chatgpt


def connection(settings, user_id):
    if settings.ai_review_provider == "openai_api":
        if not settings.openai_api_key:
            raise chatgpt.ReviewError("api_key_required")
        return {"model": settings.openai_model}
    return chatgpt.connection(settings.chatgpt_credentials_dir, user_id)


def generate(settings, provider, directory, user_id, *args, **kwargs):
    # A queued job keeps its credential type when the deployment settings change.
    if provider != settings.ai_review_provider:
        raise chatgpt.ReviewError("setup_required")
    if provider == "openai_api":
        connection(settings, user_id)
        kwargs["api_key"] = settings.openai_api_key.get_secret_value()
    return chatgpt.generate(directory, user_id, *args, **kwargs)
