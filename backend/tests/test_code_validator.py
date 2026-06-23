from code_validator import (
    CodeBlock,
    ValidationResult,
    extract_code_blocks,
    validate_code_block,
    validate_content,
    _preprocess_python_snippet,
)


# ─── Extraction ──────────────────────────────────────────────────────────────


def test_extract_single_block():
    md = "Some text\n\n```python\nprint('hi')\n```\n\nMore text"
    blocks = extract_code_blocks(md)
    assert len(blocks) == 1
    assert blocks[0].language == "python"
    assert "print('hi')" in blocks[0].code
    assert blocks[0].line_number == 3


def test_extract_multiple_blocks():
    md = "```python\nx = 1\n```\n\n```bash\necho hello\n```\n\n```json\n{}\n```"
    blocks = extract_code_blocks(md)
    assert len(blocks) == 3
    assert [b.language for b in blocks] == ["python", "bash", "json"]


def test_extract_no_blocks():
    assert extract_code_blocks("Just text, no code.") == []


def test_extract_block_with_no_language():
    md = "```\nsome output\n```"
    blocks = extract_code_blocks(md)
    assert len(blocks) == 1
    assert blocks[0].language == ""


def test_extract_preserves_content():
    code = "def greet(name: str) -> str:\n    return f'Hello {name}'\n"
    md = f"```python\n{code}```"
    blocks = extract_code_blocks(md)
    assert blocks[0].code == code


# ─── Python preprocessing ────────────────────────────────────────────────────


def test_preprocess_replaces_ellipsis():
    code = "def foo():\n    ..."
    result = _preprocess_python_snippet(code)
    assert "pass" in result
    assert "..." not in result


def test_preprocess_replaces_comment_ellipsis():
    code = "def foo():\n    # ..."
    result = _preprocess_python_snippet(code)
    assert "pass" in result


def test_preprocess_wraps_indented_only():
    code = "    x = 1\n    y = 2"
    result = _preprocess_python_snippet(code)
    assert result.startswith("def _snippet():")


def test_preprocess_leaves_normal_code():
    code = "x = 1\ny = 2"
    result = _preprocess_python_snippet(code)
    assert "def _snippet" not in result
    assert result == code


# ─── Python validation ───────────────────────────────────────────────────────


def test_validate_python_valid():
    block = CodeBlock(language="python", code="x = 1\nprint(x)", line_number=1)
    result = validate_code_block(block)
    assert result.status == "valid"


def test_validate_python_syntax_error():
    block = CodeBlock(language="python", code="def foo(\n", line_number=1)
    result = validate_code_block(block)
    assert result.status == "error"
    assert "SyntaxError" in result.message


def test_validate_python_with_ellipsis_placeholder():
    block = CodeBlock(language="python", code="def foo():\n    ...", line_number=1)
    result = validate_code_block(block)
    assert result.status == "valid"


def test_validate_python_indented_snippet():
    block = CodeBlock(language="python", code="    x = 1\n    return x", line_number=1)
    result = validate_code_block(block)
    assert result.status == "valid"


def test_validate_python_function_definition():
    code = "def process_items(items: list[str]) -> None:\n    for item in items:\n        print(item)"
    block = CodeBlock(language="python", code=code, line_number=1)
    result = validate_code_block(block)
    assert result.status == "valid"


def test_validate_py_alias():
    block = CodeBlock(language="py", code="x = 1", line_number=1)
    result = validate_code_block(block)
    assert result.status == "valid"


# ─── Bash validation ─────────────────────────────────────────────────────────


def test_validate_bash_valid():
    block = CodeBlock(language="bash", code="echo 'hello world'", line_number=1)
    result = validate_code_block(block)
    assert result.status == "valid"


def test_validate_bash_syntax_error():
    block = CodeBlock(language="bash", code="if then fi", line_number=1)
    result = validate_code_block(block)
    assert result.status == "error"


def test_validate_sh_alias():
    block = CodeBlock(language="sh", code="ls -la", line_number=1)
    result = validate_code_block(block)
    assert result.status == "valid"


# ─── YAML validation ─────────────────────────────────────────────────────────


def test_validate_yaml_valid():
    block = CodeBlock(language="yaml", code="key: value\nlist:\n  - item1", line_number=1)
    result = validate_code_block(block)
    assert result.status == "valid"


def test_validate_yaml_invalid():
    block = CodeBlock(language="yaml", code="key: value\n  bad indent:\n nope", line_number=1)
    result = validate_code_block(block)
    assert result.status in ("error", "skipped")


# ─── JSON validation ─────────────────────────────────────────────────────────


def test_validate_json_valid():
    block = CodeBlock(language="json", code='{"key": "value", "num": 42}', line_number=1)
    result = validate_code_block(block)
    assert result.status == "valid"


def test_validate_json_invalid():
    block = CodeBlock(language="json", code='{key: value}', line_number=1)
    result = validate_code_block(block)
    assert result.status == "error"
    assert "JSON error" in result.message


# ─── Skip behavior ───────────────────────────────────────────────────────────


def test_mermaid_skipped():
    block = CodeBlock(language="mermaid", code="graph TD\nA-->B", line_number=1)
    result = validate_code_block(block)
    assert result.status == "skipped"


def test_no_language_skipped():
    block = CodeBlock(language="", code="some output", line_number=1)
    result = validate_code_block(block)
    assert result.status == "skipped"


def test_unknown_language_skipped():
    block = CodeBlock(language="rust", code="fn main() {}", line_number=1)
    result = validate_code_block(block)
    assert result.status == "skipped"
    assert "No validator" in result.message


# ─── validate_content (end-to-end) ───────────────────────────────────────────


def test_validate_content_mixed():
    md = """# My Post

```python
x = 1
print(x)
```

Some text.

```bash
echo hello
```

```mermaid
graph TD
A-->B
```

```json
{"valid": true}
```
"""
    summary = validate_content(md)
    assert summary.total == 4
    assert summary.valid == 3
    assert summary.skipped == 1
    assert summary.errors == 0


def test_validate_content_no_code():
    summary = validate_content("Just a text post with no code blocks at all.")
    assert summary.total == 0
    assert summary.valid == 0


def test_validate_content_with_error():
    md = "```python\ndef foo(\n```"
    summary = validate_content(md)
    assert summary.total == 1
    assert summary.errors == 1


def test_code_preview_truncated():
    long_code = "x = " + "a" * 200
    block = CodeBlock(language="python", code=long_code, line_number=1)
    result = validate_code_block(block)
    assert len(result.code_preview) <= 80
