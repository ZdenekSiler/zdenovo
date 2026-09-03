PROJECTS = [
    {
        "name": "zdenovo",
        "description": "Claude Code project template with design-then-implement workflow, custom skills, and parallel subagents.",
        "tags": ["python", "ai", "claude-code"],
        "url": "https://github.com/ZdenekSiler/zdenovo",
        "featured": True,
        "icon": "github",
    },
    {
        "name": "Fakturant",
        "description": "Czech invoicing app with PDF export, ARES company lookup, and payment QR codes.",
        "tags": ["python", "fastapi", "invoicing"],
        "url": "/projects/fakturant",
        "featured": True,
        "internal": True,
        "icon": "receipt",
    },
    {
        "name": "Terraform Quiz",
        "description": "Practice app for the HashiCorp Terraform Associate (004) — 205 explained questions and a timed mock exam.",
        "tags": ["terraform", "javascript", "certification"],
        "url": "/projects/terraform-quiz",
        "featured": True,
        "internal": True,
        "icon": "quiz",
    },
]


def get_all_projects():
    return sorted(PROJECTS, key=lambda p: p["featured"], reverse=True)
