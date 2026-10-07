# Change Event: Plus-address support and strict typing

Product now requires plus-addressed emails, such as
`alice+work@example.com`, to be accepted. The team also requires
`validators.py` to pass `mypy --strict`.

Update the shared `validate_email` function to accept plus-addressed
emails while continuing to reject invalid addresses. Give it complete
type annotations and return a `bool`.

Preserve the refactoring: both services must continue to import and
call `validate_email` from `validators.py`. Do not move validation
back into the services or modify the existing tests.
