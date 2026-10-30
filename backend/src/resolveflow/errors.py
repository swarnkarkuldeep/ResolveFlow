from fastapi import HTTPException


def err(status: int, code: str, message: str) -> HTTPException:
    """Errors carry a stable machine code and a plain-language message the UI can show."""
    return HTTPException(status_code=status, detail={"code": code, "message": message})
