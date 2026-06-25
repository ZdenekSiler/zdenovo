PROJECTS = [
    {
        "name": "zdenovo",
        "description": "Claude Code project template with design-then-implement workflow, custom skills, and parallel subagents.",
        "tags": ["python", "ai", "claude-code"],
        "url": "https://github.com/ZdenekSiler/zdenovo",
        "featured": True,
    },
    {
        "name": "Fakturant",
        "description": "Czech invoicing app with PDF export, ARES company lookup, and payment QR codes.",
        "tags": ["python", "fastapi", "invoicing"],
        "url": "/projects/fakturant",
        "featured": True,
        "internal": True,
    },
]


def get_all_projects():
    return sorted(PROJECTS, key=lambda p: p["featured"], reverse=True)
