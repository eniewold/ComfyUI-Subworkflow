# ComfyUI-Subworkflow

## Known Issues

- [x] When `Subworkflow Output` is placed between two nodes, the output node fails during execution. Use a preview image node as a reproduction example.
- [ ] The `Subworkflow` node progress can exceed 100%, sometimes reaching about 200%. Check with the upscale workflow example.
- [x] `Subworkflow Input` transparency for nodes is not always correct, for example when a concatenate string node is used.
- [x] Inner workflow nodes with a randomize-after-processing feature execute, but their updated values were not preserved because the inner workflow state was reloaded from disk.
- [x] Nodes were a mix of v1 and v3; `Subworkflow`, `Subworkflow Input`, and `Subworkflow Output` are now all V3 nodes.

Checked items are fixed. Unchecked items are known issues or follow-up work.
