from helpers import clean_text

def format_greeting(name: str) -> str:
    return f"Hello, {clean_text(name)}!"
