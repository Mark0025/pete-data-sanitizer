## backend/

This folder is reserved for the Python “backend” of this project.

### Current status
The backend code currently lives at the repo root:

- `pete_dm_clean/` (CLI + server + runtime tracking)
- `build_staging.py` (pipeline implementation)
- `loaders.py` (CSV/XLSX loading)

We are keeping the existing entrypoints working while we grow the project. When we decide to migrate, we can move modules into `backend/` and keep thin compatibility shims at the old paths.

