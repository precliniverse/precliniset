# app/utils/files.py
import io
import os
import magic
import pandas as pd
from flask import current_app

# Centralized allowed MIME types mapped to extensions
ALLOWED_MIME_TYPES = {
    'image/jpeg': ['.jpg', '.jpeg'],
    'image/png': ['.png'],
    'image/gif': ['.gif'],
    'application/pdf': ['.pdf'],
    'application/msword': ['.doc'],
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
    'application/vnd.ms-excel': ['.xls'],
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
    'application/vnd.ms-powerpoint': ['.ppt'],
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
    'text/plain': ['.txt'],
    'text/csv': ['.csv'],
    'application/zip': ['.zip'],
    'application/xml': ['.xml'],
    'text/xml': ['.xml']
}

def validate_file_type(file_storage, allowed_mimes_dict=None):
    """
    Validates file MIME type using magic bytes AND extension matching.
    Raises ValueError if invalid.
    """
    if allowed_mimes_dict is None:
        allowed_mimes_dict = ALLOWED_MIME_TYPES
    
    filename = file_storage.filename.lower()
    ext = os.path.splitext(filename)[1]

    # 1. Check extension presence
    if not ext:
         raise ValueError("File has no extension.")

    # 2. Read magic bytes
    header = file_storage.read(2048)
    file_storage.seek(0) # Reset pointer
    
    detected_mime = magic.from_buffer(header, mime=True)
    
    # 3. Check if MIME is allowed
    if detected_mime not in allowed_mimes_dict:
        raise ValueError(f"File type '{detected_mime}' is not allowed.")

    # 4. Check if extension matches the detected MIME type
    valid_extensions = allowed_mimes_dict[detected_mime]
    if ext not in valid_extensions:
        raise ValueError(f"File extension '{ext}' does not match detected type '{detected_mime}'.")

    return True

def read_excel_to_list(file_storage, sheet_name=0):
    """
    Reads an Excel file into a list of dictionaries.
    Handles NaN values by converting them to None.
    """
    try:
        # Security check before processing
        file_storage.seek(0, os.SEEK_END)
        size = file_storage.tell()
        file_storage.seek(0)
        
        # Limit 10MB for processing in-memory to prevent DoS
        if size > 10 * 1024 * 1024:
            raise ValueError("File too large for processing (Limit 10MB).")

        df = pd.read_excel(file_storage, sheet_name=sheet_name, keep_default_na=False)
        # Replace NaN with None for JSON/DB compatibility
        df = df.where(pd.notnull(df), None)
        return df.to_dict(orient='records'), df.columns.tolist()
    except Exception as e:
        current_app.logger.error(f"Error reading Excel file: {e}")
        raise ValueError(f"Failed to parse Excel file: {str(e)}")

def _sanitize_for_excel(val):
    """
    Prevents CSV/Excel injection by prepending a single quote to values
    starting with dangerous characters (=, +, -, @).
    """
    if isinstance(val, str) and val.startswith(('=', '+', '-', '@')):
        return f"'{val}"
    return val

def dataframe_to_excel_bytes(df, sheet_name='Sheet1', **kwargs):
    """
    Converts a pandas DataFrame to an Excel file in memory (BytesIO).
    Sanitizes data to prevent formula injection.
    """
    output = io.BytesIO()
    if 'index' not in kwargs:
        kwargs['index'] = False

    try:
        # Create a copy to avoid modifying the original dataframe
        df_safe = df.copy()

        # Apply sanitization to all object (string) columns
        for col in df_safe.select_dtypes(include=['object']).columns:
            df_safe[col] = df_safe[col].apply(_sanitize_for_excel)

        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_safe.to_excel(writer, sheet_name=sheet_name, **kwargs)
        output.seek(0)
        return output
    except Exception as e:
        current_app.logger.error(f"Error writing Excel file: {e}")
        raise ValueError(f"Failed to generate Excel file: {str(e)}")
