# Task 01: Extract shared validation

Refactor `email_service.py` and `user_service.py` to remove their duplicated email validation logic.

Create `validators.py` in the `repo` folder, then update both services to import and use the shared validator. Remove their inline regex checks. Keep the existing behavior and tests passing.

Do not modify the tests.
