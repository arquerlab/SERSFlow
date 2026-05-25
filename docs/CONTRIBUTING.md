# Contributing

## Paths in documentation

Use **forward slashes** in markdown and code snippets for repository paths (for example `src/sersflow/api/main.py`, `frontend/src/main.tsx`). This keeps docs consistent across platforms.

## Local commands on Windows

Examples in READMEs may use Unix-style chaining (`cd foo && pytest`). In **PowerShell**, use `Set-Location foo; pytest` or run commands from the project root in separate steps. The project root is the git checkout directory (for example `C:\Users\you\Documents\SERSFlow`).
