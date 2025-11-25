"""
Text and code file reader.

Handles .txt, .md, .json, and code files (.ts, .tsx, .js, .py, .yml, .yaml, .toml, etc.).
"""
from pathlib import Path
from typing import Optional


def read_text_file(path: Path) -> Optional[str]:
    """
    Read a text or code file as UTF-8.
    
    Args:
        path: Path to the file
        
    Returns:
        File contents as string, or None if read fails
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        # Try with error handling
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        except Exception as e:
            print(f"Error reading text file {path}: {e}")
            return None
    except Exception as e:
        print(f"Error reading text file {path}: {e}")
        return None

