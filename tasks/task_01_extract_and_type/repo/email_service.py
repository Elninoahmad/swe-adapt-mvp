import re


def send_email(address):
    """Send an email after validating the address."""
    if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', address):
        raise ValueError("Invalid email")
    return f"Sent to {address}"
