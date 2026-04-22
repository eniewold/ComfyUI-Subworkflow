# ComfyUI-Subworkflow

## Known Issues

- [ ] When `Subworkflow Output` is placed between two nodes, the output node fails during execution. Use a preview image node as a reproduction example.
- [ ] The `Subworkflow` node progress can exceed 100%, sometimes reaching about 200%. Check with the upscale workflow example.
- [ ] `Subworkflow Input` transparency for nodes is not always correct, for example when a concatenate string node is used.
- [x] Inner workflow nodes with a randomize-after-processing feature execute, but their updated values were not preserved because the inner workflow state was reloaded from disk.
- [ ] Nodes are currently a mix of v1 and v3. This works, but it would be better to migrate all nodes to v3 if the `Subworkflow` node can be moved safely.

Checked items are fixed. Unchecked items are known issues or follow-up work.
