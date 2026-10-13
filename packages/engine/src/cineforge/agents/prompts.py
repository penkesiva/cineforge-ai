"""Versioned prompt templates: ``<prompts_dir>/<template_id>/v<version>.md``.

Templates use ``string.Template`` ``$placeholders`` and are rendered with
``safe_substitute`` (unknown placeholders stay verbatim). A leading HTML comment
(``<!-- id: ... -->``) is a header for humans and is stripped before rendering.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

log = logging.getLogger(__name__)

_HEADER = re.compile(r"\A\s*<!--.*?-->\s*", re.DOTALL)


class PromptTemplateNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class PromptTemplate:
    template_id: str
    version: int
    body: str
    path: Path | None = None

    @property
    def ref(self) -> str:
        return f"{self.template_id}@v{self.version}"

    def placeholders(self) -> set[str]:
        return {
            m.group("named") or m.group("braced")
            for m in Template.pattern.finditer(self.body)
            if m.group("named") or m.group("braced")
        }

    def render(self, **values: Any) -> str:
        return Template(self.body).safe_substitute({k: str(v) for k, v in values.items()}).strip()


class PromptLibrary:
    def __init__(self, prompts_dir: Path) -> None:
        self.prompts_dir = Path(prompts_dir)
        self._cache: dict[tuple[str, int], PromptTemplate] = {}
        self._lock = threading.Lock()

    def path_for(self, template_id: str, version: int) -> Path:
        return self.prompts_dir / template_id / f"v{version}.md"

    def get(self, template_id: str, version: int = 1) -> PromptTemplate:
        key = (template_id, version)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached
        path = self.path_for(template_id, version)
        if not path.is_file():
            raise PromptTemplateNotFoundError(f"prompt template {template_id}@v{version}: {path}")
        template = PromptTemplate(
            template_id=template_id,
            version=version,
            body=_HEADER.sub("", path.read_text(encoding="utf-8"), count=1),
            path=path,
        )
        with self._lock:
            self._cache[key] = template
        return template

    def get_or_fallback(self, template_id: str, version: int = 1) -> PromptTemplate:
        """Like ``get`` but degrades to a minimal inline template if the file is missing."""
        try:
            return self.get(template_id, version)
        except PromptTemplateNotFoundError:
            log.warning("prompt template %s@v%s missing; using fallback", template_id, version)
            return PromptTemplate(template_id, version, "$task\n\n$context")
