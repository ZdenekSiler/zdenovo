"""HTML sanitization for user-generated content (Markdown posts)."""
import bleach
import mistune
from markupsafe import Markup

# Allowed HTML tags for blog posts (generated from Markdown)
ALLOWED_TAGS = [
    "p", "br", "strong", "em", "a", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "blockquote", "pre", "code", "hr", "table", "thead",
    "tbody", "tr", "th", "td", "img", "section", "article", "div", "span",
]

# Allowed attributes for tags
ALLOWED_ATTRS = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "div": ["class"],
    "span": ["class"],
    "p": ["class"],
    "code": ["class"],
    "pre": ["class"],
}


def safe_markdown(content: str) -> str:
    """
    Convert Markdown to HTML and sanitize to prevent XSS attacks.
    
    Args:
        content: Raw Markdown text
        
    Returns:
        Sanitized HTML safe for display in templates
    """
    # Convert Markdown to HTML
    html = mistune.html(content)
    
    # Sanitize HTML to remove malicious tags/attributes
    safe_html = bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        strip=True  # Strip disallowed tags instead of escaping
    )
    
    return Markup(safe_html)  # nosec B704 — safe_html is bleach-sanitized above
