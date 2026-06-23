import ast
import json
import re
import subprocess

from pydantic import BaseModel, Field

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ─── Models ──────────────────────────────────────────────────────────────────


class CodeBlock(BaseModel):
    language: str
    code: str
    line_number: int


class ValidationResult(BaseModel):
    status: str
    message: str
    language: str
    line_number: int
    code_preview: str


class ValidationSummary(BaseModel):
    results: list[ValidationResult] = Field(default_factory=list)
    total: int = 0
    valid: int = 0
    warnings: int = 0
    errors: int = 0
    skipped: int = 0


# ─── Extraction ──────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^```(\w*)\n(.*?)^```", re.MULTILINE | re.DOTALL)


def extract_code_blocks(markdown: str) -> list[CodeBlock]:
    blocks = []
    for match in _FENCE_RE.finditer(markdown):
        lang = match.group(1).lower()
        code = match.group(2)
        line_number = markdown[: match.start()].count("\n") + 1
        blocks.append(CodeBlock(language=lang, code=code, line_number=line_number))
    return blocks


# ─── Python preprocessing ────────────────────────────────────────────────────


def _preprocess_python_snippet(code: str) -> str:
    lines = code.split("\n")
    processed = []
    for line in lines:
        stripped = line.strip()
        if stripped == "..." or stripped == "# ...":
            indent = len(line) - len(line.lstrip())
            processed.append(" " * indent + "pass")
        else:
            processed.append(line)

    result = "\n".join(processed)

    non_empty = [l for l in processed if l.strip()]
    if non_empty and all(l.startswith((" ", "\t")) for l in non_empty):
        result = "def _snippet():\n" + result

    return result


# ─── Per-language validators ─────────────────────────────────────────────────


def _validate_python(code: str) -> tuple[str, str]:
    preprocessed = _preprocess_python_snippet(code)
    try:
        ast.parse(preprocessed)
        return "valid", "Syntax OK"
    except SyntaxError as e:
        return "error", f"SyntaxError: {e.msg} (line {e.lineno})"


def _validate_bash(code: str) -> tuple[str, str]:
    try:
        result = subprocess.run(
            ["bash", "-n", "-c", code],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return "valid", "Syntax OK"
        err = result.stderr.strip().split("\n")[0] if result.stderr else "syntax error"
        return "error", err
    except subprocess.TimeoutExpired:
        return "warning", "Syntax check timed out"
    except FileNotFoundError:
        return "skipped", "bash not available"


def _validate_yaml(code: str) -> tuple[str, str]:
    if not HAS_YAML:
        return "skipped", "PyYAML not installed"
    try:
        yaml.safe_load(code)
        return "valid", "Valid YAML"
    except yaml.YAMLError as e:
        return "error", f"YAML error: {e}"


def _validate_json(code: str) -> tuple[str, str]:
    try:
        json.loads(code)
        return "valid", "Valid JSON"
    except json.JSONDecodeError as e:
        return "error", f"JSON error: {e.msg} (line {e.lineno})"


# ─── Dispatch ────────────────────────────────────────────────────────────────

_VALIDATORS = {
    "python": _validate_python,
    "py": _validate_python,
    "bash": _validate_bash,
    "sh": _validate_bash,
    "shell": _validate_bash,
    "yaml": _validate_yaml,
    "yml": _validate_yaml,
    "json": _validate_json,
}

_SKIP_LANGUAGES = {"mermaid", "text", "plaintext", "output", "log", "diff", "csv", ""}


def validate_code_block(block: CodeBlock) -> ValidationResult:
    preview = block.code.strip()[:80]

    if block.language in _SKIP_LANGUAGES:
        return ValidationResult(
            status="skipped",
            message=f"{'No language tag' if not block.language else block.language} — not validated",
            language=block.language,
            line_number=block.line_number,
            code_preview=preview,
        )

    validator = _VALIDATORS.get(block.language)
    if validator is None:
        return ValidationResult(
            status="skipped",
            message=f"No validator for '{block.language}'",
            language=block.language,
            line_number=block.line_number,
            code_preview=preview,
        )

    status, message = validator(block.code)
    return ValidationResult(
        status=status,
        message=message,
        language=block.language,
        line_number=block.line_number,
        code_preview=preview,
    )


# ─── Entry point ─────────────────────────────────────────────────────────────


def validate_content(markdown: str) -> ValidationSummary:
    blocks = extract_code_blocks(markdown)
    results = [validate_code_block(b) for b in blocks]
    return ValidationSummary(
        results=results,
        total=len(results),
        valid=sum(1 for r in results if r.status == "valid"),
        warnings=sum(1 for r in results if r.status == "warning"),
        errors=sum(1 for r in results if r.status == "error"),
        skipped=sum(1 for r in results if r.status == "skipped"),
    )
