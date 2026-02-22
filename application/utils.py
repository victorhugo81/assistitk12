"""
Utility functions for the AssistITK12 application.
Contains reusable validation and helper functions.
"""
import re
import hashlib
import base64
from typing import Tuple, Optional
from cryptography.fernet import Fernet, InvalidToken


def _get_fernet(secret_key: str) -> Fernet:
    """Derive a Fernet instance from the app SECRET_KEY."""
    key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest())
    return Fernet(key)


def encrypt_mail_password(password: str, secret_key: str) -> str:
    """Encrypt a plain-text SMTP password for storage in the database."""
    if not password:
        return ''
    return _get_fernet(secret_key).encrypt(password.encode()).decode()


def decrypt_mail_password(encrypted: str, secret_key: str) -> str:
    """Decrypt a stored SMTP password. Returns '' on failure."""
    if not encrypted:
        return ''
    try:
        return _get_fernet(secret_key).decrypt(encrypted.encode()).decode()
    except InvalidToken:
        return ''


def validate_password(password: str, min_length: int = 12) -> Tuple[bool, Optional[str]]:
    """
    Validate password complexity requirements.

    Password must:
    - Be at least min_length characters long (default 12)
    - Contain at least one uppercase letter
    - Contain at least one lowercase letter
    - Contain at least one number
    - Contain at least one special character

    Args:
        password (str): The password to validate
        min_length (int): Minimum password length (default: 12)

    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
            - is_valid: True if password meets all requirements, False otherwise
            - error_message: Description of validation failure, None if valid

    Example:
        >>> is_valid, error = validate_password("MyP@ssw0rd123")
        >>> if not is_valid:
        ...     flash(error, 'danger')
    """
    if not password:
        return False, "Password is required"

    if len(password) < min_length:
        return False, f"Password must be at least {min_length} characters long"

    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"

    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"

    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least one number"

    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character (!@#$%^&*(),.?\":{}|<>)"

    return True, None


def validate_file_upload(file, allowed_extensions=None, max_size_mb=5):
    """
    Validate uploaded files for security using both extension and magic byte checks.

    Defends against:
    - Extension spoofing (e.g., malware.php renamed to malware.jpg)
    - Oversized uploads
    - Empty files

    Args:
        file: FileStorage object from request.files
        allowed_extensions (set): Set of allowed file extensions (e.g., {'.jpg', '.pdf'})
        max_size_mb (int): Maximum file size in megabytes

    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    import os

    # Magic bytes (file signatures) for allowed types
    MAGIC_BYTES = {
        b'\xff\xd8\xff': '.jpg',         # JPEG
        b'\x89PNG\r\n\x1a\n': '.png',   # PNG
        b'%PDF': '.pdf',                 # PDF
    }

    if allowed_extensions is None:
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.pdf'}

    if not file or not file.filename:
        return False, "No file selected"

    # 1. Check file extension
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        allowed = ', '.join(sorted(allowed_extensions))
        return False, f"Invalid file type. Allowed types: {allowed}"

    # 2. Check file size
    file.seek(0, os.SEEK_END)
    file_length = file.tell()
    file.seek(0)  # Reset file pointer

    if file_length == 0:
        return False, "File is empty"

    max_bytes = max_size_mb * 1024 * 1024
    if file_length > max_bytes:
        return False, f"File size exceeds {max_size_mb}MB limit"

    # 3. Validate actual file content using magic bytes
    header = file.read(8)
    file.seek(0)  # Reset file pointer after reading

    matched_type = None
    for magic, ext in MAGIC_BYTES.items():
        if header.startswith(magic):
            matched_type = ext
            break

    if matched_type is None:
        return False, "File content does not match an allowed file type (JPG, PNG, PDF)"

    # 4. Ensure extension matches the actual file content
    # .jpg and .jpeg both map to the JPEG magic bytes
    if matched_type == '.jpg' and file_ext not in {'.jpg', '.jpeg'}:
        return False, "File extension does not match file content"
    elif matched_type != '.jpg' and file_ext != matched_type:
        return False, "File extension does not match file content"

    return True, None
