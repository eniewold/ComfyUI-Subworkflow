# Repository Guidelines

## Project Structure & Module Organization

This repository is a ComfyUI custom node package. Python source files live at the repository root:

- `__init__.py` registers the extension, web directory, nodes, and server routes.
- `nodes.py` defines the V3 `FunctionInput` and `FunctionOutput` passthrough nodes.
- `workflow_node.py` defines the legacy `FunctionWorkflow` node wrapper.
- `workflow_utils.py` contains workflow loading, I/O discovery, and graph expansion logic.
- `server_routes.py` exposes HTTP routes used by the UI extension.
- `js/function_workflow.js` contains browser-side ComfyUI behavior for dynamic slots.

There is currently no dedicated `tests/` directory or bundled asset folder. Keep new runtime code close to the module it supports unless a reusable helper clearly belongs in `workflow_utils.py`.

## Build, Test, and Development Commands

- `python -m py_compile __init__.py nodes.py workflow_node.py workflow_utils.py server_routes.py` checks Python syntax without launching ComfyUI.
- Start ComfyUI normally with this directory installed under `ComfyUI/custom_nodes/`; ComfyUI loads the package through `comfy_entrypoint()`.
- Restart ComfyUI after Python changes. Browser-side changes in `js/function_workflow.js` may also require a hard refresh.

The `pyproject.toml` declares package metadata and Python `>=3.10`, but does not define build, lint, or test scripts.

## Coding Style & Naming Conventions

Use Python 3.10+ syntax and 4-space indentation. Follow the existing style: small modules, explicit imports, descriptive helper names, and ComfyUI-facing constants in uppercase. Node IDs use the `WFF_` prefix, for example `WFF_FunctionInput`; display names should be human-readable, for example `Subworkflow`. Prefer concise comments only where ComfyUI integration behavior is non-obvious.

JavaScript should stay scoped to ComfyUI extension behavior in `js/function_workflow.js`. Match existing naming and avoid broad global state unless required by the ComfyUI frontend API.

## Testing Guidelines

No automated test suite is present. For now, validate changes with syntax checks and a manual ComfyUI run using workflows that include `Subworkflow Input`, `Subworkflow Output`, and `Subworkflow`. When adding tests, place them under `tests/`, name files `test_*.py`, and focus on pure workflow parsing and graph expansion helpers before UI-dependent behavior.

## Commit & Pull Request Guidelines

This checkout has no `.git` history, so no project-specific commit convention is established. Use short imperative commit subjects such as `Fix workflow output slot expansion` or `Add route validation`.

Pull requests should include a clear description, affected nodes or routes, manual validation steps, and screenshots or short recordings for UI changes. Link related issues or TODO items when applicable, especially current concerns in `TODO.md` around output passthrough, progress reporting, and input transparency.
