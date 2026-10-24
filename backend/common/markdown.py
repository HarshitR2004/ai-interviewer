"""Lossless primitives for the documented Markdown subset, not a general parser."""

from collections.abc import Iterator

from .errors import InvalidInput


class DocumentFormatError(InvalidInput):
    pass


class Writer:
    def __init__(self, title: str):
        self.lines = [f"# {title}", ""]

    def heading(self, name: str, level: int = 2) -> None:
        self.lines.extend([f"{'#' * level} {name}", ""])

    def text(self, value: str) -> None:
        self.lines.extend(["> " + line if line else ">" for line in value.split("\n")] + [""])

    def field(self, name: str, value: str, level: int = 3) -> None:
        self.heading(name, level)
        self.text(value)

    def items(self, values: list[str]) -> None:
        if not values:
            self.lines.extend(["No entries.", ""])
            return
        for value in values:
            first, *rest = value.split("\n")
            self.lines.append("- " + first)
            self.lines.extend("  " + line for line in rest)
        self.lines.append("")

    def finish(self) -> str:
        return "\n".join(self.lines) + "\n"


class Reader:
    def __init__(self, content: str, title: str):
        self.lines = content.replace("\r\n", "\n").split("\n")
        self.index = 0
        self.expect(f"# {title}")

    def peek(self) -> str:
        while self.index < len(self.lines) and self.lines[self.index] == "":
            self.index += 1
        return self.lines[self.index] if self.index < len(self.lines) else ""

    def expect(self, value: str) -> None:
        if self.peek() != value:
            raise DocumentFormatError(f"Markdown line {self.index + 1}: expected {value!r}.")
        self.index += 1

    def heading(self, name: str, level: int = 2) -> None:
        self.expect(f"{'#' * level} {name}")

    def text(self) -> str:
        self.peek()
        values: list[str] = []
        while self.index < len(self.lines):
            line = self.lines[self.index]
            if line == ">":
                values.append("")
            elif line.startswith("> "):
                values.append(line[2:])
            else:
                break
            self.index += 1
        if not values:
            raise DocumentFormatError(f"Markdown line {self.index + 1}: expected blockquoted text.")
        return "\n".join(values)

    def field(self, name: str, level: int = 3) -> str:
        self.heading(name, level)
        return self.text()

    def items(self) -> list[str]:
        if self.peek() == "No entries.":
            self.expect("No entries.")
            return []
        values: list[str] = []
        while self.index < len(self.lines):
            line = self.lines[self.index]
            if line.startswith("- "):
                values.append(line[2:])
            elif line.startswith("  ") and values:
                values[-1] += "\n" + line[2:]
            else:
                break
            self.index += 1
        if not values:
            raise DocumentFormatError(f"Markdown line {self.index + 1}: expected a list.")
        return values

    def groups(self, label: str) -> Iterator[int]:
        if self.peek() == "No entries.":
            self.expect("No entries.")
            return
        number = 1
        while self.peek().startswith(f"### {label} "):
            self.heading(f"{label} {number}", 3)
            yield number
            number += 1
        if number == 1:
            raise DocumentFormatError(f"Expected numbered {label} group or 'No entries.'.")

    def finish(self) -> None:
        if self.peek():
            raise DocumentFormatError(
                f"Markdown line {self.index + 1}: unexpected document content."
            )
