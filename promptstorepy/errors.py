from typing import Optional, Union


class PromptSetVersionNotFound(LookupError):
    """A prompt set was asked for at a version the server does not have.

    Raised instead of silently returning the latest prompts, so a pinned
    ``(skill, version)`` either renders exactly that version or fails.
    """

    def __init__(
        self, skill: str, version: Union[str, int], detail: Optional[str] = None
    ):
        self.skill = skill
        self.version = version
        message = f"Prompt set {skill!r} has no version {version!r}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)
