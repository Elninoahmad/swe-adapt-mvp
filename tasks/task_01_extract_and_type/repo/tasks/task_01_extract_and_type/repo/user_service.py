import re


def create_user(email):
    """Create a user after validating the email."""
    if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
        raise ValueError("Invalid email")
    return {"email": email, "created": True}
