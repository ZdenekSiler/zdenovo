PROJECTS = [
    {
        "name": "zdenovo",
        "description": "Claude Code project template with design-then-implement workflow, custom skills, and parallel subagents.",
        "tags": ["python", "ai", "claude-code"],
        "url": "https://github.com/zdenek/zdenovo",
        "featured": True,
    },
    {
        "name": "type-enforcer",
        "description": "A mypy plugin that enforces strict type annotation coverage on new code without breaking existing files.",
        "tags": ["python", "tooling", "mypy"],
        "url": "https://github.com/zdenek/type-enforcer",
        "featured": True,
    },
    {
        "name": "logpipe",
        "description": "Lightweight structured logging library for Python with zero-dependency JSON output and level filtering.",
        "tags": ["python", "logging", "library"],
        "url": "https://github.com/zdenek/logpipe",
        "featured": False,
    },
    {
        "name": "page-drift",
        "description": "CLI tool that monitors web pages for changes and sends a digest notification — no JavaScript scraping required.",
        "tags": ["python", "cli", "web"],
        "url": "https://github.com/zdenek/page-drift",
        "featured": False,
    },
]


def get_all_projects():
    return sorted(PROJECTS, key=lambda p: p["featured"], reverse=True)
