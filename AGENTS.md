# Repository Guidelines

## Project Structure & Module Organization

This repository is a ComfyUI custom node package. Python source files live at the repository root:

- `__init__.py` registers the extension, web directory, nodes, and server routes.
- `nodes.py` defines the V3 `SubworkflowInput` and `SubworkflowOutput` passthrough nodes.
- `workflow_node.py` defines the V3 `Subworkflow` node wrapper.
- `workflow_utils.py` contains workflow loading, I/O discovery, and graph expansion logic.
- `server_routes.py` exposes HTTP routes used by the UI extension.
- `js/subworkflow.js` contains browser-side ComfyUI behavior for dynamic slots.

There is currently no dedicated `tests/` directory or bundled asset folder. Keep new runtime code close to the module it supports unless a reusable helper clearly belongs in `workflow_utils.py`.

## Build, Test, and Development Commands

- `python -m py_compile __init__.py nodes.py workflow_node.py workflow_utils.py server_routes.py` checks Python syntax without launching ComfyUI.
- Start ComfyUI normally with this directory installed under `ComfyUI/custom_nodes/`; ComfyUI loads the package through `comfy_entrypoint()`.
- Restart ComfyUI after Python changes. Browser-side changes in `js/subworkflow.js` may also require a hard refresh.

The `pyproject.toml` declares package metadata and Python `>=3.10`, but does not define build, lint, or test scripts.

## Coding Style & Naming Conventions

Use Python 3.10+ syntax and 4-space indentation. Follow the existing style: small modules, explicit imports, descriptive helper names, and ComfyUI-facing constants in uppercase. Node IDs use the `SWF_` prefix, for example `SWF_SubworkflowInput`; display names should be human-readable, for example `Subworkflow`. Node categories should use `Subworkflow` capitalization. Prefer concise comments only where ComfyUI integration behavior is non-obvious.

JavaScript should stay scoped to ComfyUI extension behavior in `js/subworkflow.js`. Match existing naming and avoid broad global state unless required by the ComfyUI frontend API.

## Runtime Behavior Notes

- `Subworkflow`, `Subworkflow Input`, and `Subworkflow Output` are V3 nodes. Do not reintroduce V1 node APIs unless there is a specific compatibility task.
- `Subworkflow` dynamically updates its UI slots from the selected inner workflow through `server_routes.py` and `js/subworkflow.js`.
- The workflow selector uses an empty placeholder value when no workflow is selected.
- The `at execution` option controls whether the inner workflow is reloaded for every execution or kept loaded so ComfyUI-style widget state updates can persist.
- `Subworkflow Input` and `Subworkflow Output` must remain usable as passthrough nodes when the workflow is executed standalone.
- When an inner workflow is expanded, `Subworkflow Input` values come from the outer `Subworkflow` inputs and `Subworkflow Output` values become the outer outputs.
- Preserve support for UI-format workflows, API-format workflows, UI subgraphs, UUID node types resolved through `properties["Node name for S&R"]`, list and object link shapes, and list or dictionary widget values.
- Keep type information on dynamic slots accurate where it is available. Runtime validation should raise clear errors for known concrete type mismatches instead of letting confusing downstream errors surface.

## Testing Guidelines

No automated test suite is present. For now, validate changes with syntax checks and a manual ComfyUI run using workflows that include `Subworkflow Input`, `Subworkflow Output`, and `Subworkflow`. When adding tests, place them under `tests/`, name files `test_*.py`, and focus on pure workflow parsing and graph expansion helpers before UI-dependent behavior.

## Commit & Pull Request Guidelines

Use short imperative commit subjects such as `Fix workflow output slot expansion` or `Add route validation`.

Pull requests should include a clear description, affected nodes or routes, manual validation steps, and screenshots or short recordings for UI changes. Link related issues or README known-issue items when applicable, especially current concerns around progress reporting, optional outputs, path macros, progress borders, and input/output ordering.
