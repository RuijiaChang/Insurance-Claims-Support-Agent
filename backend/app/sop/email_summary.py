"""Email summary models."""

from pydantic import BaseModel


class EmailDraft(BaseModel):
    subject: str
    to_masked: str
    sections: dict[str, list[str]]

    @property
    def body(self) -> str:
        blocks = [
            title + "\n" + "\n".join(f"- {line}" for line in lines)
            for title, lines in self.sections.items()
        ]
        return "\n\n".join(blocks)
