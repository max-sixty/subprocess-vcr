# subprocess-vcr Development Guidelines

A concise guide for working on this subprocess recording/replay testing library.

## Core Principles

1. **Simplicity First**: This is a focused testing library. Keep it simple and avoid feature creep.

2. **Fail Fast and Clearly**: When recordings don't match or something goes wrong, provide immediate, actionable error messages.

3. **No Premature Abstraction**: Don't add configuration options or abstractions without clear user needs.

## Development Workflow

### Running Commands

Always use `uv run` to ensure the correct virtual environment:

```bash
uv run pytest                # Run tests
uv run mypy                  # Type check
uv run pre-commit run --all-files  # Run all lints and formatting
```

### Testing

After making changes, always run tests and lints:

```bash
# Run all tests
uv run pytest

# Run all lints (formatting, type checking, etc.)
uv run pre-commit run --all-files
```

Before returning to the user, ALWAYS run all tests and pre-commit to ensure code quality.

### Code Quality

- **Type hints**: Use modern syntax (`dict` not `Dict`, `| None` not `Optional`)
- **Imports**: Always at the top of files
- **Direct access**: After validation, use direct dictionary access (no defensive `.get()`)
- **Clear errors**: Provide actionable error messages with context

## What to Avoid

- Don't add configuration options "just in case"
- Don't use defensive programming for data we control
- Don't maintain backwards compatibility (we're pre-1.0)
- Don't create wrapper functions that just redirect
- Don't comment out code - delete it (Git tracks history)

## Examples

<example>
<bad>
```python
# Defensive programming for cassette data we control
if cassette_data and cassette_data.get("recordings"):
    for recording in cassette_data.get("recordings", []):
        if recording.get("command"):
            # ...
```
</bad>
<good>
```python
# Direct access - we control this data format
for recording in cassette_data["recordings"]:
    command = recording["command"]
    # ...
```
</good>
</example>

## Library-Specific Guidelines

### VCR Cassette Handling

- Cassettes should be deterministic and portable
- Filter out dynamic values (timestamps, temp paths) consistently
- Provide clear error messages when recordings don't match
- Keep cassette format simple and human-readable (YAML)

### Testing the Test Library

When testing subprocess-vcr itself:
- Use the VCR fixtures to test VCR behavior
- Keep test cassettes minimal and focused
- Test both recording and replay modes
- Verify error messages are helpful

### Filter Design

Filters should:
- Have a single, clear purpose
- Be composable (work well with other filters)
- Document what they normalize/redact
- Preserve enough information for debugging
